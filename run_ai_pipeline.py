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
        "Create neutral study material that can be reused across lecture topics. "
        "Organize the result in the order of definition, rationale, and application."
    ),
    "saju": (
        "Prioritize the context of saju and myeongri lectures. "
        "Use terms such as eumyang, ohaeng, cheongan, jiji, yugchin, sibseong, singang-sinyak, and hap-chung-hyeong-pa-hae precisely."
    ),
    "network": (
        "Prioritize the context of network engineering lectures. "
        "Clearly distinguish layers, packet flow, routing, protocol behavior, and performance metrics."
    ),
    "security": (
        "Prioritize the context of information security lectures. "
        "Clearly distinguish threats, vulnerabilities, controls, CIA, authentication, authorization, cryptography, and operational security."
    ),
    "math": (
        "Prioritize the context of mathematics lectures. "
        "Keep definitions, theorems, examples, and applications clearly separated."
    ),
    "philosophy": (
        "Prioritize the context of philosophy lectures. "
        "Focus on conceptual definitions, differences between thinkers, and argument structures."
    ),
    "philosophy_east": (
        "Prioritize the context of East Asian philosophy lectures. "
        "Keep Confucian, Daoist, Buddhist, and Neo-Confucian concepts properly distinguished."
    ),
    "philosophy_west": (
        "Prioritize the context of Western philosophy lectures. "
        "Compare epistemology, metaphysics, ethics, and each thinker's central question."
    ),
    "vocal": (
        "Prioritize the context of vocal training lectures. "
        "Organize breathing, resonance, registration, rhythm, and expression from a practice perspective."
    ),
    "essay": (
        "Prioritize the context of writing and essay lectures. "
        "Focus on prompt analysis, claim-evidence-counterargument structure, and paragraph organization."
    ),
}

