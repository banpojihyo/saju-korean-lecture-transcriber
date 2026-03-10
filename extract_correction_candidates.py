#!/usr/bin/env python3
"""Find suspicious transcript lines for batch review.

This scans corrected script files for:
1) known wrong phrases that still remain after correction
2) optional custom regex patterns

For each hit, it reports:
- script file path
- script line number
- nearest corrected timestamp
- matched phrase / pattern
- full script line
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from correct_daglo_file import (
    FILE_OVERRIDES_FILENAME,
    load_file_overrides,
    load_replace_pairs,
    manual_pairs,
)


TIMESTAMP_LINE_RE = re.compile(r"^\s*((?:\d{1,2}:)?\d{1,2}:\d{2})(?:\s*화자\s*\d+)?\s*$")


@dataclass(frozen=True)
class CandidateHit:
    pattern: str
    match_kind: str
    file_path: str
    line_no: int
    timestamp: str
    line_text: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract suspicious transcript candidates from corr/script files."
    )
    parser.add_argument(
        "--script-root",
        default="data/daglo/corr/script",
        help="Script root path (default: data/daglo/corr/script).",
    )
    parser.add_argument(
        "--corrected-root",
        default="data/daglo/corr/corrected",
        help="Corrected root path (default: data/daglo/corr/corrected).",
    )
    parser.add_argument(
        "--dict-root",
        default="dict",
        help="Dictionary root path (default: dict).",
    )
    parser.add_argument(
        "--topic",
        default="",
        help="Optional topic under dict/topics to merge with dict/common.",
    )
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help="Target file or directory under script root. Repeat for multiple targets.",
    )
    parser.add_argument(
        "--regex",
        action="append",
        default=[],
        help="Extra regex pattern to scan. Repeat for multiple patterns.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional output path. If omitted, print to stdout.",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format (default: markdown).",
    )
    return parser.parse_args()


def unique_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def load_literal_patterns(dict_root: Path, topic: str) -> list[str]:
    patterns = [wrong for wrong, _ in load_replace_pairs(dict_root / "common" / "replace.csv")]
    if topic:
        patterns.extend(
            wrong
            for wrong, _ in load_replace_pairs(
                dict_root / "topics" / topic / "replace.csv"
            )
        )
    patterns.extend(wrong for wrong, _ in manual_pairs())
    patterns = unique_preserve_order(patterns)
    patterns.sort(key=len, reverse=True)
    return patterns


def load_file_override_patterns(dict_root: Path, topic: str) -> list[tuple[str, str]]:
    patterns: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for override in load_file_overrides(dict_root / "common" / FILE_OVERRIDES_FILENAME):
        pair = (override.path, override.wrong)
        if pair in seen:
            continue
        seen.add(pair)
        patterns.append(pair)
    if topic:
        for override in load_file_overrides(
            dict_root / "topics" / topic / FILE_OVERRIDES_FILENAME
        ):
            pair = (override.path, override.wrong)
            if pair in seen:
                continue
            seen.add(pair)
            patterns.append(pair)
    return patterns


def resolve_targets(script_root: Path, raw_targets: list[str]) -> list[Path]:
    if not raw_targets:
        return sorted(script_root.rglob("*.txt"))

    resolved: list[Path] = []
    for raw_target in raw_targets:
        candidate = Path(raw_target)
        if not candidate.is_absolute():
            candidate = script_root / raw_target
        if candidate.is_file():
            resolved.append(candidate)
            continue
        if candidate.is_dir():
            resolved.extend(sorted(candidate.rglob("*.txt")))
            continue
        raise FileNotFoundError(f"target not found: {raw_target}")
    return resolved


def load_script_lines(path: Path) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = raw_line.strip()
        if not text:
            continue
        lines.append((line_no, text))
    return lines


def load_corrected_entries(path: Path) -> list[tuple[int, str, str]]:
    entries: list[tuple[int, str, str]] = []
    current_timestamp = ""
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        timestamp_match = TIMESTAMP_LINE_RE.match(stripped)
        if timestamp_match:
            current_timestamp = timestamp_match.group(1)
            continue
        entries.append((line_no, current_timestamp, stripped))
    return entries


def build_script_timestamp_map(
    script_lines: list[tuple[int, str]], corrected_entries: list[tuple[int, str, str]]
) -> dict[int, str]:
    timestamp_map: dict[int, str] = {}
    corrected_index = 0

    for script_line_no, script_text in script_lines:
        while corrected_index < len(corrected_entries):
            _, timestamp, corrected_text = corrected_entries[corrected_index]
            corrected_index += 1
            if corrected_text == script_text:
                timestamp_map[script_line_no] = timestamp
                break
        else:
            timestamp_map[script_line_no] = ""

    return timestamp_map


def collect_hits(
    script_path: Path,
    corrected_path: Path,
    literal_patterns: list[str],
    regex_patterns: list[re.Pattern[str]],
) -> list[CandidateHit]:
    script_lines = load_script_lines(script_path)
    corrected_entries = load_corrected_entries(corrected_path)
    timestamp_map = build_script_timestamp_map(script_lines, corrected_entries)

    hits: list[CandidateHit] = []
    file_label = script_path.as_posix()
    for line_no, line_text in script_lines:
        for pattern in literal_patterns:
            if pattern and pattern in line_text:
                hits.append(
                    CandidateHit(
                        pattern=pattern,
                        match_kind="literal",
                        file_path=file_label,
                        line_no=line_no,
                        timestamp=timestamp_map.get(line_no, ""),
                        line_text=line_text,
                    )
                )
        for regex_pattern in regex_patterns:
            if regex_pattern.search(line_text):
                hits.append(
                    CandidateHit(
                        pattern=regex_pattern.pattern,
                        match_kind="regex",
                        file_path=file_label,
                        line_no=line_no,
                        timestamp=timestamp_map.get(line_no, ""),
                        line_text=line_text,
                    )
                )

    return hits


def render_markdown(hits: list[CandidateHit], files_scanned: int) -> str:
    grouped: dict[tuple[str, str], list[CandidateHit]] = defaultdict(list)
    for hit in hits:
        grouped[(hit.match_kind, hit.pattern)].append(hit)

    ordered_groups = sorted(
        grouped.items(),
        key=lambda item: (
            -len({hit.file_path for hit in item[1]}),
            -len(item[1]),
            item[0][0],
            item[0][1],
        ),
    )

    lines = [
        "# Suspicious Transcript Candidates",
        "",
        f"- files_scanned: {files_scanned}",
        f"- unique_groups: {len(ordered_groups)}",
        f"- total_hits: {len(hits)}",
        "",
    ]

    if not ordered_groups:
        lines.append("No suspicious candidates found.")
        return "\n".join(lines) + "\n"

    for (match_kind, pattern), group_hits in ordered_groups:
        file_count = len({hit.file_path for hit in group_hits})
        lines.append(f"## {pattern}")
        lines.append("")
        lines.append(f"- kind: {match_kind}")
        lines.append(f"- hits: {len(group_hits)}")
        lines.append(f"- files: {file_count}")
        lines.append("")
        for hit in group_hits:
            timestamp = hit.timestamp or "--:--"
            lines.append(
                f"- {hit.file_path}:{hit.line_no} [{timestamp}] {hit.line_text}"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_json(hits: list[CandidateHit], files_scanned: int) -> str:
    payload = {
        "files_scanned": files_scanned,
        "total_hits": len(hits),
        "hits": [
            {
                "pattern": hit.pattern,
                "match_kind": hit.match_kind,
                "file_path": hit.file_path,
                "line_no": hit.line_no,
                "timestamp": hit.timestamp,
                "line_text": hit.line_text,
            }
            for hit in hits
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    args = parse_args()
    script_root = Path(args.script_root)
    corrected_root = Path(args.corrected_root)
    dict_root = Path(args.dict_root)
    base_literal_patterns = load_literal_patterns(dict_root, args.topic)
    file_override_patterns = load_file_override_patterns(dict_root, args.topic)
    regex_patterns = [re.compile(pattern) for pattern in args.regex]

    targets = resolve_targets(script_root, args.target)
    all_hits: list[CandidateHit] = []
    for script_path in targets:
        relative_script_path = script_path.relative_to(script_root).as_posix()
        relative_raw_path = relative_script_path.replace(".script.txt", ".txt")
        literal_patterns = unique_preserve_order(base_literal_patterns)
        literal_patterns.extend(
            wrong
            for path_pattern, wrong in file_override_patterns
            if fnmatch.fnmatch(relative_raw_path, path_pattern)
        )
        literal_patterns = unique_preserve_order(literal_patterns)
        literal_patterns.sort(key=len, reverse=True)
        corrected_path = corrected_root / script_path.relative_to(script_root)
        corrected_path = corrected_path.with_name(
            script_path.name.replace(".script.txt", ".corrected.txt")
        )
        if not corrected_path.exists():
            raise FileNotFoundError(
                f"matching corrected file not found for {script_path}: {corrected_path}"
            )
        all_hits.extend(
            collect_hits(
                script_path=script_path,
                corrected_path=corrected_path,
                literal_patterns=literal_patterns,
                regex_patterns=regex_patterns,
            )
        )

    if args.format == "json":
        output_text = render_json(all_hits, len(targets))
    else:
        output_text = render_markdown(all_hits, len(targets))

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_text, encoding="utf-8")
    else:
        print(output_text, end="")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
