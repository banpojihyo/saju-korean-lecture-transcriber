#!/usr/bin/env python3
"""Generate high-quality AI summaries from Daglo corrected scripts via API.

Features:
- API key via env var (`OPENAI_API_KEY`) or CLI
- OpenAI Responses API with retry/backoff
- Long-text context management (chunk -> merge -> final synthesis)
- Domain glossary injection from dict/terms.csv
- Preserves folder structure:
    data/daglo/corr/script/**/*.txt
      -> data/summary/{agent}/md/**/*.md
      -> data/summary/{agent}/txt/**/*.txt
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path


SENT_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate AI summaries using OpenAI-compatible API."
    )
    parser.add_argument(
        "--input-root",
        default="data/daglo/corr/script",
        help="Input root containing corrected script txt files.",
    )
    parser.add_argument(
        "--output-root",
        default="data/summary",
        help="Output root for AI summaries.",
    )
    parser.add_argument(
        "--agent-name",
        default="GPT-5.3-Codex",
        help="Agent folder name under output root.",
    )
    parser.add_argument(
        "--model",
        default="gpt-5",
        help="API model name. Override with your exact deployed model/version.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.2,
        help="Sampling temperature for summary generation.",
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=2200,
        help="Max output tokens per API call.",
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="API key (optional). If omitted, OPENAI_API_KEY env var is used.",
    )
    parser.add_argument(
        "--base-url",
        default="https://api.openai.com/v1",
        help="OpenAI-compatible API base URL.",
    )
    parser.add_argument(
        "--chunk-chars",
        type=int,
        default=7500,
        help="Approx chars per chunk for long transcripts.",
    )
    parser.add_argument(
        "--merge-limit-chars",
        type=int,
        default=45000,
        help="If chunk notes exceed this size, run recursive merge before final synthesis.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing outputs.",
    )
    parser.add_argument(
        "--terms-path",
        default="dict/terms.csv",
        help="Domain terms CSV for glossary injection.",
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
        help="Optional delay between files to reduce rate-limit pressure.",
    )
    return parser.parse_args()


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


def terms_in_text(text: str, terms: list[str], limit: int = 60) -> list[str]:
    hits: list[str] = []
    for term in terms:
        if term in text:
            hits.append(term)
            if len(hits) >= limit:
                break
    return hits


def split_long_text(text: str, max_chars: int) -> list[str]:
    """Split text by paragraph/sentence while preserving semantic chunks."""
    parts = [p.strip() for p in text.split("\n\n") if p.strip()]
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

        # Oversized paragraph -> sentence-level split fallback.
        sents = [s.strip() for s in SENT_SPLIT_RE.split(part) if s.strip()]
        for sent in sents:
            if len(sent) > max_chars:
                # Hard-cut for pathological lines.
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
    # Preferred shape (Responses API)
    text = payload.get("output_text")
    if isinstance(text, str) and text.strip():
        return text.strip()

    outputs = payload.get("output")
    if isinstance(outputs, list):
        collected: list[str] = []
        for item in outputs:
            contents = item.get("content") if isinstance(item, dict) else None
            if not isinstance(contents, list):
                continue
            for c in contents:
                if not isinstance(c, dict):
                    continue
                ctype = c.get("type")
                if ctype in {"output_text", "text"}:
                    t = c.get("text", "")
                    if isinstance(t, str) and t.strip():
                        collected.append(t.strip())
        if collected:
            return "\n\n".join(collected).strip()

    # Fallback shape (chat-like)
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message", {})
        content = msg.get("content", "")
        if isinstance(content, str):
            return content.strip()
    return ""


class APIClient:
    def __init__(self, api_key: str, base_url: str, model: str, temperature: float, max_output_tokens: int) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens

    def call(self, system_prompt: str, user_prompt: str, retries: int = 5) -> str:
        url = f"{self.base_url}/responses"
        body = {
            "model": self.model,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
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
                with urllib.request.urlopen(req, timeout=180) as resp:
                    raw = resp.read().decode("utf-8")
                payload = json.loads(raw)
                out = extract_output_text(payload)
                if out:
                    return out
                raise RuntimeError("API response contains no text output.")
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as e:
                last_err = e
                if attempt >= retries:
                    break
                sleep_sec = min(20, 1.8 ** attempt)
                time.sleep(sleep_sec)

        raise RuntimeError(f"API call failed after {retries} retries: {last_err}")


SYSTEM_PROMPT = """너는 한국어 명리학/사주 강의 요약 전문가다.
목표는 원문의 핵심 개념, 구조, 시험 포인트를 정확하고 실용적으로 정리하는 것이다.
규칙:
1) 원문에 없는 사실을 추가하지 않는다.
2) 애매하면 단정하지 말고 '강의에서 강조됨' 같은 중립 표현을 사용한다.
3) 용어는 원문 표현(예: 음양, 오행, 생극제화, 십성, 비견, 관성, 재성)을 우선한다.
4) 군더더기 표현 없이 명확한 학습용 문장으로 작성한다.
5) 출력은 반드시 한국어로 작성한다."""


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

[용어 사전 힌트]
{glossary_text}

[지시]
아래는 강의 원문의 일부 조각({chunk_idx}/{chunk_total})이다.
학습 관점에서 중요한 내용만 압축 정리하라.

출력 형식(정확히 유지):
### 핵심 주제
- ...

### 핵심 개념
- 개념: 설명

### 시험 포인트
- ...

### 혼동 주의
- ...

[원문 조각]
{chunk_text}
"""


