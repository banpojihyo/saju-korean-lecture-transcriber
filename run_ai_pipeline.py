#!/usr/bin/env python3
"""Unified AI batch pipeline for summaries and study packs."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable


DEFAULT_INPUT_ROOT = Path("data/daglo/corr/script")
ALT_INPUT_ROOT = Path("data/daglo/script")

PROVIDERS = ("openai", "gemini")
STYLES = ("summary", "study-pack", "merged")
OUTPUT_FORMATS = ("md", "txt", "both")

SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

TOPIC_SYSTEM_GUIDE: dict[str, str] = {
    "general": (
        "여러 강의 도메인에 공통 적용 가능한 중립적 학습 자료를 작성한다. "
        "정의-근거-적용 순서로 정리한다."
    ),
    "saju": (
        "사주/명리학 강의 맥락을 우선한다. "
        "음양, 오행, 천간, 지지, 십성, 용신, 왕쇠강약, 생극제화 같은 용어를 정확히 사용한다."
    ),
    "network": (
        "네트워크 공학 강의 맥락을 우선한다. "
        "OSI/TCP-IP 계층, 패킷 흐름, 라우팅, 프로토콜 동작, 성능 지표를 명확히 구분한다."
    ),
    "security": (
        "정보보안 강의 맥락을 우선한다. "
        "위협-취약점-대응 흐름과 CIA(기밀성/무결성/가용성), 인증/인가, 암호, 운영 보안을 정확히 구분한다."
    ),
    "math": (
        "수학 강의 맥락을 우선한다. "
        "정의-정리-예시-적용 흐름으로 쓰고, 위상수학/딥러닝/강화학습 용어를 혼동 없이 사용한다."
    ),
    "philosophy": (
        "철학 강의 맥락을 우선한다. "
        "개념 정의, 사상가 관점 차이, 논증 구조를 중심으로 정리한다."
    ),
    "philosophy_east": (
        "동양철학 강의 맥락을 우선한다. "
        "유가/도가/불교 및 성리학 개념을 맥락에 맞게 구분해 정리한다."
    ),
    "philosophy_west": (
        "서양철학 강의 맥락을 우선한다. "
        "인식론/존재론/윤리학 틀과 사상가별 문제의식을 비교해 정리한다."
    ),
    "vocal": (
        "보컬 수업 맥락을 우선한다. "
        "발성, 호흡, 공명, 성구 전환, 리듬/표현을 실습 관점으로 정리한다."
    ),
    "essay": (
        "논술/글쓰기 강의 맥락을 우선한다. "
        "논제 분석, 주장-근거-반박 구조, 문단 구성과 표현 전략을 중심으로 정리한다."
    ),
}

STYLE_GUIDE: dict[str, str] = {
    "summary": (
        "목표: 핵심 요약과 시험 대비 포인트 정리.\n"
        "결과는 핵심 주제, 핵심 개념, 시험 포인트, 혼동 주의를 중심으로 작성한다."
    ),
    "study-pack": (
        "목표: 학습자가 바로 공부할 수 있는 패키지 제작.\n"
        "결과는 주제별 정리, 시험문제 5개, 핵심 요약 노트 중심으로 작성한다."
    ),
    "merged": (
        "목표: summary와 study-pack의 장점을 결합한 통합 결과 생성.\n"
        "결과는 주제별 정리 + 핵심 개념맵 + 시험문제 + 시험 포인트/혼동 주의 + 핵심 요약 노트를 포함한다."
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Unified batch generator for AI summaries/study packs with provider selection."
        )
    )
    parser.add_argument(
        "--provider",
        choices=PROVIDERS,
        required=True,
        help="AI provider to use.",
    )
    parser.add_argument(
        "--style",
        choices=STYLES,
        default="merged",
        help="Output style (default: merged).",
    )
    parser.add_argument(
        "--topic",
        default="general",
        help="Topic profile used for system prompt and dictionary hints.",
    )
    parser.add_argument(
        "--input-root",
        default=str(DEFAULT_INPUT_ROOT),
        help=(
            "Input root containing transcript txt files. "
            "Default: data/daglo/corr/script "
            "(falls back to data/daglo/script if missing)."
        ),
    )
    parser.add_argument(
        "--output-root",
        default="data/summaries",
        help="Output root (default: data/summaries).",
    )
    parser.add_argument(
        "--agent-name",
        default="Unified-AI",
        help="Agent folder name under output root and topic.",
    )
    parser.add_argument(
        "--output-format",
        choices=OUTPUT_FORMATS,
        default="both",
        help="Output format: md, txt, or both (default: both).",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Model name. If empty, provider default is used.",
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="API key. If empty, provider-specific env var is used.",
    )
    parser.add_argument(
        "--base-url",
        default="",
        help="Custom API base URL. If empty, provider default is used.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.2,
        help="Sampling temperature.",
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=3200,
        help="Max output tokens per request.",
    )
    parser.add_argument(
        "--chunk-chars",
        type=int,
        default=8000,
        help="Approx chars per chunk for long transcripts.",
    )
    parser.add_argument(
        "--merge-limit-chars",
        type=int,
        default=40000,
        help="If chunk notes exceed this size, run recursive merge before final step.",
    )
    parser.add_argument(
        "--terms-path",
        default="",
        help=(
            "Optional terms CSV path. If omitted, uses dict/common/terms.csv "
            "and tries dict/topics/<topic>/terms.csv."
        ),
    )
    parser.add_argument(
        "--no-common-terms",
        action="store_true",
        help="Do not auto-load dict/common/terms.csv.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Process at most N files (0 means all).",
    )
    parser.add_argument(
        "--sleep-sec",
        type=float,
        default=0.0,
        help="Optional delay between files.",
    )
    parser.add_argument(
        "--final-retries",
        type=int,
        default=2,
        help=(
            "Additional retries for final generation when output looks incomplete. "
            "Default: 2."
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files.",
    )
    return parser.parse_args()


def provider_default_model(provider: str) -> str:
    if provider == "openai":
        return "gpt-5"
    return "gemini-2.5-flash"


def provider_default_base_url(provider: str) -> str:
    if provider == "openai":
        return "https://api.openai.com/v1"
    return "https://generativelanguage.googleapis.com/v1beta"


def provider_env_key(provider: str) -> str:
    if provider == "openai":
        return "OPENAI_API_KEY"
    return "GEMINI_API_KEY"


def resolve_input_root(raw: str) -> Path:
    given = Path(raw)
    if given.exists():
        return given
    if given == DEFAULT_INPUT_ROOT and ALT_INPUT_ROOT.exists():
        return ALT_INPUT_ROOT
    return given


def resolve_terms_paths(args: argparse.Namespace) -> list[Path]:
    paths: list[Path] = []

    if not args.no_common_terms:
        paths.append(Path("dict/common/terms.csv"))

    if args.topic:
        topic_path = Path("dict") / "topics" / args.topic / "terms.csv"
        paths.append(topic_path)

    if args.terms_path:
        paths.append(Path(args.terms_path))

    # Keep order, remove duplicates.
    uniq: list[Path] = []
    seen: set[Path] = set()
    for p in paths:
        rp = p.resolve() if p.exists() else p
        if rp in seen:
            continue
        seen.add(rp)
        uniq.append(p)
    return uniq


def load_terms(paths: list[Path]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                term = (row.get("term") or "").strip()
                if not term or term in seen:
                    continue
                seen.add(term)
                terms.append(term)
    return terms


def terms_in_text(text: str, terms: Iterable[str], limit: int = 80) -> list[str]:
    hits: list[str] = []
    for term in terms:
        if term in text:
            hits.append(term)
            if len(hits) >= limit:
                break
    return hits


def split_long_text(text: str, max_chars: int) -> list[str]:
    parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not parts:
        return [text] if text else []

    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0

    def flush() -> None:
        nonlocal buf, buf_len
        if buf:
            chunks.append("\n\n".join(buf).strip())
            buf = []
            buf_len = 0

    for part in parts:
        if len(part) <= max_chars:
            if buf_len + len(part) + 2 <= max_chars:
                buf.append(part)
                buf_len += len(part) + 2
            else:
                flush()
                buf.append(part)
                buf_len = len(part)
            continue

        sents = [s.strip() for s in SENT_SPLIT_RE.split(part) if s.strip()]
        if not sents:
            sents = [part]

        for sent in sents:
            if len(sent) > max_chars:
                for i in range(0, len(sent), max_chars):
                    frag = sent[i : i + max_chars]
                    if buf_len + len(frag) + 1 <= max_chars:
                        buf.append(frag)
                        buf_len += len(frag) + 1
                    else:
                        flush()
                        buf.append(frag)
                        buf_len = len(frag)
                continue

            if buf_len + len(sent) + 1 <= max_chars:
                buf.append(sent)
                buf_len += len(sent) + 1
            else:
                flush()
                buf.append(sent)
                buf_len = len(sent)

    flush()
    return [c for c in chunks if c]


def build_system_prompt(topic: str, style: str) -> str:
    topic_text = TOPIC_SYSTEM_GUIDE.get(topic, TOPIC_SYSTEM_GUIDE["general"])
    style_text = STYLE_GUIDE[style]
    return (
        "당신은 강의 대본을 학습용 자료로 재구성하는 전문가다.\n"
        f"주제 지침: {topic_text}\n"
        f"출력 스타일: {style_text}\n"
        "규칙:\n"
        "1) 원문에 없는 사실을 만들지 않는다.\n"
        "2) 단정이 어려운 경우 조건부/중립 표현을 사용한다.\n"
        "3) 출력은 한국어 마크다운으로 작성한다.\n"
        "4) 요청한 섹션 헤더/형식을 정확히 지킨다.\n"
        "5) 불필요한 서론, 면책 문구, 메타 발화를 쓰지 않는다.\n"
    )


def make_chunk_prompt(
    file_name: str,
    chunk_idx: int,
    chunk_total: int,
    chunk_text: str,
    glossary: list[str],
) -> str:
    glossary_text = ", ".join(glossary) if glossary else "(없음)"
    return f"""[파일]
{file_name}

