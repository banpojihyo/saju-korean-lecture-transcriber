from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import FileOverrideRule


FILE_OVERRIDES_FILENAME = "file_overrides.jsonl"
TERM_STOPWORDS_FILENAME = "term_stopwords.txt"


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


def load_file_overrides(path: Path) -> list[FileOverrideRule]:
    overrides: list[FileOverrideRule] = []
    if not path.exists():
        return overrides

    with path.open("r", encoding="utf-8-sig") as f:
        for line_no, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid JSONL in {path} at line {line_no}: {exc}"
                ) from exc

            path_pattern = str(payload.get("path") or "").strip().replace("\\", "/")
            wrong = str(payload.get("wrong") or "").strip()
            right = str(payload.get("right") or "").strip()
            note = str(payload.get("note") or "").strip()
            if not path_pattern or not wrong or not right or wrong == right:
                continue

            overrides.append(
                FileOverrideRule(
                    path=path_pattern,
                    wrong=wrong,
                    right=right,
                    note=note,
                )
            )
    return overrides


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


def load_stopwords(path: Path) -> set[str]:
    stopwords: set[str] = set()
    if not path.exists():
        return stopwords
    with path.open("r", encoding="utf-8-sig") as f:
        for raw_line in f:
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            stopwords.add(line)
    return stopwords


def ensure_dict_files(dict_dir: Path) -> None:
    dict_dir.mkdir(parents=True, exist_ok=True)
    replace_path = dict_dir / "replace.csv"
    terms_path = dict_dir / "terms.csv"
    file_overrides_path = dict_dir / FILE_OVERRIDES_FILENAME
    stopwords_path = dict_dir / TERM_STOPWORDS_FILENAME
    if not replace_path.exists():
        write_replace_pairs(replace_path, [])
    if not terms_path.exists():
        write_terms(terms_path, [])
    if not file_overrides_path.exists():
        write_file_overrides(file_overrides_path, [])
    if not stopwords_path.exists():
        write_stopwords(stopwords_path, set())


def write_replace_pairs(path: Path, pairs: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["wrong", "right"])
        for wrong, right in pairs:
            writer.writerow([wrong, right])


def write_file_overrides(path: Path, overrides: list[FileOverrideRule]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        for rule in overrides:
            payload = {
                "path": rule.path,
                "wrong": rule.wrong,
                "right": rule.right,
            }
            if rule.note:
                payload["note"] = rule.note
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_terms(path: Path, terms: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["term"])
        for term in terms:
            normalized = term.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            writer.writerow([normalized])


def write_stopwords(path: Path, stopwords: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = sorted(word for word in stopwords if word.strip())
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        if lines:
            f.write("\n".join(lines) + "\n")


def merge_replace_pair_lists(
    first: list[tuple[str, str]], second: list[tuple[str, str]]
) -> list[tuple[str, str]]:
    merged: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for pair in first + second:
        if pair in seen:
            continue
        seen.add(pair)
        merged.append(pair)
    return merged


def merge_terms(first: list[str], second: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for term in first + second:
        if term in seen:
            continue
        seen.add(term)
        merged.append(term)
    return merged


def added_replace_pairs(
    baseline: list[tuple[str, str]], updated: list[tuple[str, str]]
) -> list[tuple[str, str]]:
    base = set(baseline)
    return [pair for pair in updated if pair not in base]


def added_terms(baseline: list[str], updated: list[str]) -> list[str]:
    base = set(baseline)
    return [term for term in updated if term not in base]


def merge_file_overrides(
    existing: list[FileOverrideRule], incoming: list[FileOverrideRule]
) -> list[FileOverrideRule]:
    merged: list[FileOverrideRule] = []
    seen: set[tuple[str, str, str]] = set()
    for rule in existing + incoming:
        key = (rule.path, rule.wrong, rule.right)
        if key in seen:
            continue
        seen.add(key)
        merged.append(rule)
    return merged


def merge_stopwords(first: set[str], second: set[str]) -> set[str]:
    return set(first) | set(second)