STYLE_GUIDE: dict[str, str] = {
    "summary": (
        "Goal: produce a compact study summary for review and exams.\n"
        "Include key topics, key concepts, exam points, and practical cautions."
    ),
    "study-pack": (
        "Goal: produce a study pack a learner can use immediately.\n"
        "Include topic summaries, five exam questions, and a concise study note."
    ),
    "merged": (
        "Goal: combine the strengths of summary and study-pack into one result.\n"
        "Include topic summaries, concept map, exam questions, exam points, practical cautions, and a study note."
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
        default="openai",
        help="AI provider to use (default: openai).",
    )
    parser.add_argument(
        "--style",
        choices=STYLES,
        default="merged",
        help="Output style (default: merged).",
    )
    parser.add_argument(
        "--topic",
        default="saju",
        help="Topic profile used for system prompt and dictionary hints (default: saju).",
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
        default="GPT-5.3-Chat-Latest",
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
        help=(
            "Sampling temperature. Primarily used for Gemini or custom-compatible "
            "providers; official OpenAI runs omit it by default."
        ),
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=5000,
        help="Max output tokens per request.",
    )
    parser.add_argument(
        "--chunk-chars",
        type=int,
        default=6000,
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
        default=3,
        help=(
            "Additional retries for final generation when output looks incomplete. "
            "Default: 3."
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
        return "gpt-5.3-chat-latest"
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
        "You are a specialist who turns lecture transcripts into structured study material.\n"
        "Write the final output in Korean.\n"
        f"Topic guidance: {topic_text}\n"
        f"Output style: {style_text}\n"
        "Rules:\n"
        "1) Do not invent facts that are not supported by the transcript.\n"
        "2) If uncertainty remains, use conditional or neutral wording.\n"
        "3) Output must be clear markdown.\n"
        "4) Follow the requested section titles and structure exactly.\n"
        "5) Do not add filler, meta commentary, or self-reference.\n"
    )


def make_chunk_prompt(
    file_name: str,
    chunk_idx: int,
    chunk_total: int,
    chunk_text: str,
    glossary: list[str],
) -> str:
    glossary_text = ", ".join(glossary) if glossary else "(none)"
    return f"""[FILE]
{file_name}

[GLOSSARY HINTS]
{glossary_text}

[TASK]
This is chunk {chunk_idx}/{chunk_total} from one lecture transcript.
Extract only the essential points for downstream merging.
Write the note in Korean.

[OUTPUT FORMAT]
### Chunk Topics
- ...

### Chunk Concepts
- concept: explanation

### Chunk Exam Points
- ...

### Chunk Practical Cautions
- ...

[TRANSCRIPT]
{chunk_text}
"""


def make_merge_prompt(group_notes: list[str], group_idx: int, total_groups: int) -> str:
    joined = "\n\n---\n\n".join(group_notes)
    return f"""[TASK]
Below are chunk notes from the same source file.
Remove duplication and merge them into one coherent Korean note.

[OUTPUT FORMAT]
### Merged Topics
- ...

### Merged Concepts
- concept: explanation

### Merged Exam Points
- ...

### Merged Practical Cautions
- ...

[GROUP]
{group_idx}/{total_groups}

[INPUT NOTES]
{joined}
"""


def final_template(style: str) -> str:
    if style == "summary":
        return (
            "## \ud575\uc2ec \uc8fc\uc81c\ubcc4 \uc815\ub9ac\n"
            "### \uc8fc\uc81c 1\n"
            "- ...\n"
            "### \uc8fc\uc81c 2\n"
            "- ...\n\n"
            "## \ud575\uc2ec \uac1c\ub150 \ub9f5\n"
            "- \uac1c\ub150: \uc124\uba85\n\n"
            "## \uc2dc\ud5d8 \ud3ec\uc778\ud2b8\n"
            "- ...\n\n"
            "## \uc2e4\uc804 \uc8fc\uc758\uc0ac\ud56d\n"
            "- ..."
        )
    if style == "study-pack":
        return (
            "## \ud575\uc2ec \uc8fc\uc81c\ubcc4 \uc815\ub9ac\n"
            "### \uc8fc\uc81c 1\n"
            "- ...\n"
            "### \uc8fc\uc81c 2\n"
            "- ...\n\n"
            "## \uc608\uc0c1 \uc2dc\ud5d8\ubb38\uc81c\n"
            "### \ud575\uc2ec \uac1c\ub150 1\n"
            "1. \uc608\uc0c1 \ubb38\uc81c: ...\n"
            "2. \uc815\ub2f5 \ubc0f \ud574\uc124: ...\n"
            "### \ud575\uc2ec \uac1c\ub150 2\n"
            "1. \uc608\uc0c1 \ubb38\uc81c: ...\n"
            "2. \uc815\ub2f5 \ubc0f \ud574\uc124: ...\n"
            "### \ud575\uc2ec \uac1c\ub150 3\n"
            "1. \uc608\uc0c1 \ubb38\uc81c: ...\n"
            "2. \uc815\ub2f5 \ubc0f \ud574\uc124: ...\n"
            "### \ud575\uc2ec \uac1c\ub150 4\n"
            "1. \uc608\uc0c1 \ubb38\uc81c: ...\n"
            "2. \uc815\ub2f5 \ubc0f \ud574\uc124: ...\n"
            "### \ud575\uc2ec \uac1c\ub150 5\n"
            "1. \uc608\uc0c1 \ubb38\uc81c: ...\n"
            "2. \uc815\ub2f5 \ubc0f \ud574\uc124: ...\n\n"
            "## \uaf2d \uacf5\ubd80\ud574\uc57c \ud560 \ub0b4\uc6a9\n"
            "### \ud575\uc2ec \ud0a4\uc6cc\ub4dc\uc640 \uc815\uc758\n"
            "- ...\n"
            "### \ub2e8\uacc4\ubcc4 \uc774\ud574\n"
            "1. ...\n"
            "2. ...\n"
            "3. ..."
        )
    return (
        "## \ud575\uc2ec \uc8fc\uc81c\ubcc4 \uc815\ub9ac\n"
        "### \uc8fc\uc81c 1\n"
        "- ...\n"
        "### \uc8fc\uc81c 2\n"
        "- ...\n\n"
        "## \ud575\uc2ec \uac1c\ub150 \ub9f5\n"
        "- \uac1c\ub150: \uc124\uba85\n\n"
        "## \uc608\uc0c1 \uc2dc\ud5d8\ubb38\uc81c\n"
        "### \ud575\uc2ec \uac1c\ub150 1\n"
        "1. \uc608\uc0c1 \ubb38\uc81c: ...\n"
        "2. \uc815\ub2f5 \ubc0f \ud574\uc124: ...\n"
        "### \ud575\uc2ec \uac1c\ub150 2\n"
        "1. \uc608\uc0c1 \ubb38\uc81c: ...\n"
        "2. \uc815\ub2f5 \ubc0f \ud574\uc124: ...\n"
        "### \ud575\uc2ec \uac1c\ub150 3\n"
        "1. \uc608\uc0c1 \ubb38\uc81c: ...\n"
        "2. \uc815\ub2f5 \ubc0f \ud574\uc124: ...\n"
        "### \ud575\uc2ec \uac1c\ub150 4\n"
        "1. \uc608\uc0c1 \ubb38\uc81c: ...\n"
        "2. \uc815\ub2f5 \ubc0f \ud574\uc124: ...\n"
        "### \ud575\uc2ec \uac1c\ub150 5\n"
        "1. \uc608\uc0c1 \ubb38\uc81c: ...\n"
        "2. \uc815\ub2f5 \ubc0f \ud574\uc124: ...\n\n"
        "## \uc2dc\ud5d8 \ud3ec\uc778\ud2b8\uc640 \uc2e4\uc804 \uc8fc\uc758\uc0ac\ud56d\n"
        "### \uc2dc\ud5d8 \ud3ec\uc778\ud2b8\n"
        "- ...\n"
        "### \uc2e4\uc804 \uc8fc\uc758\uc0ac\ud56d\n"
        "- ...\n\n"
        "## \uaf2d \uacf5\ubd80\ud574\uc57c \ud560 \ub0b4\uc6a9\n"
        "### \ud575\uc2ec \ud0a4\uc6cc\ub4dc\uc640 \uc815\uc758\n"
        "- ...\n"
        "### \ub2e8\uacc4\ubcc4 \uc774\ud574\n"
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
    glossary_text = ", ".join(glossary) if glossary else "(none)"
    template = final_template(style)
    return f"""[FILE]
{file_name}

[GLOSSARY HINTS]
{glossary_text}

[TASK]
Write the final output in Korean based on the merged notes below.
The result must be compact, study-friendly markdown.
Do not add file notices, meta comments, or self-reference.
Follow the template exactly.

[TEMPLATE]
{template}

[MERGED NOTES]
{notes_text}
"""


def required_sections(style: str) -> list[str]:
    if style == "summary":
        return [
            "## \ud575\uc2ec \uc8fc\uc81c\ubcc4 \uc815\ub9ac",
            "## \ud575\uc2ec \uac1c\ub150 \ub9f5",
            "## \uc2dc\ud5d8 \ud3ec\uc778\ud2b8",
            "## \uc2e4\uc804 \uc8fc\uc758\uc0ac\ud56d",
        ]
    if style == "study-pack":
        return [
            "## \ud575\uc2ec \uc8fc\uc81c\ubcc4 \uc815\ub9ac",
            "## \uc608\uc0c1 \uc2dc\ud5d8\ubb38\uc81c",
            "## \uaf2d \uacf5\ubd80\ud574\uc57c \ud560 \ub0b4\uc6a9",
        ]
    return [
        "## \ud575\uc2ec \uc8fc\uc81c\ubcc4 \uc815\ub9ac",
        "## \ud575\uc2ec \uac1c\ub150 \ub9f5",
        "## \uc608\uc0c1 \uc2dc\ud5d8\ubb38\uc81c",
        "## \uc2dc\ud5d8 \ud3ec\uc778\ud2b8\uc640 \uc2e4\uc804 \uc8fc\uc758\uc0ac\ud56d",
        "## \uaf2d \uacf5\ubd80\ud574\uc57c \ud560 \ub0b4\uc6a9",
    ]


def looks_incomplete_output(text: str, style: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True

    exact_hits = sum(1 for sec in required_sections(style) if sec in stripped)

    if style == "summary":
        min_sections = 4
        keywords = ("\uc8fc\uc81c", "\uac1c\ub150", "\uc2dc\ud5d8", "\uc8fc\uc758")
    elif style == "study-pack":
        min_sections = 3
        keywords = ("\uc8fc\uc81c", "\uc2dc\ud5d8", "\uacf5\ubd80")
    else:
        min_sections = 5
        keywords = ("\uc8fc\uc81c", "\uac1c\ub150", "\uc2dc\ud5d8", "\uacf5\ubd80")

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
    glossary_text = ", ".join(glossary) if glossary else "(none)"
    template = final_template(style)
    return f"""[FILE]
{file_name}

[GLOSSARY HINTS]
{glossary_text}

[TASK]
The previous output was cut off.
Regenerate the entire final result from start to finish in Korean.
Do not leave missing sections, half-finished headings, or trailing bullets.
If length becomes an issue, keep each bullet concise.

[TEMPLATE]
{template}

[PREVIOUS INCOMPLETE OUTPUT]
{previous_output}

[MERGED NOTES]
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
        "## \ubd80\ubd84 \uacb0\uacfc \uc548\ub0b4",
        f"- \uc0dd\uc131 \uc911\ub2e8 \uc9c0\uc810: `{stage}`",
        "- \uc0ac\uc720: API \uc694\uccad \ud55c\ub3c4 \ucd08\uacfc (429/RESOURCE_EXHAUSTED)",
        "- \uc544\ub798 \ub0b4\uc6a9\uc740 \ud55c\ub3c4 \ucd08\uacfc \uc9c1\uc804\uae4c\uc9c0 \uc0dd\uc131\ub41c \uacb0\uacfc\uc785\ub2c8\ub2e4.",
    ]
    if error_line:
        lines.append(f"- \uc624\ub958 \uc694\uc57d: `{error_line}`")
    lines.append("")

    if result_text.strip():
        lines.append(result_text.strip())
        return "\n".join(lines).strip()

    if merged_notes:
        lines.append("## \ud55c\ub3c4 \ucd08\uacfc \uc804 \ud1b5\ud569 \ub178\ud2b8")
        for idx, note in enumerate(merged_notes, start=1):
            lines.append(f"### \ud1b5\ud569 \ub178\ud2b8 {idx}")
            lines.append(note.strip())
            lines.append("")
        return "\n".join(lines).strip()

    if chunk_notes:
        lines.append("## \ud55c\ub3c4 \ucd08\uacfc \uc804 \uccad\ud06c \uc694\uc57d")
        for idx, note in enumerate(chunk_notes, start=1):
            lines.append(f"### \uccad\ud06c {idx}")
            lines.append(note.strip())
            lines.append("")
        return "\n".join(lines).strip()

    if style == "summary":
        lines.append("## \ud575\uc2ec \uc8fc\uc81c\ubcc4 \uc815\ub9ac")
        lines.append("- (\uc0dd\uc131\ub41c \ub0b4\uc6a9 \uc5c6\uc74c)")
    elif style == "study-pack":
        lines.append("## \ud575\uc2ec \uc8fc\uc81c\ubcc4 \uc815\ub9ac")
        lines.append("- (\uc0dd\uc131\ub41c \ub0b4\uc6a9 \uc5c6\uc74c)")
        lines.append("## \uc608\uc0c1 \uc2dc\ud5d8\ubb38\uc81c")
        lines.append("- (\uc0dd\uc131\ub41c \ub0b4\uc6a9 \uc5c6\uc74c)")
        lines.append("## \uaf2d \uacf5\ubd80\ud574\uc57c \ud560 \ub0b4\uc6a9")
        lines.append("- (\uc0dd\uc131\ub41c \ub0b4\uc6a9 \uc5c6\uc74c)")
    else:
        lines.append("## \ud575\uc2ec \uc8fc\uc81c\ubcc4 \uc815\ub9ac")
        lines.append("- (\uc0dd\uc131\ub41c \ub0b4\uc6a9 \uc5c6\uc74c)")
        lines.append("## \ud575\uc2ec \uac1c\ub150 \ub9f5")
        lines.append("- (\uc0dd\uc131\ub41c \ub0b4\uc6a9 \uc5c6\uc74c)")
        lines.append("## \uc608\uc0c1 \uc2dc\ud5d8\ubb38\uc81c")
        lines.append("- (\uc0dd\uc131\ub41c \ub0b4\uc6a9 \uc5c6\uc74c)")
        lines.append("## \uc2dc\ud5d8 \ud3ec\uc778\ud2b8\uc640 \uc2e4\uc804 \uc8fc\uc758\uc0ac\ud56d")
        lines.append("- (\uc0dd\uc131\ub41c \ub0b4\uc6a9 \uc5c6\uc74c)")
        lines.append("## \uaf2d \uacf5\ubd80\ud574\uc57c \ud560 \ub0b4\uc6a9")
        lines.append("- (\uc0dd\uc131\ub41c \ub0b4\uc6a9 \uc5c6\uc74c)")
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
        self._omit_temperature = self.base_url == "https://api.openai.com/v1"

    def _build_body(
        self,
        system_prompt: str,
        user_prompt: str,
        output_limit: int,
    ) -> dict:
        body = {
            "model": self.model,
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
        if not self._omit_temperature:
            body["temperature"] = self.temperature
        return body

    def call(
        self,
        system_prompt: str,
        user_prompt: str,
        retries: int = 5,
        max_output_tokens: int | None = None,
    ) -> str:
        url = f"{self.base_url}/responses"
        output_limit = max_output_tokens or self.max_output_tokens
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        last_err: Exception | None = None
        for attempt in range(1, retries + 1):
            body = self._build_body(system_prompt, user_prompt, output_limit)
            data = json.dumps(body).encode("utf-8")
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
                if (
                    not self._omit_temperature
                    and e.code == 400
                    and "Unsupported parameter: 'temperature'" in detail
                ):
                    self._omit_temperature = True
                    continue
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
            md_path.write_text(content, encoding="utf-8-sig")
        if should_write_txt:
            txt_path.parent.mkdir(parents=True, exist_ok=True)
            txt_path.write_text(content, encoding="utf-8-sig")

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
