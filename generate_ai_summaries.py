#!/usr/bin/env python3
"""Generate AI-style study summaries from Daglo corrected script files.

Input:
  data/daglo/corr/script/**/*.txt

Output:
  data/summaries/<agent_name>/md/**/*.md
  data/summaries/<agent_name>/txt/**/*.txt
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from pathlib import Path


KOR_WORD_RE = re.compile(r"[가-힣]{2,}")
ENG_WORD_RE = re.compile(r"[A-Za-z]{2,}")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+")

STOPWORDS = {
    # discourse fillers
    "이렇게",
    "그렇죠",
    "그러니까",
    "거예요",
    "거에요",
    "이게",
    "그게",
    "있는",
    "있어요",
    "있고",
    "있습니다",
    "하는데",
    "하면은",
    "그",
    "이",
    "저",
    "요",
    # generic
    "그리고",
    "그런데",
    "그래서",
    "하지만",
    "때문",
    "부분",
    "정도",
    "이런",
    "저런",
    "그냥",
    "지금",
    "경우",
    "대한",
    "이야기",
    "내용",
    "있다",
    "없다",
    "한다",
    "된다",
    "합니다",
    "하는",
    "에서",
    "으로",
    "까지",
    "에게",
    "하기",
    "하면",
    "합니다",
    "때",
    "것",
    "수",
    "좀",
    "더",
    "등",
    "관련",
    "통해",
    "기준",
    "상태",
    "부분들",
    "부분이",
    "것들",
    "하죠",
    "하는거",
    "같은",
    "이런식",
    "여기",
    "저기",
    "이번",
    "저번",
    "이제",
    "먼저",
    "다시",
    "사실",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate structured AI summary files from corr/script."
    )
    parser.add_argument(
        "--input-root",
        default="data/daglo/corr/script",
        help="Input root containing script txt files.",
    )
    parser.add_argument(
        "--output-root",
        default="data/summaries",
        help="Output root directory for AI results.",
    )
    parser.add_argument(
        "--agent-name",
        default="GPT-5.3-Codex",
        help="AI agent folder name under output root.",
    )
    parser.add_argument(
        "--max-theme-bullets",
        type=int,
        default=4,
        help="Max bullet count per theme.",
    )
    parser.add_argument(
        "--terms-path",
        default="dict/common/terms.csv",
        help="Domain term dictionary path used to prioritize keywords.",
    )
    return parser.parse_args()


def split_sentences(text: str) -> list[str]:
    # First split by line breaks, then sentence punctuation.
    chunks = [part.strip() for part in text.splitlines() if part.strip()]
    sents: list[str] = []
    for chunk in chunks:
        for sent in SENTENCE_SPLIT_RE.split(chunk):
            sent = sent.strip()
            if sent:
                sents.append(sent)
    return sents


def load_domain_terms(path: Path) -> set[str]:
    if not path.exists():
        return set()
    terms: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            term = (row.get("term") or "").strip()
            if len(term) >= 2:
                terms.add(term)
    return terms


def extract_keywords(text: str, domain_terms: set[str], limit: int = 16) -> list[str]:
    # 1) Prefer domain dictionary terms first.
    domain_counter: Counter[str] = Counter()
    for term in domain_terms:
        cnt = text.count(term)
        if cnt > 0:
            domain_counter[term] = cnt

    ordered: list[str] = [term for term, _ in domain_counter.most_common(limit)]
    if len(ordered) >= limit:
        return ordered[:limit]

    # 2) Fill remaining slots with frequent non-stopword tokens.
    words: list[str] = []
    words.extend(KOR_WORD_RE.findall(text))
    words.extend(ENG_WORD_RE.findall(text.lower()))
    filtered = [w for w in words if w not in STOPWORDS and len(w) >= 2]
    counter = Counter(filtered)
    for term, _ in domain_counter.items():
        if term in counter:
            del counter[term]
    for word, _ in counter.most_common(limit):
        if word not in ordered:
            ordered.append(word)
        if len(ordered) >= limit:
            break
    return ordered[:limit]


def score_sentences(sentences: list[str], keywords: list[str]) -> list[tuple[int, str]]:
    if not sentences:
        return []
    keyset = set(keywords)
    scored: list[tuple[int, str]] = []
    for sent in sentences:
        words = KOR_WORD_RE.findall(sent) + ENG_WORD_RE.findall(sent.lower())
        score = sum(1 for w in words if w in keyset)
        # Prefer informative medium-length sentences.
        if 20 <= len(sent) <= 220:
            score += 1
        scored.append((score, sent))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def title_tokens(path: Path) -> list[str]:
    stem = path.stem
    raw = re.split(r"[\s\-_–—·()（）\[\],.]+", stem)
    ban = {"script", "요약", "txt", "md"}
    tokens = [
        tok
        for tok in raw
        if len(tok) >= 2 and not tok.isdigit() and tok.lower() not in ban
    ]
    return tokens


def pick_theme_sentences(
    sentences: list[str],
    theme_keywords: list[str],
    limit: int,
) -> list[str]:
    if not sentences:
        return []
    picked: list[str] = []
    seen: set[str] = set()
    for sent in sentences:
        if sent in seen:
            continue
        if any(k in sent for k in theme_keywords):
            picked.append(sent)
            seen.add(sent)
            if len(picked) >= limit:
                break
    if picked:
        return picked

    # Fallback: first informative sentences.
    for sent in sentences:
        if sent in seen:
            continue
        if len(sent) >= 20:
            picked.append(sent)
            seen.add(sent)
            if len(picked) >= limit:
                break
    return picked


def safe_concept_list(
    path: Path, keywords: list[str], domain_terms: set[str], size: int = 5
) -> list[str]:
    candidates = []
    candidates.extend(title_tokens(path))
    candidates.extend([k for k in keywords if k in domain_terms])
    candidates.extend(keywords)
    seen: set[str] = set()
    uniq: list[str] = []
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        uniq.append(c)
        if len(uniq) >= size:
            break
    while len(uniq) < size:
        uniq.append(f"핵심개념{len(uniq) + 1}")
    return uniq


def make_summary_text(
    source_path: Path,
    text: str,
    max_theme_bullets: int,
    domain_terms: set[str],
) -> str:
    sentences = split_sentences(text)
    keywords = extract_keywords(text, domain_terms, limit=16)
    scored = score_sentences(sentences, keywords)
    ranked_sentences = [s for _, s in scored]

    # Build three topic groups from keyword windows.
    groups = [
        keywords[0:4],
        keywords[4:8],
        keywords[8:12],
    ]
    groups = [g for g in groups if g]
    if not groups:
        groups = [["핵심", "개념"], ["구조", "관계"], ["응용", "실전"]]

    lines: list[str] = []
    lines.append(f"# {source_path.stem} 요약")
    lines.append("")
    lines.append("## 🔖 핵심 주제별로 나눠서 정리해줘")
    lines.append("")

    for idx, kws in enumerate(groups, start=1):
        label = ", ".join(kws[:2]) if kws else f"주제 {idx}"
        lines.append(f"### 주제 {idx}. {label}")
        bullets = pick_theme_sentences(ranked_sentences, kws, max_theme_bullets)
        if not bullets:
            bullets = ["핵심 개념 중심으로 내용이 전개됩니다."]
        for bullet in bullets:
            lines.append(f"- {bullet}")
        lines.append("")

    concepts = safe_concept_list(source_path, keywords, domain_terms, size=5)
    lines.append("## 📑 시험문제를 만들어줘")
    lines.append("")
    for idx, concept in enumerate(concepts, start=1):
        qtype = "객관식" if idx % 2 == 1 else "단답형"
        related = concepts[(idx % len(concepts))]
        lines.append(f"{idx}. 개념: {concept}")
        lines.append(f"- 예상 문제({qtype}): `{concept}`과(와) `{related}`의 관계를 설명하시오.")
        lines.append(
            f"- 정답 및 해설: `{concept}`은(는) 강의의 핵심 축이며, `{related}`과(와)의 상호작용을 통해 실제 해석 기준이 정리됩니다."
        )
    lines.append("")

    lines.append("## 📗 꼭 공부해야 할 내용을 알려줘")
    lines.append("")
    lines.append("### 핵심 키워드 정의")
    defs = concepts + keywords[:5]
    seen_defs: set[str] = set()
    for term in defs:
        if term in seen_defs:
            continue
        seen_defs.add(term)
        lines.append(f"- **{term}**: 강의 흐름에서 반복적으로 등장하며 개념 연결의 기준이 되는 핵심 용어.")
    lines.append("")
    lines.append("### 단계별 이해 흐름")
    lines.append("1. 기본 개념 정의: 용어의 뜻과 범위를 먼저 확정한다.")
    lines.append("2. 관계 정리: 개념 간 연결(원인-결과, 대비, 포함)을 구조화한다.")
    lines.append("3. 적용 연습: 사례 문장에 개념을 대입해 해석 기준을 점검한다.")
    lines.append("4. 오개념 교정: 유사 개념을 구분하고 혼동 포인트를 정리한다.")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    input_root = Path(args.input_root)
    output_base = Path(args.output_root) / args.agent_name
    md_root = output_base / "md"
    txt_root = output_base / "txt"

    if not input_root.exists():
        print(f"[ERROR] input root not found: {input_root}")
        return 1

    files = sorted(input_root.rglob("*.txt"))
    if not files:
        print(f"[ERROR] no txt files found under: {input_root}")
        return 1

    domain_terms = load_domain_terms(Path(args.terms_path))

    generated = 0
    for src in files:
        rel = src.relative_to(input_root)
        text = src.read_text(encoding="utf-8")
        summary = make_summary_text(src, text, args.max_theme_bullets, domain_terms)

        md_path = (md_root / rel).with_suffix(".md")
        txt_path = (txt_root / rel).with_suffix(".txt")
        md_path.parent.mkdir(parents=True, exist_ok=True)
        txt_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(summary, encoding="utf-8")
        txt_path.write_text(summary, encoding="utf-8")
        generated += 1

    print(f"[DONE] source files: {len(files)}")
    print(f"[DONE] generated md: {generated}")
    print(f"[DONE] generated txt: {generated}")
    print(f"[DONE] output root: {output_base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
