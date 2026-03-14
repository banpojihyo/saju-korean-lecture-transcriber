#!/usr/bin/env python3
"""Create a corrected Daglo transcript copy in a separate folder.

This applies:
1) dict/common/replace.csv base replacements
2) high-confidence manual replacements for common ASR mistakes
"""

from __future__ import annotations

import argparse
from pathlib import Path

from daglo_corrector import (
    FILE_OVERRIDES_FILENAME,
    TERM_STOPWORDS_FILENAME,
    CorrectionContext,
    append_change_report,
    apply_context_aware_replacements,
    apply_literal_replacements,
    apply_saju_regex_replacements,
    apply_saju_stable_normalizations,
    build_script_only_text,
    expand_replace_pairs_with_particles,
    load_file_overrides,
    load_replace_pairs,
    load_stopwords,
    load_terms,
    manual_pairs,
    merge_replace_pairs,
    merge_terms_from_applied,
    write_replace_pairs,
    write_terms,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Correct one Daglo transcript and save into "
            "data/daglo/corr/{corrected,script,changes}."
        )
    )
    parser.add_argument(
        "--source-file",
        required=True,
        help="Path to a Daglo txt file (for example: data/daglo/raw/.../foo.txt).",
    )
    parser.add_argument(
        "--dict-dir",
        default="dict/common",
        help="Directory containing replace.csv and terms.csv (default: ./dict/common).",
    )
    parser.add_argument(
        "--topic-name",
        default="",
        help="Logical topic name used for topic-specific correction rules.",
    )
    parser.add_argument(
        "--input-root",
        default="data/daglo/raw",
        help=(
            "Input root used to preserve relative folder structure "
            "(default: ./data/daglo/raw)."
        ),
    )
    parser.add_argument(
        "--output-root",
        default="data/daglo/corr",
        help=(
            "Output root. Files are written under "
            "{output_root}/corrected, {output_root}/script, {output_root}/changes."
        ),
    )
    parser.add_argument(
        "--no-update-dict",
        action="store_true",
        help="Do not update <dict-dir>/replace.csv and <dict-dir>/terms.csv from applied corrections.",
    )
    return parser.parse_args()


def normalize_relative_path(path: Path) -> str:
    return path.as_posix()


