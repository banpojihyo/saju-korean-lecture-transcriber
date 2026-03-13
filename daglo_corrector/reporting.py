from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path


def current_git_short_hash() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        commit = result.stdout.strip()
        return commit or "working-tree"
    except Exception:
        return "working-tree"


def append_change_report(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = f"[{current_git_short_hash()} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"
    block = "\n".join([header, *lines]).rstrip() + "\n"
    if path.exists():
        existing = path.read_text(encoding="utf-8").rstrip()
        if existing:
            path.write_text(existing + "\n\n" + block, encoding="utf-8")
            return
    path.write_text(block, encoding="utf-8")


TIMESTAMP_LINE_RE = re.compile(
    r"^\s*(?:\d{1,2}:)?\d{1,2}:\d{2}(?:\s*화자\s*\d+)?\s*$"
)


def build_script_only_text(text: str) -> str:
    lines = text.splitlines()
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if TIMESTAMP_LINE_RE.match(stripped):
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