[용어 힌트]
{glossary_text}

[지시]
아래는 전체 강의의 일부 조각({chunk_idx}/{chunk_total})이다.
핵심만 추려 조각 노트를 작성하라.

[출력 형식]
### 조각 핵심 주제
- ...

### 조각 핵심 개념
- 개념명: 설명

### 조각 시험 포인트
- ...

### 조각 혼동 주의
- ...

[원문]
{chunk_text}
"""


def make_merge_prompt(group_notes: list[str], group_idx: int, total_groups: int) -> str:
    joined = "\n\n---\n\n".join(group_notes)
    return f"""[지시]
아래는 같은 파일에서 나온 조각 노트들이다.
중복을 제거하고 핵심만 남겨 통합 노트로 압축하라.

[출력 형식]
### 통합 핵심 주제
- ...

### 통합 핵심 개념
- 개념명: 설명

### 통합 시험 포인트
- ...

### 통합 혼동 주의
- ...

[현재 그룹]
{group_idx}/{total_groups}

[입력 노트]
{joined}
"""


def final_template(style: str) -> str:
    if style == "summary":
        return (
            "## 🔖 핵심 주제별로 나눠서 정리\n"
            "### 주제 1\n"
            "- ...\n"
            "### 주제 2\n"
            "- ...\n\n"
            "## 🧠 핵심 개념 맵\n"
            "- 개념: 설명\n\n"
            "## 🎯 시험 포인트\n"
            "- ...\n\n"
            "## ⚠️ 혼동 주의\n"
            "- ..."
        )
    if style == "study-pack":
        return (
            "## 🔖 핵심 주제별로 나눠서 정리\n"
            "### 주제 1\n"
            "- ...\n"
            "### 주제 2\n"
            "- ...\n\n"
            "## 📑 시험문제\n"
            "### 핵심 개념 1\n"
            "1. 예상 문제: ...\n"
            "2. 정답 및 해설: ...\n"
            "### 핵심 개념 2\n"
            "1. 예상 문제: ...\n"
            "2. 정답 및 해설: ...\n"
            "### 핵심 개념 3\n"
            "1. 예상 문제: ...\n"
            "2. 정답 및 해설: ...\n"
            "### 핵심 개념 4\n"
            "1. 예상 문제: ...\n"
            "2. 정답 및 해설: ...\n"
            "### 핵심 개념 5\n"
            "1. 예상 문제: ...\n"
            "2. 정답 및 해설: ...\n\n"
            "## 📗 꼭 공부해야 할 내용\n"
            "### 핵심 키워드 정의\n"
            "- ...\n"
            "### 단계별 이해\n"
            "1. ...\n"
            "2. ...\n"
            "3. ..."
        )
    # merged
    return (
        "## 🔖 핵심 주제별로 나눠서 정리\n"
        "### 주제 1\n"
        "- ...\n"
        "### 주제 2\n"
        "- ...\n\n"
        "## 🧠 핵심 개념 맵\n"
        "- 개념: 설명\n\n"
        "## 📑 시험문제\n"
        "### 핵심 개념 1\n"
        "1. 예상 문제: ...\n"
        "2. 정답 및 해설: ...\n"
        "### 핵심 개념 2\n"
        "1. 예상 문제: ...\n"
        "2. 정답 및 해설: ...\n"
        "### 핵심 개념 3\n"
        "1. 예상 문제: ...\n"
        "2. 정답 및 해설: ...\n"
        "### 핵심 개념 4\n"
        "1. 예상 문제: ...\n"
        "2. 정답 및 해설: ...\n"
        "### 핵심 개념 5\n"
        "1. 예상 문제: ...\n"
        "2. 정답 및 해설: ...\n\n"
        "## 🎯 시험 포인트/혼동 주의\n"
        "### 시험 포인트\n"
        "- ...\n"
        "### 혼동 주의\n"
        "- ...\n\n"
        "## 📗 꼭 공부해야 할 내용\n"
        "### 핵심 키워드 정의\n"
        "- ...\n"
        "### 단계별 이해\n"
        "1. ...\n"
        "2. ...\n"
        "3. ..."
    )


def make_final_prompt(
    file_name: str,
    merged_notes: list[str],
    glossary: list[str],
    style: str,
) -> str:
    notes_text = "\n\n====\n\n".join(merged_notes)
    glossary_text = ", ".join(glossary) if glossary else "(없음)"
    template = final_template(style)
    return f"""[파일]
{file_name}

