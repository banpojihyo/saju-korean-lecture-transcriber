#!/usr/bin/env python3
"""Generate study packs (summary + exam + study notes) via Gemini API."""

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

SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate markdown study packs from transcript txt files using Gemini API."
        )
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
        default="data/study_packs",
        help="Output root for generated files (default: data/study_packs).",
    )
    parser.add_argument(
        "--agent-name",
        default="Gemini-Study-Pack",
        help="Agent folder name under output root.",
    )
    parser.add_argument(
        "--model",
        default="gemini-2.5-flash",
        help="Gemini model name (for example: gemini-2.5-flash).",
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
        default=3072,
        help="Max output tokens per request.",
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="Gemini API key. If omitted, GEMINI_API_KEY env var is used.",
    )
    parser.add_argument(
        "--base-url",
        default="https://generativelanguage.googleapis.com/v1beta",
        help="Gemini REST base URL.",
    )
    parser.add_argument(
        "--topic",
        default="",
        help=(
            "Optional topic name under dict/topics. "
            "If --terms-path is omitted, uses dict/topics/<topic>/terms.csv."
        ),
    )
    parser.add_argument(
        "--terms-path",
        default="",
        help=(
            "Terms CSV path. If omitted: "
            "dict/topics/<topic>/terms.csv (when --topic is set), "
            "otherwise dict/common/terms.csv."
        ),
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
        help="If chunk notes exceed this size, merge recursively before final step.",
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
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files.",
    )
    return parser.parse_args()


def resolve_input_root(raw: str) -> Path:
    given = Path(raw)
    if given.exists():
        return given

    # Convenience fallback for user's legacy path naming.
    if given == DEFAULT_INPUT_ROOT and ALT_INPUT_ROOT.exists():
        return ALT_INPUT_ROOT
    return given


def resolve_terms_path(args: argparse.Namespace) -> Path:
    if args.terms_path:
        return Path(args.terms_path)
    if args.topic:
        return Path("dict") / "topics" / args.topic / "terms.csv"
    return Path("dict/common/terms.csv")


def load_terms(path: Path) -> list[str]:
    if not path.exists():
        return []

    terms: list[str] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            term = (row.get("term") or "").strip()
            if not term or term in seen:
                continue
            seen.add(term)
            terms.append(term)
    return terms


def terms_in_text(text: str, terms: Iterable[str], limit: int = 60) -> list[str]:
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


def extract_output_text(payload: dict) -> str:
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


class GeminiClient:
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

    def call(self, system_prompt: str, user_prompt: str, retries: int = 5) -> str:
        url = f"{self.base_url}/models/{self.model}:generateContent"
        body = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_output_tokens,
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
                text = extract_output_text(payload)
                if text:
                    return text

                feedback = payload.get("promptFeedback")
                raise RuntimeError(f"No text output. promptFeedback={feedback}")
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


SYSTEM_PROMPT = """당신은 대학 강의 스크립트를 학습용 자료로 재구성하는 전문 출제위원이다.
주어진 전사 텍스트를 바탕으로 정확하고 구조화된 결과를 작성한다.

규칙:
1) 원문에 없는 사실을 추가하지 않는다.
2) 모호한 내용은 단정하지 않고 조건부 표현을 쓴다.
3) 결과는 한국어 마크다운으로 작성한다.
4) 각 섹션은 요청된 형식을 정확히 따른다.
5) 불필요한 서론/인사/메타 코멘트는 쓰지 않는다.
"""


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
아래 텍스트는 전체 강의 중 일부 조각({chunk_idx}/{chunk_total})이다.
이 조각에서 핵심 개념, 주장, 흐름만 간결히 정리하라.

[출력 형식]
### 조각 핵심 주제
- ...

### 조각 핵심 개념
- 개념명: 설명

### 조각 중요 포인트
- ...

[원문]
{chunk_text}
"""


def make_merge_prompt(group_notes: list[str], group_idx: int, total_groups: int) -> str:
    joined = "\n\n---\n\n".join(group_notes)
    return f"""[지시]
아래는 같은 파일에서 나온 조각 요약들이다.
중복을 제거하고 핵심만 남겨 통합 노트로 압축하라.

[출력 형식]
### 통합 핵심 주제
- ...

### 통합 핵심 개념
- 개념명: 설명

### 통합 중요 포인트
- ...

[현재 그룹]
{group_idx}/{total_groups}

[입력 노트]
{joined}
"""


def make_final_prompt(file_name: str, merged_notes: list[str], glossary: list[str]) -> str:
    notes_text = "\n\n====\n\n".join(merged_notes)
    glossary_text = ", ".join(glossary) if glossary else "(없음)"
    return f"""[파일]
{file_name}

[용어 힌트]
{glossary_text}

[지시]
아래 통합 노트를 바탕으로, 다음 세 가지 결과를 한 번에 작성하라.
형식은 반드시 그대로 지켜라.

1) 핵심 주제별 정리
- 각 주제를 ### 헤더로 구분
- 각 주제 아래는 bullet points 요약

2) 시험문제
- 가장 중요 개념 5개를 선정
- 각 개념마다:
  - 예상 문제: 객관식 또는 단답형
  - 정답 및 해설: 핵심 설명

3) 꼭 공부해야 할 내용
- 전체를 관통하는 핵심 키워드 정의
- 복잡한 개념/흐름은 단계별 설명

[출력 템플릿]
## 🔖 핵심 주제별로 나눠서 정리
### 주제 1
- ...
### 주제 2
- ...

