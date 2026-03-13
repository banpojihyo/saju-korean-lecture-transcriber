#!/usr/bin/env python3
"""Run Daglo correction with merged common/topic dictionaries."""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

from daglo_corrector import (
    FILE_OVERRIDES_FILENAME,
    TERM_STOPWORDS_FILENAME,
    load_file_overrides,
    load_stopwords,
    merge_file_overrides,
    merge_stopwords,
    write_file_overrides,
    write_stopwords,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Merge dict/common + dict/topics/<topic> and run correct_daglo_file.py "
            "with the merged dictionary."
        )
    )
    parser.add_argument(
        "--source-file",
        action="append",
        required=True,
        help="Path to a Daglo txt file. Repeat this option for multiple files.",
    )
    parser.add_argument(
        "--topic",
        required=True,
        help="Topic name under dict/topics (for example: network, security, math).",
    )
    parser.add_argument(
        "--dict-root",
        default="dict",
        help="Dictionary root path (default: ./dict).",
    )
    parser.add_argument(
        "--common-dir",
        default="",
        help="Override common dictionary dir. Default: <dict-root>/common",
    )
    parser.add_argument(
        "--topic-dir",
        default="",
        help="Override topic dictionary dir. Default: <dict-root>/topics/<topic>",
    )
    parser.add_argument(
        "--input-root",
        default="data/daglo/raw",
        help="Input root forwarded to correct_daglo_file.py.",
    )
    parser.add_argument(
        "--output-root",
        default="data/daglo/corr",
        help="Output root forwarded to correct_daglo_file.py.",
    )
    parser.add_argument(
        "--no-update-dict",
        action="store_true",
        help="Pass --no-update-dict to correct_daglo_file.py.",
    )
    parser.add_argument(
        "--no-persist-topic-update",
        action="store_true",
        help=(
            "Do not write new dictionary entries from merged run back to "
            "the topic dictionary."
        ),
    )
    return parser.parse_args()


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


def load_replace_pairs(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        return []
    pairs: list[tuple[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            wrong = (row.get("wrong") or "").strip()
            right = (row.get("right") or "").strip()
            if wrong and right and wrong != right:
                pairs.append((wrong, right))
    return pairs


def write_replace_pairs(path: Path, pairs: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["wrong", "right"])
        for wrong, right in pairs:
            writer.writerow([wrong, right])


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


def write_terms(path: Path, terms: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["term"])
        for term in terms:
            writer.writerow([term])


def merge_replace_pairs(
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


def run_one_file(
    source_file: Path,
    correct_script: Path,
    common_dir: Path,
    topic_dir: Path,
    input_root: str,
    output_root: str,
    no_update_dict: bool,
    persist_topic_update: bool,
) -> int:
    ensure_dict_files(common_dir)
    ensure_dict_files(topic_dir)

    common_replace = load_replace_pairs(common_dir / "replace.csv")
    common_terms = load_terms(common_dir / "terms.csv")
    common_file_overrides = load_file_overrides(common_dir / FILE_OVERRIDES_FILENAME)
    common_stopwords = load_stopwords(common_dir / TERM_STOPWORDS_FILENAME)
    topic_replace = load_replace_pairs(topic_dir / "replace.csv")
    topic_terms = load_terms(topic_dir / "terms.csv")
    topic_file_overrides = load_file_overrides(topic_dir / FILE_OVERRIDES_FILENAME)
    topic_stopwords = load_stopwords(topic_dir / TERM_STOPWORDS_FILENAME)

    merged_replace = merge_replace_pairs(common_replace, topic_replace)
    merged_terms = merge_terms(common_terms, topic_terms)
    merged_file_overrides = merge_file_overrides(common_file_overrides, topic_file_overrides)
    merged_stopwords = merge_stopwords(common_stopwords, topic_stopwords)

    with tempfile.TemporaryDirectory(prefix="daglo-merged-dict-") as temp_dir:
        temp_dict = Path(temp_dir)
        write_replace_pairs(temp_dict / "replace.csv", merged_replace)
        write_terms(temp_dict / "terms.csv", merged_terms)
        write_file_overrides(temp_dict / FILE_OVERRIDES_FILENAME, merged_file_overrides)
        write_stopwords(temp_dict / TERM_STOPWORDS_FILENAME, merged_stopwords)

        cmd = [
            sys.executable,
            str(correct_script),
            "--source-file",
            str(source_file),
            "--dict-dir",
            str(temp_dict),
            "--topic-name",
            topic_dir.name,
            "--input-root",
            input_root,
            "--output-root",
            output_root,
        ]
        if no_update_dict:
            cmd.append("--no-update-dict")

        result = subprocess.run(cmd)
        if result.returncode != 0:
            return result.returncode

        if no_update_dict or not persist_topic_update:
            return 0

        updated_replace = load_replace_pairs(temp_dict / "replace.csv")
        updated_terms = load_terms(temp_dict / "terms.csv")
        new_replace = added_replace_pairs(merged_replace, updated_replace)
        new_terms = added_terms(merged_terms, updated_terms)

        if new_replace:
            write_replace_pairs(
                topic_dir / "replace.csv",
                merge_replace_pairs(topic_replace, new_replace),
            )
        if new_terms:
            write_terms(topic_dir / "terms.csv", merge_terms(topic_terms, new_terms))

        print(
            f"[DONE] topic dict updated: {topic_dir} "
            f"(replace +{len(new_replace)}, terms +{len(new_terms)})"
        )
        return 0


def main() -> int:
    args = parse_args()
    dict_root = Path(args.dict_root)
    common_dir = Path(args.common_dir) if args.common_dir else (dict_root / "common")
    topic_dir = (
        Path(args.topic_dir)
        if args.topic_dir
        else (dict_root / "topics" / args.topic)
    )

    correct_script = Path(__file__).with_name("correct_daglo_file.py")
    if not correct_script.exists():
        print(f"[ERROR] missing script: {correct_script}")
        return 1

    sources = [Path(x) for x in args.source_file]
    for source in sources:
        if not source.exists():
            print(f"[ERROR] source file not found: {source}")
            return 1

        print(f"[RUN] source={source} topic={args.topic}")
        code = run_one_file(
            source_file=source,
            correct_script=correct_script,
            common_dir=common_dir,
            topic_dir=topic_dir,
            input_root=args.input_root,
            output_root=args.output_root,
            no_update_dict=args.no_update_dict,
            persist_topic_update=not args.no_persist_topic_update,
        )
        if code != 0:
            return code

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