[용어 힌트]
{glossary_text}

[지시]
아래 통합 노트를 바탕으로 결과를 작성하라.
사용자가 채팅에 요청한 답변처럼 자연스럽고 완결된 마크다운 형태로 작성하라.
파일 첨부 안내, 메타 문장, 사족은 금지한다.

반드시 아래 출력 템플릿 구조를 따른다.
[출력 템플릿]
{template}

[통합 노트]
{notes_text}
"""


def required_sections(style: str) -> list[str]:
    if style == "summary":
        return [
            "## 🔖 핵심 주제별로 나눠서 정리",
            "## 🧠 핵심 개념 맵",
            "## 🎯 시험 포인트",
            "## ⚠️ 혼동 주의",
        ]
    if style == "study-pack":
        return [
            "## 🔖 핵심 주제별로 나눠서 정리",
            "## 📑 시험문제",
            "## 📗 꼭 공부해야 할 내용",
        ]
    return [
        "## 🔖 핵심 주제별로 나눠서 정리",
        "## 🧠 핵심 개념 맵",
        "## 📑 시험문제",
        "## 🎯 시험 포인트/혼동 주의",
        "## 📗 꼭 공부해야 할 내용",
    ]


def looks_incomplete_output(text: str, style: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True

    # Prefer exact template checks when available, but do not require exact wording.
    exact_hits = sum(1 for sec in required_sections(style) if sec in stripped)

    if style == "summary":
        min_sections = 4
        keywords = ("주제", "개념", "시험", "주의")
    elif style == "study-pack":
        min_sections = 3
        keywords = ("주제", "시험", "공부")
    else:
        min_sections = 5
        keywords = ("주제", "개념", "시험", "공부")

    lines = [ln.rstrip() for ln in stripped.splitlines()]
    if not lines:
        return True

    top_level_sections = sum(1 for ln in lines if ln.startswith("## "))
    any_headings = sum(1 for ln in lines if ln.startswith("#"))
    if top_level_sections < min_sections and any_headings < (min_sections + 2):
        return True

    if exact_hits == 0:
        for kw in keywords:
            if kw not in stripped:
                return True

    if len(stripped) < 240:
        return True

    last = lines[-1].strip()
    if not last:
        return True
    if last.startswith(("### ", "## ")):
        return True
    if last in {"-", "1.", "2.", "3.", "4.", "5."}:
        return True

    return False


def make_repair_prompt(
    file_name: str,
    merged_notes: list[str],
    glossary: list[str],
    style: str,
    previous_output: str,
) -> str:
    notes_text = "\n\n====\n\n".join(merged_notes)
    glossary_text = ", ".join(glossary) if glossary else "(없음)"
    template = final_template(style)
    return f"""[파일]
{file_name}

