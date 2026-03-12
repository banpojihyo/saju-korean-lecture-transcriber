#!/usr/bin/env python3
"""Helpers for timestamped summary output folder naming."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


TIMESTAMP_RE = re.compile(r"\d{8}-\d{6}")
SUFFIXED_AGENT_RE = re.compile(r"__\d{8}-\d{6}$")


def resolve_run_timestamp(run_timestamp: str = "") -> str:
    stamp = (run_timestamp or "").strip()
    if not stamp:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if not TIMESTAMP_RE.fullmatch(stamp):
        raise ValueError("run timestamp must use YYYYMMDD-HHMMSS format")
    return stamp


def build_agent_dir_name(agent_name: str, run_timestamp: str = "") -> str:
    name = agent_name.strip()
    if not name:
        raise ValueError("agent name must not be empty")
    if SUFFIXED_AGENT_RE.search(name):
        return name
    return f"{name}__{resolve_run_timestamp(run_timestamp)}"


def build_output_base(
    output_root: str | Path,
    topic: str,
    agent_name: str,
    run_timestamp: str = "",
) -> Path:
    return Path(output_root) / topic / build_agent_dir_name(agent_name, run_timestamp)
