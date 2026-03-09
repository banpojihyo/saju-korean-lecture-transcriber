#!/usr/bin/env python3
"""Auto-correct transcript outputs and maintain dict CSV files."""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher, get_close_matches
from pathlib import Path
from typing import Iterable


TOKEN_PATTERN = re.compile(r"[가-힣A-Za-z0-9]+")
SRT_TIMECODE_PATTERN = re.compile(
    r"^\d{2}:\d{2}:\d{2},\d{3}\s+-->\s+\d{2}:\d{2}:\d{2},\d{3}$"
)
DIGIT_BLOCK_PATTERN = re.compile(r"\d+")
HAS_KOREAN_PATTERN = re.compile(r"[가-힣]")

# Korean postpositions / endings to peel off while matching term stems.
PARTICLE_SUFFIXES = (
    "으로",
    "에게",
    "에서",
    "부터",
    "까지",
    "처럼",
    "하고",
    "이라",
    "라고",
    "라는",
    "이면",
    "이나",
    "이며",
    "이예요",
    "이에요",
    "입니다",
    "예요",
    "죠",
    "요",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "와",
    "과",
    "도",
    "만",
    "에",
    "로",
    "별",
)

NON_TERM_ENDINGS = (
    "합니다",
    "했다",
    "하는",
    "하면",
    "하고",
    "해서",
    "하죠",
    "하잖아요",
    "거든요",
    "테니까요",
    "아니고",
    "라고",
    "니까",
    "네요",
    "요",
    "다",
)

STOPWORDS = {
    "오늘",
    "부터",
    "어떻게",
    "고민",
    "많이",
    "어쨌든",
    "최대한",
    "뭐라",
    "그럴까",
    "이렇게",
    "기존",
    "생각",
    "시도",
    "왜",
    "그래서",
    "이것",
    "이게",
    "자기",
    "스스로",
    "얘기",
    "정답",
    "지나치게들",
    "대한",
    "작업",
    "작업들",
    "맞다",
    "틀리다",
    "접근",
    "중요",
    "먼저",
    "염두",
    "보시기",
    "바랍니다",
    "그냥",
    "우리",
    "주변",
    "모든",
    "부분",
    "부분들",
}

SINO_DIGITS = {
    0: "영",
    1: "일",
    2: "이",
    3: "삼",
    4: "사",
    5: "오",
    6: "육",
    7: "칠",
    8: "팔",
    9: "구",
}

PARTICLE_SUFFIXES_EXTRA = (
    "\uAED8\uC11C",  # 께서
    "\uAED8",  # 께
    "\uC758",  # 의
)

EXTRA_NON_TERM_ENDINGS = (
    "\uD558\uC796\uC544",  # 하잖아
    "\uD558\uC796\uC544\uC694",  # 하잖아요
    "\uD558\uACE0",  # 하고
    "\uD558\uACE0\uC694",  # 하고요
    "\uC774\uACE0",  # 이고
    "\uC778\uAC00",  # 인가
    "\uC774\uB77C\uACE0",  # 이라고
    "\uB77C\uACE0",  # 라고
    "\uAC70\uC608\uC694",  # 거예요
    "\uD560\uAC70\uC608\uC694",  # 할거예요
)


@dataclass
class ReplacementSuggestion:
    wrong: str
    right: str
    count: int
    reason: str
    score: float


@dataclass
class TranscriptFile:
    path: Path
    is_srt: bool
    original_lines: list[str]
    lines: list[str]

    def iter_text_line_indexes(self) -> Iterable[int]:
        for idx, line in enumerate(self.lines):
            if self.is_srt and not is_srt_text_line(line):
                continue
            yield idx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Auto-correct output transcripts using <dict-dir>/replace.csv and "
            "auto-grow <dict-dir>/replace.csv + <dict-dir>/terms.csv from output text."
        )
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory containing transcript outputs (default: ./output)",
    )
    parser.add_argument(
        "--dict-dir",
        default="dict/common",
        help="Directory containing replace.csv and terms.csv (default: ./dict/common)",
    )
    parser.add_argument(
        "--replace-file",
        default="replace.csv",
        help="Replacement CSV filename inside --dict-dir (default: replace.csv)",
    )
    parser.add_argument(
        "--terms-file",
        default="terms.csv",
        help="Terms CSV filename inside --dict-dir (default: terms.csv)",
    )
    parser.add_argument(
        "--no-srt",
        action="store_true",
        help="Do not update .srt files; process only .txt files.",
    )
    parser.add_argument(
        "--min-term-freq",
        type=int,
        default=2,
        help="Minimum frequency for auto-adding new term entries (default: 2)",
    )
    parser.add_argument(
        "--min-wrong-freq",
        type=int,
        default=1,
        help="Minimum frequency for auto-adding new replace entries (default: 1)",
    )
    parser.add_argument(
        "--similarity-cutoff",
        type=float,
        default=0.78,
        help="Similarity threshold for wrong->right suggestion (default: 0.78)",
    )
    parser.add_argument(
        "--max-new-terms",
        type=int,
        default=30,
        help="Maximum number of terms to auto-add in one run (default: 30)",
    )
    parser.add_argument(
        "--max-new-replaces",
        type=int,
        default=30,
        help="Maximum number of replace pairs to auto-add in one run (default: 30)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing files.",
    )
    return parser.parse_args()


