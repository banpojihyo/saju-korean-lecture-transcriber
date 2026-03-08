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
        description=(
            "Correct one Daglo transcript and save into "
            "data/daglo/corr/{corrected,script,changes}."
        )
    )
    parser.add_argument(
        "--source-file",
        required=True,
        help="Path to a Daglo txt file (for example: data/daglo/raw/.../foo.txt).",
    )
    parser.add_argument(
        "--dict-dir",
        default="dict",
        help="Directory containing replace.csv and terms.csv (default: ./dict).",
    )
    parser.add_argument(
        "--input-root",
        default="data/daglo/raw",
        help=(
            "Input root used to preserve relative folder structure "
            "(default: ./data/daglo/raw)."
        ),
    )
    parser.add_argument(
        "--output-root",
        default="data/daglo/corr",
        help=(
            "Output root. Files are written under "
            "{output_root}/corrected, {output_root}/script, {output_root}/changes."
        ),
    )
    parser.add_argument(
        "--no-update-dict",
        action="store_true",
        help="Do not update dict/replace.csv and dict/terms.csv from applied corrections.",
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


def load_terms(path: Path) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    if not path.exists():
        return terms
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            term = (row.get("term") or "").strip()
            if not term or term in seen:
                continue
            seen.add(term)
            terms.append(term)
    return terms


def write_replace_pairs(path: Path, pairs: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["wrong", "right"])
        for wrong, right in pairs:
            writer.writerow([wrong, right])


def write_terms(path: Path, terms: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["term"])
        for term in terms:
            writer.writerow([term])


def merge_replace_pairs(
    existing: list[tuple[str, str]], applied: list[tuple[str, str, int]]
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    merged = existing.copy()
    seen = set(existing)
    added: list[tuple[str, str]] = []
    for wrong, right, _ in applied:
        pair = (wrong, right)
        if pair in seen:
            continue
        seen.add(pair)
        merged.append(pair)
        added.append(pair)
    return merged, added


KOREAN_RE = re.compile(r"[가-힣]")
TRAILING_SUFFIXES = (
    "으로는",
    "로는",
    "이라면",
    "라면",
    "다면은",
    "다면",
    "에는",
    "에서",
    "으로",
    "하다",
    "했다",
    "하는",
    "하게",
    "하며",
    "하면",
    "하죠",
    "해요",
    "입니다",
    "이다",
    "라고",
    "하고",
    "이며",
    "에게",
    "부터",
    "까지",
    "처럼",
    "다",
    "께서",
    "께",
    "의",
    "를",
    "을",
    "은",
    "는",
    "이",
    "가",
    "에",
    "도",
    "만",
    "와",
    "과",
)

REJECT_ENDINGS = (
    "다면",
    "한다",
    "했다",
    "해요",
    "하고",
    "가면",
    "해질",
    "하는",
    "한",
)


def normalize_term_candidate(text: str) -> str:
    candidate = text.strip()
    if " " in candidate:
        return ""
    if not KOREAN_RE.search(candidate):
        return ""
    if candidate.isdigit():
        return ""

    # Peel one grammatical tail when present.
    for suffix in TRAILING_SUFFIXES:
        if candidate.endswith(suffix) and len(candidate) - len(suffix) >= 2:
            candidate = candidate[: -len(suffix)]
            break

    for ending in REJECT_ENDINGS:
        if candidate.endswith(ending):
            return ""

    if len(candidate) < 2 or len(candidate) > 20:
        return ""
    if not KOREAN_RE.search(candidate):
        return ""
    return candidate


def is_term_candidate(text: str) -> bool:
    return bool(normalize_term_candidate(text))


def merge_terms_from_applied(
    existing_terms: list[str], applied: list[tuple[str, str, int]]
) -> tuple[list[str], list[str]]:
    merged = existing_terms.copy()
    seen = set(existing_terms)
    added: list[str] = []
    for _, right, _ in applied:
        normalized = normalize_term_candidate(right)
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        merged.append(normalized)
        added.append(normalized)
    return merged, added


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
        # Context-bound fixes: only convert '과목' where it clearly means '갑목'.
        ("이 과목이 자수를 끌어내서 쓰는데", "이 갑목이 자수를 끌어내서 쓰는데"),
        ("이 과목이 이미 사목적 성향의 상징성을 띕니다.", "이 갑목이 이미 사목적 성향의 상징성을 띕니다."),
        ("과목 하나 따로 건드려야 돼.", "갑목 하나 따로 건드려야 돼."),
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

    output_path = (
        output_root / "corrected" / relative.parent / f"{source.stem}.corrected{source.suffix}"
    )
    script_path = (
        output_root / "script" / relative.parent / f"{source.stem}.script{source.suffix}"
    )
    report_path = output_root / "changes" / relative.parent / f"{source.stem}.changes.txt"

    text = source.read_text(encoding="utf-8")
    original_text = text

    replace_path = dict_dir / "replace.csv"
    terms_path = dict_dir / "terms.csv"

    replace_pairs = load_replace_pairs(replace_path)
    domain_terms = load_terms(terms_path)
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

    added_replace_pairs: list[tuple[str, str]] = []
    added_terms: list[str] = []
    if not args.no_update_dict:
        merged_replace_pairs, added_replace_pairs = merge_replace_pairs(
            replace_pairs, applied
        )
        merged_terms, added_terms = merge_terms_from_applied(domain_terms, applied)
        if added_replace_pairs:
            write_replace_pairs(replace_path, merged_replace_pairs)
        if added_terms:
            write_terms(terms_path, merged_terms)
        domain_terms_for_count = merged_terms
    else:
        domain_terms_for_count = domain_terms

    corrected_term_hits = sum(1 for term in domain_terms_for_count if term in text)
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
    lines.append(f"dict_replace_added: {len(added_replace_pairs)}")
    lines.append(f"dict_terms_added: {len(added_terms)}")
    lines.append("")
    lines.append("[applied replacements]")
    for wrong, right, count in applied:
        lines.append(f"{wrong} -> {right} (x{count})")
    if added_replace_pairs:
        lines.append("")
        lines.append("[dict replace added]")
        for wrong, right in added_replace_pairs:
            lines.append(f"{wrong} -> {right}")
    if added_terms:
        lines.append("")
        lines.append("[dict terms added]")
        for term in added_terms:
            lines.append(term)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"[DONE] source: {source}")
    print(f"[DONE] corrected: {output_path}")
    print(f"[DONE] script-only: {script_path}")
    print(f"[DONE] report: {report_path}")
    print(f"[DONE] applied rules: {len(applied)}")
    print(f"[DONE] dict replace added: {len(added_replace_pairs)}")
    print(f"[DONE] dict terms added: {len(added_terms)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