[용어 힌트]
{glossary_text}

[지시]
직전 출력이 중간에서 끊겼다.
이전 출력은 참고만 하고, 처음부터 끝까지 전체 결과를 다시 완성해서 작성하라.
섹션 누락/중간 끊김/미완성 소제목(예: '### 주제'로 끝남) 없이 완성형으로 출력하라.
출력 길이가 길어질 경우 각 bullet을 1~2문장으로 간결하게 유지하라.

[출력 템플릿]
{template}

[직전 불완전 출력]
{previous_output}

[통합 노트]
{notes_text}
"""


def is_quota_exceeded_error(error: Exception) -> bool:
    msg = str(error).lower()
    quota_signals = (
        "http 429",
        "resource_exhausted",
        "quota exceeded",
        "rate limit",
    )
    return any(sig in msg for sig in quota_signals)


def compose_partial_output(
    style: str,
    stage: str,
    chunk_notes: list[str],
    merged_notes: list[str],
    result_text: str,
    error: Exception,
) -> str:
    error_line = str(error).splitlines()[0].strip()
    lines: list[str] = [
        "## ⚠️ 부분 결과 안내",
        f"- 생성 중단 지점: `{stage}`",
        "- 사유: API 요청 한도 초과(429/RESOURCE_EXHAUSTED)",
        "- 아래 내용은 한도 초과 직전까지 생성된 결과입니다.",
    ]
    if error_line:
        lines.append(f"- 오류 요약: `{error_line}`")
    lines.append("")

    if result_text.strip():
        lines.append(result_text.strip())
        return "\n".join(lines).strip()

    if merged_notes:
        lines.append("## 한도 초과 전 통합 노트")
        for idx, note in enumerate(merged_notes, start=1):
            lines.append(f"### 통합 노트 {idx}")
            lines.append(note.strip())
            lines.append("")
        return "\n".join(lines).strip()

    if chunk_notes:
        lines.append("## 한도 초과 전 청크 요약")
        for idx, note in enumerate(chunk_notes, start=1):
            lines.append(f"### 청크 {idx}")
            lines.append(note.strip())
            lines.append("")
        return "\n".join(lines).strip()

    # Nothing was generated before hitting quota.
    if style == "summary":
        lines.append("## 🔖 핵심 주제별로 나눠서 정리")
        lines.append("- (생성된 내용 없음)")
    elif style == "study-pack":
        lines.append("## 🔖 핵심 주제별로 나눠서 정리")
        lines.append("- (생성된 내용 없음)")
        lines.append("## 📑 시험문제")
        lines.append("- (생성된 내용 없음)")
        lines.append("## 📗 꼭 공부해야 할 내용")
        lines.append("- (생성된 내용 없음)")
    else:
        lines.append("## 🔖 핵심 주제별로 나눠서 정리")
        lines.append("- (생성된 내용 없음)")
        lines.append("## 🧠 핵심 개념 맵")
        lines.append("- (생성된 내용 없음)")
        lines.append("## 📑 시험문제")
        lines.append("- (생성된 내용 없음)")
        lines.append("## 🎯 시험 포인트/혼동 주의")
        lines.append("- (생성된 내용 없음)")
        lines.append("## 📗 꼭 공부해야 할 내용")
        lines.append("- (생성된 내용 없음)")
    return "\n".join(lines).strip()


def extract_openai_text(payload: dict) -> str:
    text = payload.get("output_text")
    if isinstance(text, str) and text.strip():
        return text.strip()

    outputs = payload.get("output")
    if isinstance(outputs, list):
        collected: list[str] = []
        for item in outputs:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                ptype = part.get("type")
                if ptype in {"output_text", "text"}:
                    txt = part.get("text", "")
                    if isinstance(txt, str) and txt.strip():
                        collected.append(txt.strip())
        if collected:
            return "\n\n".join(collected).strip()

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message", {})
        content = msg.get("content", "")
        if isinstance(content, str):
            return content.strip()
    return ""


def extract_gemini_text(payload: dict) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return ""
    texts: list[str] = []
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        content = cand.get("content")
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
    return "\n\n".join(texts).strip()


class BaseClient:
    def call(
        self,
        system_prompt: str,
        user_prompt: str,
        retries: int = 5,
        max_output_tokens: int | None = None,
    ) -> str:
        raise NotImplementedError


class OpenAIClient(BaseClient):
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float,
        max_output_tokens: int,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens

    def call(
        self,
        system_prompt: str,
        user_prompt: str,
        retries: int = 5,
        max_output_tokens: int | None = None,
    ) -> str:
        url = f"{self.base_url}/responses"
        output_limit = max_output_tokens or self.max_output_tokens
        body = {
            "model": self.model,
            "temperature": self.temperature,
            "max_output_tokens": output_limit,
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": user_prompt}],
                },
            ],
        }
        data = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        last_err: Exception | None = None
        for attempt in range(1, retries + 1):
            req = urllib.request.Request(url=url, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=240) as resp:
                    raw = resp.read().decode("utf-8")
                payload = json.loads(raw)
                out = extract_openai_text(payload)
                if out:
                    return out
                raise RuntimeError("OpenAI response has no text output.")
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", errors="ignore")
                except Exception:
                    detail = str(e)
                last_err = RuntimeError(f"HTTP {e.code}: {detail}")
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as e:
                last_err = e

            if attempt < retries:
                time.sleep(min(20, 1.8**attempt))

        raise RuntimeError(f"OpenAI API call failed after {retries} retries: {last_err}")


class GeminiClient(BaseClient):
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float,
        max_output_tokens: int,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens

    def call(
        self,
        system_prompt: str,
        user_prompt: str,
        retries: int = 5,
        max_output_tokens: int | None = None,
    ) -> str:
        url = f"{self.base_url}/models/{self.model}:generateContent"
        output_limit = max_output_tokens or self.max_output_tokens
        body = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": output_limit,
            },
        }
        data = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

        last_err: Exception | None = None
        for attempt in range(1, retries + 1):
            req = urllib.request.Request(url=url, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=240) as resp:
                    raw = resp.read().decode("utf-8")
                payload = json.loads(raw)
                out = extract_gemini_text(payload)
                if out:
                    return out
                feedback = payload.get("promptFeedback")
                raise RuntimeError(f"Gemini response has no text output. {feedback}")
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", errors="ignore")
                except Exception:
                    detail = str(e)
                last_err = RuntimeError(f"HTTP {e.code}: {detail}")
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as e:
                last_err = e

            if attempt < retries:
                time.sleep(min(20, 1.8**attempt))

        raise RuntimeError(f"Gemini API call failed after {retries} retries: {last_err}")


def create_client(args: argparse.Namespace) -> BaseClient:
    model = args.model.strip() or provider_default_model(args.provider)
    base_url = args.base_url.strip() or provider_default_base_url(args.provider)
    api_key = args.api_key.strip() or os.environ.get(provider_env_key(args.provider), "")
    if not api_key:
        raise RuntimeError(
            f"Missing API key. Set {provider_env_key(args.provider)} or pass --api-key."
        )

    if args.provider == "openai":
        return OpenAIClient(
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=args.temperature,
            max_output_tokens=args.max_output_tokens,
        )
    return GeminiClient(
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=args.temperature,
        max_output_tokens=args.max_output_tokens,
    )


def ensure_header(text: str, stem: str, style: str) -> str:
    display_stem = stem[:-7] if stem.lower().endswith(".script") else stem
    if text.lstrip().startswith("# "):
        return text.rstrip() + "\n"
    if style == "summary":
        title = f"# {display_stem} AI Summary"
    elif style == "study-pack":
        title = f"# {display_stem} Study Pack"
    else:
        title = f"# {display_stem} 통합 학습 패키지"
    return f"{title}\n\n{text.rstrip()}\n"


def render_one_file(
    client: BaseClient,
    system_prompt: str,
    src: Path,
    rel: Path,
    md_root: Path,
    txt_root: Path,
    output_format: str,
    style: str,
    chunk_chars: int,
    merge_limit_chars: int,
    glossary_terms: list[str],
    final_retries: int,
    overwrite: bool,
) -> tuple[bool, str]:
    md_path = (md_root / rel).with_suffix(".md")
    txt_path = (txt_root / rel).with_suffix(".txt")

    should_write_md = output_format in {"md", "both"}
    should_write_txt = output_format in {"txt", "both"}

    exists = True
    if should_write_md and not md_path.exists():
        exists = False
    if should_write_txt and not txt_path.exists():
        exists = False
    if exists and not overwrite:
        return False, f"[SKIP] {rel}"

    def write_outputs(content: str) -> None:
        if should_write_md:
            md_path.parent.mkdir(parents=True, exist_ok=True)
            md_path.write_text(content, encoding="utf-8")
        if should_write_txt:
            txt_path.parent.mkdir(parents=True, exist_ok=True)
            txt_path.write_text(content, encoding="utf-8")

    text = src.read_text(encoding="utf-8")
    chunks = split_long_text(text, max_chars=chunk_chars)
    if not chunks:
        chunks = [text]

    stage = "init"
    chunk_notes: list[str] = []
    merged_notes: list[str] = []
    result_text = ""

    try:
        for idx, chunk in enumerate(chunks, start=1):
            stage = f"chunk {idx}/{len(chunks)}"
            chunk_prompt = make_chunk_prompt(
                file_name=src.name,
                chunk_idx=idx,
                chunk_total=len(chunks),
                chunk_text=chunk,
                glossary=glossary_terms,
            )
            chunk_notes.append(client.call(system_prompt, chunk_prompt))

        merged_notes = chunk_notes
        while len(merged_notes) > 1 and sum(len(n) for n in merged_notes) > merge_limit_chars:
            merged: list[str] = []
            group_size = 6
            total_groups = (len(merged_notes) + group_size - 1) // group_size
            for i in range(0, len(merged_notes), group_size):
                stage = f"merge {i // group_size + 1}/{total_groups}"
                group = merged_notes[i : i + group_size]
                merge_prompt = make_merge_prompt(group, i // group_size + 1, total_groups)
                merged.append(client.call(system_prompt, merge_prompt))
            merged_notes = merged

        stage = "final"
        final_prompt = make_final_prompt(src.name, merged_notes, glossary_terms, style)
        result_text = client.call(system_prompt, final_prompt)

        retry_count = max(0, final_retries)
        base_limit = getattr(client, "max_output_tokens", 3200)
        for attempt in range(retry_count):
            if not looks_incomplete_output(result_text, style):
                break
            stage = f"repair {attempt + 1}/{retry_count}"
            repair_prompt = make_repair_prompt(
                file_name=src.name,
                merged_notes=merged_notes,
                glossary=glossary_terms,
                style=style,
                previous_output=result_text,
            )
            boosted_limit = min(8192, int(base_limit * (2 ** (attempt + 1))))
            result_text = client.call(
                system_prompt,
                repair_prompt,
                max_output_tokens=boosted_limit,
            )

        if looks_incomplete_output(result_text, style):
            raise RuntimeError(
                "Final output appears incomplete after retries. "
                "Increase --max-output-tokens or --final-retries."
            )

        result = ensure_header(result_text, src.stem, style)
        write_outputs(result)
        return True, f"[DONE] {rel} (chunks={len(chunks)})"

    except Exception as e:
        if is_quota_exceeded_error(e):
            partial = compose_partial_output(
                style=style,
                stage=stage,
                chunk_notes=chunk_notes,
                merged_notes=merged_notes or chunk_notes,
                result_text=result_text,
                error=e,
            )
            write_outputs(ensure_header(partial, src.stem, style))
            return True, f"[PARTIAL] {rel} (stage={stage}; quota exceeded)"
        raise


def main() -> int:
    args = parse_args()

    input_root = resolve_input_root(args.input_root)
    if not input_root.exists():
        print(f"[ERROR] input root not found: {input_root}")
        return 1

    try:
        client = create_client(args)
    except RuntimeError as e:
        print(f"[ERROR] {e}")
        return 1

    terms_paths = resolve_terms_paths(args)
    terms = load_terms(terms_paths)

    output_base = Path(args.output_root) / args.topic / args.agent_name
    md_root = output_base / "md"
    txt_root = output_base / "txt"

    files = sorted(input_root.rglob("*.txt"))
    if args.max_files > 0:
        files = files[: args.max_files]
    if not files:
        print(f"[ERROR] no input txt files under: {input_root}")
        return 1

    system_prompt = build_system_prompt(args.topic, args.style)

    model_name = args.model.strip() or provider_default_model(args.provider)
    base_url = args.base_url.strip() or provider_default_base_url(args.provider)
    print(f"[INFO] provider={args.provider} model={model_name} style={args.style}")
    print(f"[INFO] topic={args.topic} input_root={input_root}")
    print(f"[INFO] output_root={output_base} output_format={args.output_format}")
    print(
        "[INFO] terms_paths="
        + ", ".join(str(p) for p in terms_paths)
        + f" (loaded={len(terms)})"
    )

    done = 0
    partial = 0
    skipped = 0
    failed = 0

    for idx, src in enumerate(files, start=1):
        rel = src.relative_to(input_root)
        try:
            text = src.read_text(encoding="utf-8")
            glossary = terms_in_text(text, terms, limit=80)
            wrote, msg = render_one_file(
                client=client,
                system_prompt=system_prompt,
                src=src,
                rel=rel,
                md_root=md_root,
                txt_root=txt_root,
                output_format=args.output_format,
                style=args.style,
                chunk_chars=args.chunk_chars,
                merge_limit_chars=args.merge_limit_chars,
                glossary_terms=glossary,
                final_retries=args.final_retries,
                overwrite=args.overwrite,
            )
            print(f"[{idx}/{len(files)}] {msg}")
            if wrote:
                if msg.startswith("[PARTIAL]"):
                    partial += 1
                else:
                    done += 1
            else:
                skipped += 1
        except Exception as e:
            failed += 1
            print(f"[{idx}/{len(files)}] [FAIL] {rel}: {e}")

        if args.sleep_sec > 0:
            time.sleep(args.sleep_sec)

    print(
        f"[SUMMARY] total={len(files)} done={done} partial={partial} "
        f"skipped={skipped} failed={failed}"
    )
    print(f"[SUMMARY] output={output_base}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