def make_merge_prompt(group_notes: list[str], group_idx: int, total_groups: int) -> str:
    joined = "\n\n---\n\n".join(group_notes)
    return f"""[지시]
아래 노트들은 같은 강의 파일의 부분 요약이다.
중복을 제거하고 핵심만 합쳐 압축 노트로 만들어라.
원문 외 추론은 금지한다.

출력 형식(정확히 유지):
### 통합 핵심 주제
- ...

### 통합 핵심 개념
- 개념: 설명

### 통합 시험 포인트
- ...

### 통합 혼동 주의
- ...

[현재 병합 그룹]
{group_idx}/{total_groups}

[입력 노트]
{joined}
"""


def make_final_prompt(file_name: str, merged_notes: list[str], glossary: list[str]) -> str:
    notes_text = "\n\n====\n\n".join(merged_notes)
    glossary_text = ", ".join(glossary) if glossary else "(없음)"
    return f"""[파일]
{file_name}

[용어 사전 힌트]
{glossary_text}

[지시]
아래는 강의 조각 요약 노트들이다.
이를 통합하여 학습자가 바로 공부할 수 있는 최종 요약본을 작성하라.

아래 출력 형식을 정확히 사용하라.

## 🔖 핵심 주제별로 나눠서 정리해줘
전체 내용을 분석하여 주요 주제별로 그룹화해서 정리해 줘.
1. 각 주제를 마크다운 헤더(###)로 구분
2. 주제별 세부 내용은 Bullet points으로 요약

## 📑 시험문제를 만들어줘
가장 중요하게 다뤄진 핵심 개념 5가지를 선정하고, 각 개념에 대해:
1. 예상 문제: 객관식 또는 단답형 문제
2. 정답 및 해설: 핵심 설명

## 📗 꼭 공부해야 할 내용을 알려줘
1. 전체 내용을 관통하는 핵심 키워드를 뽑아 정의
2. 복잡한 개념이나 흐름이 있다면 이해하기 쉽게 단계별로 설명

주의:
- 불필요한 서론/면책 문구 금지.
- 중복 문장 최소화.
- 시험문제는 실제 출제 가능한 수준으로 명확하게 작성.

[입력 노트]
{notes_text}
"""


def recursive_merge_notes(client: APIClient, notes: list[str], limit_chars: int) -> list[str]:
    """If notes are too long, compress in groups recursively."""
    cur = notes
    while sum(len(n) for n in cur) > limit_chars and len(cur) > 1:
        merged: list[str] = []
        group_size = 6
        total_groups = (len(cur) + group_size - 1) // group_size
        for i in range(0, len(cur), group_size):
            group = cur[i : i + group_size]
            prompt = make_merge_prompt(group, i // group_size + 1, total_groups)
            merged_note = client.call(SYSTEM_PROMPT, prompt)
            merged.append(merged_note)
        cur = merged
    return cur


def ensure_header(summary_md: str, stem: str) -> str:
    if summary_md.lstrip().startswith("# "):
        return summary_md.rstrip() + "\n"
    return f"# {stem} 요약\n\n{summary_md.rstrip()}\n"


def summarize_one_file(
    client: APIClient,
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
        prompt = make_chunk_prompt(src.name, idx, len(chunks), chunk, glossary_terms)
        note = client.call(SYSTEM_PROMPT, prompt)
        chunk_notes.append(note)

    merged_notes = recursive_merge_notes(client, chunk_notes, limit_chars=merge_limit_chars)
    final_prompt = make_final_prompt(src.name, merged_notes, glossary_terms)
    final_md = client.call(SYSTEM_PROMPT, final_prompt)
    final_md = ensure_header(final_md, src.stem)

    md_path.parent.mkdir(parents=True, exist_ok=True)
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(final_md, encoding="utf-8")
    txt_path.write_text(final_md, encoding="utf-8")
    return True, f"[DONE] {rel} (chunks={len(chunks)})"


def main() -> int:
    args = parse_args()
    input_root = Path(args.input_root)
    if not input_root.exists():
        print(f"[ERROR] input root not found: {input_root}")
        return 1

    api_key = args.api_key or __import__("os").environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("[ERROR] API key is missing. Set OPENAI_API_KEY or pass --api-key.")
        return 1

    output_base = Path(args.output_root) / args.agent_name
    md_root = output_base / "md"
    txt_root = output_base / "txt"

    files = sorted(input_root.rglob("*.txt"))
    if args.max_files > 0:
        files = files[: args.max_files]
    if not files:
        print(f"[ERROR] no input txt files under: {input_root}")
        return 1

    terms = load_terms(Path(args.terms_path))

    client = APIClient(
        api_key=api_key,
        base_url=args.base_url,
        model=args.model,
        temperature=args.temperature,
        max_output_tokens=args.max_output_tokens,
    )

    done = 0
    skipped = 0
    failed = 0

    for idx, src in enumerate(files, start=1):
        rel = src.relative_to(input_root)
        text = src.read_text(encoding="utf-8")
        glossary = terms_in_text(text, terms, limit=60)
        try:
            wrote, msg = summarize_one_file(
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