## 📑 시험문제
### 핵심 개념 1
1. 예상 문제: ...
2. 정답 및 해설: ...
### 핵심 개념 2
1. 예상 문제: ...
2. 정답 및 해설: ...
### 핵심 개념 3
1. 예상 문제: ...
2. 정답 및 해설: ...
### 핵심 개념 4
1. 예상 문제: ...
2. 정답 및 해설: ...
### 핵심 개념 5
1. 예상 문제: ...
2. 정답 및 해설: ...

## 📗 꼭 공부해야 할 내용
### 핵심 키워드 정의
- ...
### 단계별 이해
1. ...
2. ...
3. ...

[통합 노트]
{notes_text}
"""


def recursive_merge_notes(
    client: GeminiClient,
    notes: list[str],
    limit_chars: int,
) -> list[str]:
    cur = notes
    while len(cur) > 1 and sum(len(n) for n in cur) > limit_chars:
        merged: list[str] = []
        group_size = 6
        total_groups = (len(cur) + group_size - 1) // group_size
        for i in range(0, len(cur), group_size):
            group = cur[i : i + group_size]
            prompt = make_merge_prompt(
                group_notes=group,
                group_idx=(i // group_size) + 1,
                total_groups=total_groups,
            )
            merged.append(client.call(SYSTEM_PROMPT, prompt))
        cur = merged
    return cur


def ensure_header(study_md: str, stem: str) -> str:
    if study_md.lstrip().startswith("# "):
        return study_md.rstrip() + "\n"
    return f"# {stem} 학습 패키지\n\n{study_md.rstrip()}\n"


def generate_one_file(
    client: GeminiClient,
    src: Path,
    rel: Path,
    md_root: Path,
    txt_root: Path,
    chunk_chars: int,
    merge_limit_chars: int,
    glossary_terms: list[str],
    overwrite: bool,
) -> tuple[bool, str]:
    md_path = (md_root / rel).with_suffix(".md")
    txt_path = (txt_root / rel).with_suffix(".txt")
    if not overwrite and md_path.exists() and txt_path.exists():
        return False, f"[SKIP] {rel}"

    text = src.read_text(encoding="utf-8")
    chunks = split_long_text(text, max_chars=chunk_chars)
    if not chunks:
        chunks = [text]

    chunk_notes: list[str] = []
    for idx, chunk in enumerate(chunks, start=1):
        prompt = make_chunk_prompt(
            file_name=src.name,
            chunk_idx=idx,
            chunk_total=len(chunks),
            chunk_text=chunk,
            glossary=glossary_terms,
        )
        chunk_notes.append(client.call(SYSTEM_PROMPT, prompt))

    merged = recursive_merge_notes(client, chunk_notes, limit_chars=merge_limit_chars)
    final_prompt = make_final_prompt(src.name, merged, glossary_terms)
    final_md = ensure_header(client.call(SYSTEM_PROMPT, final_prompt), src.stem)

    md_path.parent.mkdir(parents=True, exist_ok=True)
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(final_md, encoding="utf-8")
    txt_path.write_text(final_md, encoding="utf-8")
    return True, f"[DONE] {rel} (chunks={len(chunks)})"


def main() -> int:
    args = parse_args()

    input_root = resolve_input_root(args.input_root)
    if not input_root.exists():
        print(f"[ERROR] input root not found: {input_root}")
        return 1

    api_key = args.api_key or os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("[ERROR] API key is missing. Set GEMINI_API_KEY or pass --api-key.")
        return 1

    terms_path = resolve_terms_path(args)
    terms = load_terms(terms_path)

    output_base = Path(args.output_root) / args.agent_name
    md_root = output_base / "md"
    txt_root = output_base / "txt"

    files = sorted(input_root.rglob("*.txt"))
    if args.max_files > 0:
        files = files[: args.max_files]
    if not files:
        print(f"[ERROR] no input txt files under: {input_root}")
        return 1

    client = GeminiClient(
        api_key=api_key,
        base_url=args.base_url,
        model=args.model,
        temperature=args.temperature,
        max_output_tokens=args.max_output_tokens,
    )

    print(f"[INFO] input_root={input_root}")
    print(f"[INFO] output_root={output_base}")
    print(f"[INFO] model={args.model}")
    print(f"[INFO] terms_path={terms_path} (loaded={len(terms)})")
    if args.topic:
        print(f"[INFO] topic={args.topic}")

    done = 0
    skipped = 0
    failed = 0

    for idx, src in enumerate(files, start=1):
        rel = src.relative_to(input_root)
        try:
            text = src.read_text(encoding="utf-8")
            glossary = terms_in_text(text, terms, limit=60)

            wrote, msg = generate_one_file(
                client=client,
                src=src,
                rel=rel,
                md_root=md_root,
                txt_root=txt_root,
                chunk_chars=args.chunk_chars,
                merge_limit_chars=args.merge_limit_chars,
                glossary_terms=glossary,
                overwrite=args.overwrite,
            )
            print(f"[{idx}/{len(files)}] {msg}")
            if wrote:
                done += 1
            else:
                skipped += 1
        except Exception as e:
            failed += 1
            print(f"[{idx}/{len(files)}] [FAIL] {rel}: {e}")

        if args.sleep_sec > 0:
            time.sleep(args.sleep_sec)

    print(f"[SUMMARY] total={len(files)} done={done} skipped={skipped} failed={failed}")
    print(f"[SUMMARY] output={output_base}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