def main() -> int:
    args = parse_args()
    source = Path(args.source_file)
    if not source.exists():
        print(f"[ERROR] source file not found: {source}")
        return 1

    input_root = Path(args.input_root)
    output_root = Path(args.output_root)
    dict_dir = Path(args.dict_dir)

    source_abs = source.resolve()
    input_root_abs = input_root.resolve()
    input_root_parts = tuple(part.lower() for part in input_root_abs.parts)
    daglo_raw_parts = ("data", "daglo", "raw")
    is_daglo_raw_root = input_root_parts[-len(daglo_raw_parts) :] == daglo_raw_parts

    try:
        relative = source_abs.relative_to(input_root_abs)
        source_under_saju_raw = is_daglo_raw_root
    except ValueError:
        # Fallback: preserve source filename under output root.
        relative = Path(source.name)
        source_under_saju_raw = False

    context = CorrectionContext(
        dict_topic=(args.topic_name or dict_dir.name).lower(),
        source_relative_path=normalize_relative_path(relative),
        source_under_saju_raw=source_under_saju_raw,
        term_stopwords=frozenset(load_stopwords(dict_dir / TERM_STOPWORDS_FILENAME)),
    )

    output_path = (
        output_root / "corrected" / relative.parent / f"{source.stem}.corrected{source.suffix}"
    )
    script_path = (
        output_root / "script" / relative.parent / f"{source.stem}.script{source.suffix}"
    )
    report_path = output_root / "changes" / relative.parent / f"{source.stem}.changes.txt"

    text = source.read_text(encoding="utf-8")
    original_text = text

    replace_path = dict_dir / "replace.csv"
    terms_path = dict_dir / "terms.csv"
    file_overrides_path = dict_dir / FILE_OVERRIDES_FILENAME

    replace_pairs = load_replace_pairs(replace_path)
    runtime_replace_pairs, expanded_pair_to_base = expand_replace_pairs_with_particles(
        replace_pairs
    )
    domain_terms = load_terms(terms_path)
    file_overrides = [
        rule
        for rule in load_file_overrides(file_overrides_path)
        if rule.matches(context.source_relative_path)
    ]
    all_pairs_raw = runtime_replace_pairs + manual_pairs()
    all_pairs: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for pair in all_pairs_raw:
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        all_pairs.append(pair)

    # Longer source phrase first to avoid partial overlap issues.
    all_pairs.sort(key=lambda p: len(p[0]), reverse=True)

    file_override_pairs = [(rule.wrong, rule.right) for rule in file_overrides]
    file_override_pairs.sort(key=lambda p: len(p[0]), reverse=True)
    text, file_override_applied = apply_literal_replacements(text, file_override_pairs)
    text, regex_applied = apply_saju_regex_replacements(text, context)
    text, applied, skipped_by_context = apply_context_aware_replacements(
        text,
        all_pairs,
        context,
        expanded_pair_to_base,
    )
    text, stable_normalization_applied = apply_saju_stable_normalizations(text, context)
    reported_applied = regex_applied + applied + stable_normalization_applied

    output_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    script_only_text = build_script_only_text(text)
    script_path.write_text(script_only_text, encoding="utf-8")

    added_replace_pairs: list[tuple[str, str]] = []
    added_terms: list[str] = []
    if not args.no_update_dict:
        merged_replace_pairs, added_replace_pairs = merge_replace_pairs(
            replace_pairs,
            applied,
            expanded_pair_to_base,
        )
        merged_terms, added_terms = merge_terms_from_applied(domain_terms, applied, context)
        if added_replace_pairs:
            write_replace_pairs(replace_path, merged_replace_pairs)
        if added_terms:
            write_terms(terms_path, merged_terms)
        domain_terms_for_count = merged_terms
    else:
        domain_terms_for_count = domain_terms

    corrected_term_hits = sum(1 for term in domain_terms_for_count if term in text)
    script_lines = sum(1 for line in script_only_text.splitlines() if line.strip())
    changed_chars = sum(1 for a, b in zip(original_text, text) if a != b) + abs(
        len(original_text) - len(text)
    )

    lines: list[str] = []
    lines.append(f"source: {source}")
    lines.append(f"output: {output_path}")
    lines.append(f"script_only_output: {script_path}")
    lines.append(f"file_override_rules: {len(file_overrides)}")
    lines.append(
        f"file_override_hits: {sum(count for _, _, count in file_override_applied)}"
    )
    lines.append(f"applied_rules: {len(reported_applied)}")
    lines.append(f"changed_chars: {changed_chars}")
    lines.append(f"term_hits_after_correction: {corrected_term_hits}")
    lines.append(f"script_lines_after_cleanup: {script_lines}")
    lines.append(f"dict_replace_added: {len(added_replace_pairs)}")
    lines.append(f"dict_terms_added: {len(added_terms)}")
    lines.append(f"context_skipped_rules: {len(skipped_by_context)}")
    lines.append(
        f"context_skipped_hits: {sum(count for _, _, count in skipped_by_context)}"
    )
    lines.append("")
    if file_override_applied:
        lines.append("[file overrides applied]")
        for wrong, right, count in file_override_applied:
            lines.append(f"{wrong} -> {right} (x{count})")
        lines.append("")
    lines.append("[applied replacements]")
    for wrong, right, count in reported_applied:
        lines.append(f"{wrong} -> {right} (x{count})")
    if skipped_by_context:
        lines.append("")
        lines.append("[skipped by context]")
        for wrong, right, count in skipped_by_context:
            lines.append(f"{wrong} -> {right} (x{count})")
    if added_replace_pairs:
        lines.append("")
        lines.append("[dict replace added]")
        for wrong, right in added_replace_pairs:
            lines.append(f"{wrong} -> {right}")
    if added_terms:
        lines.append("")
        lines.append("[dict terms added]")
        for term in added_terms:
            lines.append(term)
    append_change_report(report_path, lines)

    print(f"[DONE] source: {source}")
    print(f"[DONE] corrected: {output_path}")
    print(f"[DONE] script-only: {script_path}")
    print(f"[DONE] report: {report_path}")
    print(f"[DONE] file override rules: {len(file_overrides)}")
    print(f"[DONE] file override hits: {sum(count for _, _, count in file_override_applied)}")
    print(f"[DONE] applied rules: {len(applied)}")
    print(f"[DONE] context skipped rules: {len(skipped_by_context)}")
    print(f"[DONE] dict replace added: {len(added_replace_pairs)}")
    print(f"[DONE] dict terms added: {len(added_terms)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