def clean_cell(value: str | None) -> str:
    if value is None:
        return ""
    cleaned = value.strip().strip("\ufeff").strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        cleaned = cleaned[1:-1]
    return cleaned.strip()


def get_column(row: dict[str, str], expected: str) -> str:
    for key, value in row.items():
        normalized_key = clean_cell(key).lower()
        if normalized_key == expected:
            return clean_cell(value)
    return ""


def dedupe_pairs(pairs: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str]] = []
    for wrong, right in pairs:
        if not wrong or not right or wrong == right:
            continue
        key = (wrong, right)
        if key in seen:
            continue
        seen.add(key)
        result.append((wrong, right))
    return result


def dedupe_terms(terms: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        cleaned = clean_cell(term)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def load_replacements(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows: list[tuple[str, str]] = []
        for row in reader:
            wrong = get_column(row, "wrong")
            right = get_column(row, "right")
            if wrong and right:
                rows.append((wrong, right))
    return dedupe_pairs(rows)


def load_terms(path: Path) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows: list[str] = []
        for row in reader:
            term = get_column(row, "term")
            if term:
                rows.append(term)
    return dedupe_terms(rows)


def write_replacements(path: Path, replacements: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["wrong", "right"])
        for wrong, right in replacements:
            writer.writerow([wrong, right])


def write_terms(path: Path, terms: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["term"])
        for term in terms:
            writer.writerow([term])


def list_transcript_files(output_dir: Path, include_srt: bool) -> list[Path]:
    if not output_dir.exists():
        return []
    suffixes = {".txt"}
    if include_srt:
        suffixes.add(".srt")
    files = [
        path
        for path in output_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in suffixes
    ]
    return sorted(files, key=lambda p: str(p).lower())


def read_text_with_fallback(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def load_transcript_files(paths: list[Path]) -> list[TranscriptFile]:
    docs: list[TranscriptFile] = []
    for path in paths:
        content = read_text_with_fallback(path)
        lines = content.splitlines(keepends=True)
        if not lines:
            lines = [""]
        docs.append(
            TranscriptFile(
                path=path,
                is_srt=path.suffix.lower() == ".srt",
                original_lines=lines.copy(),
                lines=lines.copy(),
            )
        )
    return docs


def is_srt_text_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.isdigit():
        return False
    if SRT_TIMECODE_PATTERN.fullmatch(stripped):
        return False
    return True


def apply_replacements(
    docs: list[TranscriptFile], replacements: list[tuple[str, str]]
) -> Counter[tuple[str, str]]:
    ordered = sorted(replacements, key=lambda pair: len(pair[0]), reverse=True)
    usage: Counter[tuple[str, str]] = Counter()
    if not ordered:
        return usage
    for doc in docs:
        for line_idx in doc.iter_text_line_indexes():
            line = doc.lines[line_idx]
            updated = line
            for wrong, right in ordered:
                if wrong and wrong in updated:
                    count = updated.count(wrong)
                    updated = updated.replace(wrong, right)
                    usage[(wrong, right)] += count
            if updated != line:
                doc.lines[line_idx] = updated
    return usage


def has_korean(text: str) -> bool:
    return bool(HAS_KOREAN_PATTERN.search(text))


def tokenize(text: str) -> list[str]:
    return [token for token in TOKEN_PATTERN.findall(text) if token]


def token_frequency(docs: list[TranscriptFile]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for doc in docs:
        for line_idx in doc.iter_text_line_indexes():
            for token in tokenize(doc.lines[line_idx]):
                counts[token] += 1
    return counts


def stem_frequency(docs: list[TranscriptFile]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for doc in docs:
        for line_idx in doc.iter_text_line_indexes():
            for token in tokenize(doc.lines[line_idx]):
                stem, _ = split_suffix(token)
                if len(stem) < 2:
                    continue
                candidate = stem
                counts[candidate] += 1
    return counts


def split_suffix(token: str) -> tuple[str, str]:
    suffixes = sorted(
        set(PARTICLE_SUFFIXES).union(PARTICLE_SUFFIXES_EXTRA),
        key=len,
        reverse=True,
    )
    for suffix in suffixes:
        if token.endswith(suffix) and len(token) - len(suffix) >= 2:
            return token[: -len(suffix)], suffix
    return token, ""


def number_to_korean(num: int) -> str:
    if num == 0:
        return SINO_DIGITS[0]
    if num < 0:
        return str(num)
    units = ((1000, "천"), (100, "백"), (10, "십"), (1, ""))
    result = ""
    remaining = num
    for value, unit in units:
        digit, remaining = divmod(remaining, value)
        if digit == 0:
            continue
        if digit == 1 and unit:
            result += unit
        else:
            result += SINO_DIGITS[digit] + unit
    return result


def normalize_digits_to_korean(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        try:
            return number_to_korean(int(match.group(0)))
        except ValueError:
            return match.group(0)

    return DIGIT_BLOCK_PATTERN.sub(repl, text)


def one_char_diff_match(stem: str, terms: list[str]) -> str:
    best = ""
    for term in terms:
        if len(term) != len(stem):
            continue
        diff_count = sum(1 for a, b in zip(stem, term) if a != b)
        if diff_count != 1:
            continue
        if stem[0] == term[0]:
            return term
        if not best:
            best = term
    return best


def suggest_new_replacements(
    token_counts: Counter[str],
    known_terms: list[str],
    existing_replacements: list[tuple[str, str]],
    min_freq: int,
    similarity_cutoff: float,
    max_new_replaces: int,
) -> list[ReplacementSuggestion]:
    known_term_set = set(known_terms)
    known_term_no_space = [term for term in known_terms if " " not in term]
    existing_wrong_set = {wrong for wrong, _ in existing_replacements}
    suggestions: dict[str, ReplacementSuggestion] = {}
    strict_cutoff = max(similarity_cutoff, 0.85)
    byul_suffix = "\uBCC4"  # 별

    for token, count in token_counts.most_common():
        if count < min_freq:
            break
        if token in existing_wrong_set or token in known_term_set:
            continue
        if token in STOPWORDS:
            continue
        if len(token) < 2 or len(token) > 15:
            continue
        if not (has_korean(token) or any(ch.isdigit() for ch in token)):
            continue

        stem, suffix = split_suffix(token)
        if len(stem) < 2:
            continue
        if stem in known_term_set:
            # Correct term + particle form, not a typo.
            continue
        if not (has_korean(stem) or any(ch.isdigit() for ch in stem)):
            continue
        if any(token.endswith(ending) for ending in NON_TERM_ENDINGS):
            continue

        right = ""
        reason = ""
        score = 0.0

        normalized_stem = normalize_digits_to_korean(stem)
        if normalized_stem in known_term_set and normalized_stem != stem:
            right = normalized_stem + suffix
            reason = "digit->korean"
            score = 1.0
        elif len(stem) >= 3:
            matches = get_close_matches(
                stem, known_term_no_space, n=1, cutoff=strict_cutoff
            )
            if matches:
                match = matches[0]
                ratio = SequenceMatcher(None, stem, match).ratio()
                if abs(len(stem) - len(match)) <= 1 and ratio >= strict_cutoff:
                    right = match + suffix
                    reason = f"similarity:{ratio:.2f}"
                    score = ratio

        if not right and suffix == byul_suffix and len(stem) >= 2:
            near = one_char_diff_match(stem, known_term_no_space)
            if near:
                right = near + suffix
                reason = "single-char-diff+별"
                score = 0.70

        if not right or right == token:
            continue

        current = suggestions.get(token)
        if current is None or score > current.score:
            suggestions[token] = ReplacementSuggestion(
                wrong=token,
                right=right,
                count=count,
                reason=reason,
                score=score,
            )

    ranked = sorted(
        suggestions.values(),
        key=lambda item: (-item.count, -item.score, item.wrong),
    )
    return ranked[:max_new_replaces]


def suggest_new_terms(
    stem_counts: Counter[str],
    known_terms: list[str],
    min_freq: int,
    max_new_terms: int,
) -> list[str]:
    known_set = set(known_terms)
    anchors = [term for term in known_terms if len(term) >= 2 and " " not in term]
    suggestions: list[str] = []
    for token, count in stem_counts.most_common():
        if count < min_freq:
            break
        if token in known_set:
            continue
        if len(token) < 2 or len(token) > 12:
            continue
        if token in STOPWORDS:
            continue
        if not has_korean(token):
            continue
        if any(token.endswith(ending) for ending in NON_TERM_ENDINGS):
            continue
        if any(token.endswith(ending) for ending in EXTRA_NON_TERM_ENDINGS):
            continue
        if token.endswith(("\uC544", "\uC5B4", "\uACE0", "\uC694", "\uC8E0", "\uAE4C", "\uB124")):
            continue
        related = False
        for term in anchors:
            if (
                token.startswith(term)
                or token.endswith(term)
                or term.startswith(token)
                or term.endswith(token)
            ):
                related = True
                break
        if not related:
            continue
        if token not in suggestions:
            suggestions.append(token)
        if len(suggestions) >= max_new_terms:
            break
    return suggestions


def count_changed_docs(docs: list[TranscriptFile]) -> int:
    return sum(1 for doc in docs if doc.lines != doc.original_lines)


def write_docs(docs: list[TranscriptFile]) -> int:
    changed = 0
    for doc in docs:
        if doc.lines == doc.original_lines:
            continue
        doc.path.write_text("".join(doc.lines), encoding="utf-8-sig")
        changed += 1
    return changed


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    dict_dir = Path(args.dict_dir)
    replace_path = dict_dir / args.replace_file
    terms_path = dict_dir / args.terms_file

    replacements = load_replacements(replace_path)
    terms = load_terms(terms_path)

    targets = list_transcript_files(output_dir, include_srt=not args.no_srt)
    if not targets:
        print(f"[ERROR] No transcript files found in: {output_dir}")
        return 1

    docs = load_transcript_files(targets)
    print(f"[INFO] Loaded {len(docs)} transcript file(s).")
    print(f"[INFO] Loaded {len(replacements)} replace pair(s), {len(terms)} term(s).")

    usage_existing = apply_replacements(docs, replacements)
    existing_replacement_hits = sum(usage_existing.values())
    print(f"[INFO] Applied existing replace rules: {existing_replacement_hits} hit(s).")

    term_seed = dedupe_terms(terms + [right for _, right in replacements if " " not in right])
    token_counts_before_new = token_frequency(docs)
    replacement_suggestions = suggest_new_replacements(
        token_counts=token_counts_before_new,
        known_terms=term_seed,
        existing_replacements=replacements,
        min_freq=max(args.min_wrong_freq, 1),
        similarity_cutoff=args.similarity_cutoff,
        max_new_replaces=max(args.max_new_replaces, 0),
    )
    new_replacements = [(item.wrong, item.right) for item in replacement_suggestions]
    usage_suggested = apply_replacements(docs, new_replacements)
    suggested_replacement_hits = sum(usage_suggested.values())

    merged_replacements = dedupe_pairs(replacements + new_replacements)

    stem_counts_final = stem_frequency(docs)
    terms_seed_final = dedupe_terms(
        terms + [right for _, right in merged_replacements if " " not in right]
    )
    new_terms = suggest_new_terms(
        stem_counts=stem_counts_final,
        known_terms=terms_seed_final,
        min_freq=max(args.min_term_freq, 1),
        max_new_terms=max(args.max_new_terms, 0),
    )
    merged_terms = dedupe_terms(terms_seed_final + new_terms)

    changed_docs = count_changed_docs(docs)
    added_replace_count = len(merged_replacements) - len(replacements)
    added_term_count = len(merged_terms) - len(terms)

    print(
        "[INFO] Auto-suggested replace pairs: "
        f"{added_replace_count} (applied {suggested_replacement_hits} hit(s))."
    )
    if replacement_suggestions:
        for item in replacement_suggestions[:10]:
            print(
                f"[SUGGEST] replace: '{item.wrong}' -> '{item.right}' "
                f"(freq={item.count}, reason={item.reason})"
            )

    print(f"[INFO] Auto-suggested new terms: {len(new_terms)}")
    if new_terms:
        for term in new_terms[:10]:
            print(f"[SUGGEST] term: '{term}'")

    if args.dry_run:
        print(
            "[DRY-RUN] "
            f"{changed_docs} transcript file(s) would be updated, "
            f"{added_replace_count} replace pair(s) and "
            f"{added_term_count} term(s) would be added."
        )
        return 0

    written_docs = write_docs(docs)
    write_replacements(replace_path, merged_replacements)
    write_terms(terms_path, merged_terms)

    print(
        "[DONE] Updated "
        f"{written_docs} transcript file(s), "
        f"replace.csv +{added_replace_count}, terms.csv +{added_term_count}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
