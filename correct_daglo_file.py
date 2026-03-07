#!/usr/bin/env python3
"""Create a corrected Daglo transcript copy in a separate folder.

This applies:
1) dict/replace.csv base replacements
2) high-confidence manual replacements for common ASR mistakes
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Correct one Daglo transcript and save to data/corrected/daglo."
    )
    parser.add_argument(
        "--source-file",
        required=True,
        help="Path to a Daglo txt file (for example: daglo/.../foo.txt).",
    )
    parser.add_argument(
        "--dict-dir",
        default="dict",
        help="Directory containing replace.csv and terms.csv (default: ./dict).",
    )
    parser.add_argument(
        "--input-root",
        default="daglo",
        help="Input root used to preserve relative folder structure (default: ./daglo).",
    )
    parser.add_argument(
        "--output-root",
        default="data/corrected/daglo",
        help="Output root for corrected files (default: ./data/corrected/daglo).",
    )
    return parser.parse_args()


def load_replace_pairs(path: Path) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    if not path.exists():
        return pairs
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            wrong = (row.get("wrong") or "").strip()
            right = (row.get("right") or "").strip()
            if wrong and right and wrong != right:
                pairs.append((wrong, right))
    return pairs


def load_terms(path: Path) -> set[str]:
    terms: set[str] = set()
    if not path.exists():
        return terms
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            term = (row.get("term") or "").strip()
            if term:
                terms.add(term)
    return terms


def manual_pairs() -> list[tuple[str, str]]:
    # High-confidence fixes verified against terms usage in this domain.
    return [
        ("이제마 4조", "이제마 사주"),
        ("4조", "사주"),
        ("1주", "일주"),
        ("1조", "일주"),
        ("이정화 선생님", "이제마 선생님"),
        ("이정화 선생", "이제마 선생"),
        ("이자야마 선생", "이제마 선생"),
        ("이자마 선생", "이제마 선생"),
        ("이재명 선생님", "이제마 선생"),
        ("태는 금", "폐는 금"),
        ("푸는 비비", "토는 비위"),
        ("목국도", "목극토"),
        ("복국토다", "목극토다"),
        ("4.3 의학", "사상의학"),
        ("채용", "체용"),
        ("동의 수세보원", "동의수세보원"),
        ("동인수세보원", "동의수세보원"),
        ("그 복을 폐로", "그 목을 폐로"),
        ("관사를", "관살을"),
        ("사조를", "사주를"),
        ("사두에", "사주에"),
        ("귀신", "기신"),
        ("심금 편제", "신금 편재"),
        ("북을 이루어서", "국을 이루어서"),
        ("부관한다면은", "투간한다면은"),
        ("이사경은", "이 사주는"),
        ("수색묵", "수생목"),
        ("수온이라는", "수 운이라는"),
        ("공부한테", "공부할 때"),
        ("무반", "무관"),
        ("신자진 국을 지르고요", "신자진 국을 이루고요"),
        ("금극무", "금극목"),
        ("통정대구", "통정대부"),
        ("통운대구", "통훈대부"),
        ("당삼각", "당상관"),
        ("붕괴가", "품계가"),
        ("감묵", "갑목"),
        ("감복", "갑목"),
        ("왕세강약", "왕쇠강약"),
        ("새해질", "쇠해질"),
        ("붉어나가면", "불어나가면"),
        ("걸록", "건록"),
        ("쟁제쟁관", "쟁재쟁관"),
        ("술을 봐야", "수를 봐야"),
        ("10점을", "십성을"),
        ("1가능에는", "일간으로는"),
        ("공관은", "상관은"),
        ("단락해도", "달라고 해도"),
        ("활을 봐야", "화를 봐야"),
    ]


TIMESTAMP_SPEAKER_RE = re.compile(
    r"^\s*\d{1,2}:\d{2}(?::\d{2})?\s+화자\s*\d+\s*$"
)


def build_script_only_text(text: str) -> str:
    lines = text.splitlines()
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if TIMESTAMP_SPEAKER_RE.match(stripped):
            continue
        if not stripped:
            if kept and kept[-1] != "":
                kept.append("")
            continue
        kept.append(stripped)

    while kept and kept[0] == "":
        kept.pop(0)
    while kept and kept[-1] == "":
        kept.pop()

    return "\n".join(kept) + ("\n" if kept else "")


def main() -> int:
    args = parse_args()
    source = Path(args.source_file)
    if not source.exists():
        print(f"[ERROR] source file not found: {source}")
        return 1

    input_root = Path(args.input_root)
    output_root = Path(args.output_root)
    dict_dir = Path(args.dict_dir)

    source_abs = source.resolve()
    input_root_abs = input_root.resolve()

    try:
        relative = source_abs.relative_to(input_root_abs)
    except ValueError:
        # Fallback: preserve source filename under output root.
        relative = Path(source.name)

    output_path = output_root / relative.parent / f"{source.stem}.corrected{source.suffix}"
    script_path = output_root / relative.parent / f"{source.stem}.script{source.suffix}"
    report_path = output_root / relative.parent / f"{source.stem}.changes.txt"

    text = source.read_text(encoding="utf-8")
    original_text = text

    replace_pairs = load_replace_pairs(dict_dir / "replace.csv")
    domain_terms = load_terms(dict_dir / "terms.csv")
    all_pairs = replace_pairs + manual_pairs()

    # Longer source phrase first to avoid partial overlap issues.
    all_pairs.sort(key=lambda p: len(p[0]), reverse=True)

    applied: list[tuple[str, str, int]] = []
    for wrong, right in all_pairs:
        if wrong not in text:
            continue
        count = text.count(wrong)
        text = text.replace(wrong, right)
        applied.append((wrong, right, count))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    script_only_text = build_script_only_text(text)
    script_path.write_text(script_only_text, encoding="utf-8")

    corrected_term_hits = sum(1 for term in domain_terms if term in text)
    script_lines = sum(1 for line in script_only_text.splitlines() if line.strip())
    changed_chars = sum(1 for a, b in zip(original_text, text) if a != b) + abs(
        len(original_text) - len(text)
    )

    lines: list[str] = []
    lines.append(f"source: {source}")
    lines.append(f"output: {output_path}")
    lines.append(f"script_only_output: {script_path}")
    lines.append(f"applied_rules: {len(applied)}")
    lines.append(f"changed_chars: {changed_chars}")
    lines.append(f"term_hits_after_correction: {corrected_term_hits}")
    lines.append(f"script_lines_after_cleanup: {script_lines}")
    lines.append("")
    lines.append("[applied replacements]")
    for wrong, right, count in applied:
        lines.append(f"{wrong} -> {right} (x{count})")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"[DONE] source: {source}")
    print(f"[DONE] corrected: {output_path}")
    print(f"[DONE] script-only: {script_path}")
    print(f"[DONE] report: {report_path}")
    print(f"[DONE] applied rules: {len(applied)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
