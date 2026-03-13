#!/usr/bin/env python3
"""Convert inline review markers in corr/script files into file overrides."""

from __future__ import annotations

import argparse
import re
from dataclasses import replace
from pathlib import Path

from daglo_corrector import (
    FILE_OVERRIDES_FILENAME,
    FileOverrideRule,
    load_file_overrides,
    write_file_overrides,
)

MARKER_RE = re.compile(
    r"^\s*@@\s*override\s*:\s*(?P<wrong>.+?)\s*=>\s*(?P<right>.+?)\s*$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read @@ override markers from corr/script files and append or update "
            "dict/topics/<topic>/file_overrides.jsonl entries."
        )
    )
    parser.add_argument(
        "--topic",
        required=True,
        help="Topic name under dict/topics (for example: saju, network, security).",
    )
    parser.add_argument(
        "--script-file",
        action="append",
        required=True,
        help="Path to a corr/script/*.script.txt file. Repeat this option for multiple files.",
    )
    parser.add_argument(
        "--dict-root",
        default="dict",
        help="Dictionary root path (default: ./dict).",
    )
    parser.add_argument(
        "--script-root",
        default="data/daglo/corr/script",
        help="corr/script root used to infer the raw relative path.",
    )
    parser.add_argument(
        "--clean-markers",
        action="store_true",
        help="Remove consumed @@ override marker lines from the script file.",
    )
    parser.add_argument(
        "--note",
        default="Imported from script review marker",
        help="Note text written to added/updated override entries.",
    )
    return parser.parse_args()


def infer_raw_relative_path(script_file: Path, script_root: Path) -> str:
    relative = script_file.resolve().relative_to(script_root.resolve())
    if not relative.name.endswith(".script.txt"):
        raise ValueError(f"not a .script.txt file under script root: {script_file}")
    raw_name = relative.name[: -len(".script.txt")] + ".txt"
    return relative.with_name(raw_name).as_posix()


def extract_markers(script_file: Path) -> tuple[list[tuple[str, str]], list[str]]:
    pairs: list[tuple[str, str]] = []
    kept_lines: list[str] = []

    for raw_line in script_file.read_text(encoding="utf-8").splitlines():
        match = MARKER_RE.match(raw_line)
        if not match:
            kept_lines.append(raw_line)
            continue

        wrong = match.group("wrong").strip()
        right = match.group("right").strip()
        if not wrong or not right or wrong == right:
            raise ValueError(f"invalid override marker in {script_file}: {raw_line}")
        pairs.append((wrong, right))

    return pairs, kept_lines


def merge_override_entries(
    existing: list[FileOverrideRule],
    raw_relative_path: str,
    pairs: list[tuple[str, str]],
    note: str,
) -> tuple[list[FileOverrideRule], int, int]:
    merged = existing.copy()
    index_by_key = {(rule.path, rule.wrong): idx for idx, rule in enumerate(merged)}
    added = 0
    updated = 0

    for wrong, right in pairs:
        key = (raw_relative_path, wrong)
        new_rule = FileOverrideRule(
            path=raw_relative_path,
            wrong=wrong,
            right=right,
            note=note,
        )
        idx = index_by_key.get(key)
        if idx is None:
            merged.append(new_rule)
            index_by_key[key] = len(merged) - 1
            added += 1
            continue

        current = merged[idx]
        if current.right == right and current.note == note:
            continue
        merged[idx] = replace(current, right=right, note=note or current.note)
        updated += 1

    return merged, added, updated


def main() -> int:
    args = parse_args()
    dict_root = Path(args.dict_root)
    script_root = Path(args.script_root)
    overrides_path = dict_root / "topics" / args.topic / FILE_OVERRIDES_FILENAME
    overrides = load_file_overrides(overrides_path)

    total_markers = 0
    total_added = 0
    total_updated = 0

    for script_file_arg in args.script_file:
        script_file = Path(script_file_arg)
        if not script_file.exists():
            raise FileNotFoundError(f"script file not found: {script_file}")

        raw_relative_path = infer_raw_relative_path(script_file, script_root)
        pairs, kept_lines = extract_markers(script_file)
        if not pairs:
            print(f"[SKIP] no markers: {script_file}")
            continue

        overrides, added, updated = merge_override_entries(
            overrides, raw_relative_path, pairs, args.note
        )
        total_markers += len(pairs)
        total_added += added
        total_updated += updated

        if args.clean_markers:
            cleaned_text = "\n".join(kept_lines)
            if kept_lines:
                cleaned_text += "\n"
            script_file.write_text(cleaned_text, encoding="utf-8")

        print(
            f"[DONE] {script_file} -> {raw_relative_path} "
            f"(markers={len(pairs)}, added={added}, updated={updated})"
        )

    write_file_overrides(overrides_path, overrides)
    print(
        f"[DONE] overrides written: {overrides_path} "
        f"(markers={total_markers}, added={total_added}, updated={total_updated})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
