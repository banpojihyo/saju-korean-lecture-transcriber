#!/usr/bin/env python3
"""Create a corrected Daglo transcript copy in a separate folder.

This applies:
1) dict/common/replace.csv base replacements
2) high-confidence manual replacements for common ASR mistakes
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


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


FILE_OVERRIDES_FILENAME = "file_overrides.jsonl"
TERM_STOPWORDS_FILENAME = "term_stopwords.txt"
AUTO_REPLACE_PAIR_RE = re.compile(r"^[가-힣A-Za-z0-9]+(?: [가-힣A-Za-z0-9]+)?$")
HANGUL_TOKEN_RE = re.compile(r"[가-힣]+$")
EXPANDED_REPLACE_PAIR_TO_BASE: dict[tuple[str, str], tuple[str, str]] = {}


@dataclass(frozen=True)
class FileOverrideRule:
    path: str
    wrong: str
    right: str
    note: str = ""

    def matches(self, relative_path: str) -> bool:
        return fnmatch.fnmatch(relative_path, self.path)


def normalize_relative_path(path: Path) -> str:
    return path.as_posix()


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


def jongseong_index(text: str) -> int:
    if not text:
        return 0
    char = text[-1]
    if not ("가" <= char <= "힣"):
        return 0
    return (ord(char) - ord("가")) % 28


def has_batchim(text: str) -> bool:
    return jongseong_index(text) != 0


def has_rieul_batchim(text: str) -> bool:
    return jongseong_index(text) == 8


def pick_particle_suffix(
    stem: str,
    with_batchim: str,
    without_batchim: str,
    rieul_suffix: str | None = None,
) -> str:
    if has_rieul_batchim(stem) and rieul_suffix is not None:
        return rieul_suffix
    if has_batchim(stem):
        return with_batchim
    return without_batchim


PARTICLE_EXPANSION_SPECS: tuple[tuple[str, Callable[[str], str]], ...] = (
    ("은/는", lambda stem: pick_particle_suffix(stem, "은", "는")),
    ("이/가", lambda stem: pick_particle_suffix(stem, "이", "가")),
    ("을/를", lambda stem: pick_particle_suffix(stem, "을", "를")),
    ("과/와", lambda stem: pick_particle_suffix(stem, "과", "와")),
    ("으로/로", lambda stem: pick_particle_suffix(stem, "으로", "로", rieul_suffix="로")),
    ("의", lambda stem: "의"),
    ("에", lambda stem: "에"),
    ("도", lambda stem: "도"),
    ("고", lambda stem: "고"),
    ("만", lambda stem: "만"),
    ("한테", lambda stem: "한테"),
    ("이나/나", lambda stem: pick_particle_suffix(stem, "이나", "나")),
    ("이에요/예요", lambda stem: pick_particle_suffix(stem, "이에요", "예요")),
    ("이죠/죠", lambda stem: pick_particle_suffix(stem, "이죠", "죠")),
    ("이니까/니까", lambda stem: pick_particle_suffix(stem, "이니까", "니까")),
    ("이잖아요/잖아요", lambda stem: pick_particle_suffix(stem, "이잖아요", "잖아요")),
    ("이면/면", lambda stem: pick_particle_suffix(stem, "이면", "면")),
    ("이면은/면은", lambda stem: pick_particle_suffix(stem, "이면은", "면은")),
    ("이라고요/라고요", lambda stem: pick_particle_suffix(stem, "이라고요", "라고요")),
    ("이라든지/라든지", lambda stem: pick_particle_suffix(stem, "이라든지", "라든지")),
    ("이든지/든지", lambda stem: pick_particle_suffix(stem, "이든지", "든지")),
)


def is_expandable_replace_stem(text: str) -> bool:
    return bool(HANGUL_TOKEN_RE.fullmatch(text)) and len(text) >= 2


def looks_like_particle_variant(wrong: str, right: str) -> bool:
    for _, selector in PARTICLE_EXPANSION_SPECS:
        for wrong_cut in range(2, len(wrong)):
            wrong_stem = wrong[:wrong_cut]
            wrong_suffix = wrong[wrong_cut:]
            if wrong_suffix != selector(wrong_stem):
                continue
            for right_cut in range(2, len(right)):
                right_stem = right[:right_cut]
                right_suffix = right[right_cut:]
                if right_suffix == selector(right_stem):
                    return True
    return False


def expand_replace_pairs_with_particles(
    base_pairs: list[tuple[str, str]]
) -> list[tuple[str, str]]:
    EXPANDED_REPLACE_PAIR_TO_BASE.clear()

    expanded: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for wrong, right in base_pairs:
        base_pair = (wrong, right)
        if base_pair not in seen:
            seen.add(base_pair)
            expanded.append(base_pair)
        EXPANDED_REPLACE_PAIR_TO_BASE[base_pair] = base_pair

        if not is_expandable_replace_stem(wrong) or not is_expandable_replace_stem(right):
            continue
        if looks_like_particle_variant(wrong, right):
            continue

        for _, selector in PARTICLE_EXPANSION_SPECS:
            expanded_pair = (wrong + selector(wrong), right + selector(right))
            if expanded_pair in seen:
                continue
            seen.add(expanded_pair)
            expanded.append(expanded_pair)
            EXPANDED_REPLACE_PAIR_TO_BASE[expanded_pair] = base_pair

    return expanded


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
        for override in overrides:
            payload = {
                "path": override.path,
                "wrong": override.wrong,
                "right": override.right,
            }
            if override.note:
                payload["note"] = override.note
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_terms(path: Path, terms: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["term"])
        for term in terms:
            writer.writerow([term])


def write_stopwords(path: Path, stopwords: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = sorted(stopwords)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        if lines:
            f.write("\n".join(lines) + "\n")


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


def merge_replace_pairs(
    existing: list[tuple[str, str]], applied: list[tuple[str, str, int]]
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    merged = existing.copy()
    seen = set(existing)
    added: list[tuple[str, str]] = []
    for wrong, right, _ in applied:
        wrong, right = EXPANDED_REPLACE_PAIR_TO_BASE.get((wrong, right), (wrong, right))
        if not is_auto_dict_replace_candidate(wrong, right):
            continue
        pair = (wrong, right)
        if pair in seen:
            continue
        seen.add(pair)
        merged.append(pair)
        added.append(pair)
    return merged, added


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


KOREAN_RE = re.compile(r"[가-힣]")
TRAILING_SUFFIXES = (
    "으로는",
    "로는",
    "이라면",
    "라면",
    "다면은",
    "다면",
    "에는",
    "에서",
    "으로",
    "하다",
    "했다",
    "하는",
    "하게",
    "하며",
    "하면",
    "하죠",
    "해요",
    "입니다",
    "이다",
    "라고",
    "하고",
    "이며",
    "에게",
    "부터",
    "까지",
    "처럼",
    "다",
    "께서",
    "께",
    "의",
    "를",
    "을",
    "은",
    "는",
    "이",
    "가",
    "에",
    "도",
    "만",
    "와",
    "과",
)

REJECT_ENDINGS = (
    "다면",
    "한다",
    "했다",
    "해요",
    "하고",
    "가면",
    "해질",
    "하는",
    "한",
)

GAPMOK_AMBIGUOUS_PAIRS = (
    ("감묵", "갑목"),
    ("감묵은", "갑목은"),
    ("감묵의", "갑목의"),
    ("감묵이", "갑목이"),
    ("감묵에", "갑목에"),
    ("감묵한테", "갑목한테"),
    ("감묵이나", "갑목이나"),
    ("감묵이라든지", "갑목이라든지"),
    ("감묵이에요", "갑목이에요"),
    ("감묵이든지", "갑목이든지"),
    ("감묵이니까", "갑목이니까"),
    ("감묵이잖아요", "갑목이잖아요"),
    ("감묵이면", "갑목이면"),
    ("감묵이죠", "갑목이죠"),
    ("관묵", "갑목"),
    ("관묵은", "갑목은"),
    ("관묵의", "갑목의"),
    ("관묵이", "갑목이"),
    ("관묵에", "갑목에"),
    ("관묵한테", "갑목한테"),
    ("관묵이나", "갑목이나"),
    ("관묵이라든지", "갑목이라든지"),
    ("관묵이에요", "갑목이에요"),
    ("관묵이든지", "갑목이든지"),
    ("관묵이니까", "갑목이니까"),
    ("관묵이잖아요", "갑목이잖아요"),
    ("관묵이면", "갑목이면"),
    ("관묵이죠", "갑목이죠"),
)

GEUK_AMBIGUOUS_PAIRS = (
    ("토국수", "토극수"),
    ("토국수는", "토극수는"),
    ("토국수의", "토극수의"),
    ("토국수가", "토극수가"),
    ("토국수에", "토극수에"),
    ("토국수로", "토극수로"),
    ("토국수도", "토극수도"),
    ("토국수고", "토극수고"),
    ("토국수면", "토극수면"),
    ("토국수죠", "토극수죠"),
    ("토국수예요", "토극수예요"),
    ("목국토", "목극토"),
    ("목국토는", "목극토는"),
    ("목국토의", "목극토의"),
    ("목국토가", "목극토가"),
    ("목국토에", "목극토에"),
    ("목국토로", "목극토로"),
    ("목국토도", "목극토도"),
    ("목국토고", "목극토고"),
    ("목국토면", "목극토면"),
    ("목국토죠", "목극토죠"),
    ("목국토예요", "목극토예요"),
)

SINGEUM_AMBIGUOUS_PAIRS = (
    ("심금", "신금"),
    ("심금은", "신금은"),
    ("심금의", "신금의"),
    ("심금이", "신금이"),
    ("심금에", "신금에"),
    ("심금한테", "신금한테"),
    ("심금이나", "신금이나"),
    ("심금이라든지", "신금이라든지"),
    ("심금이에요", "신금이에요"),
    ("심금이든지", "신금이든지"),
    ("심금이니까", "신금이니까"),
    ("심금이잖아요", "신금이잖아요"),
    ("심금이면", "신금이면"),
    ("심금이죠", "신금이죠"),
    ("심금을", "신금을"),
    ("심금상관", "신금상관"),
)

GITO_AMBIGUOUS_PAIRS = (
    ("기포", "기토"),
    ("기포가", "기토가"),
    ("기포는", "기토는"),
    ("기포의", "기토의"),
    ("기포에", "기토에"),
    ("기포로", "기토로"),
    ("기포도", "기토도"),
    ("기포고", "기토고"),
    ("기포를", "기토를"),
    ("기포면", "기토면"),
    ("기포면은", "기토면은"),
    ("기포라고요", "기토라고요"),
)

GYESU_AMBIGUOUS_PAIRS = (
    ("배수", "계수"),
    ("배수가", "계수가"),
    ("배수는", "계수는"),
    ("배수의", "계수의"),
    ("배수에", "계수에"),
    ("배수로", "계수로"),
    ("배수도", "계수도"),
    ("배수고", "계수고"),
    ("배수를", "계수를"),
)

MOK_MISRECOGNITION_PAIRS = (
    ("생무기", "생목이"),
    ("사무기", "사목이"),
    ("생모기", "생목이"),
    ("사모기", "사목이"),
    ("수생무기", "수생목이"),
    ("수생모기", "수생목이"),
    ("관무기", "갑목이"),
)

SAJU_RAW_PRIORITY_PAIRS = frozenset(
    (
        *GITO_AMBIGUOUS_PAIRS,
        *GYESU_AMBIGUOUS_PAIRS,
        *MOK_MISRECOGNITION_PAIRS,
        ("배수 기포를 만나면은", "계수를 만나면은"),
        ("계수 배수가 붙는 순간", "계수가 붙는 순간"),
        ("배수가 가장 음해요.", "계수가 가장 음해요."),
        ("배수로 축축하게 적셔야 되나?", "계수로 축축하게 적셔야 되나?"),
        ("배수로 연결되면은", "계수로 연결되면은"),
        ("배수의 가치가 제대로 발현되는 거죠.", "계수의 가치가 제대로 발현되는 거죠."),
        ("관무기, 사무기라는 것은", "갑목이 사목이라는 것은"),
        ("그게 수생무기라고요.", "그게 수생목이라고요."),
        ("요수생무기라고요.", "요 수생목이라고요."),
        ("수생무기라고요.", "수생목이라고요."),
        ("수생무기라고 할 때", "수생목이라고 할 때"),
        ("수생모기 기준이니까.", "수생목이 기준이니까."),
        ("수생모기지는", "수생목이지는"),
        ("수생모기 저", "수생목이 저"),
        ("생무기 빛을 본 것은", "생목이 빛을 본 것은"),
        ("생모기 풀어서 쓰려면", "생목이 풀어서 쓰려면"),
        ("이 모기 생모기면", "이 목이 생목이면"),
        (
            "사모기 빛을 보는 것과 생모기 빛을 보는 거의 작용이 달라지겠죠.",
            "사목이 빛을 보는 것과 생목이 빛을 보는 것의 작용이 달라지겠죠.",
        ),
    )
)

PAIR_CONTEXT_RULES: dict[tuple[str, str], dict[str, tuple[str, ...]]] = {
    # Ambiguous in general Korean; apply only with 사주 맥락.
    ("귀신", "기신"): {
        "include": (
            "사주",
            "사조",
            "초년",
            "월",
            "연",
            "대운",
            "일지",
            "월지",
            "연지",
            "용신",
            "희신",
            "기신",
            "십성",
            "관살",
            "재성",
            "인성",
            "비겁",
            "식상",
        ),
        "exclude": ("천지", "유령", "강시", "드라큐라", "소복", "무섭", "안 보"),
    },
    # Keep historical/military usage when context points to it.
    ("무반", "무관"): {
        "include": ("관살", "관성", "직업", "관직", "상관", "정관"),
        "exclude": ("문관", "무과", "경복궁", "창경궁", "궁궐"),
    },
    # Building-floor context only.
    ("고친", "고층"): {
        "include": ("지하", "반지하", "고층", "저층", "중층", "아파트", "건물"),
        "exclude": ("고친다", "고친 게", "고친 걸", "고친 후"),
    },
}

for pair in GAPMOK_AMBIGUOUS_PAIRS:
    PAIR_CONTEXT_RULES[pair] = {
        "include": (
            "사주",
            "오행",
            "일간",
            "월간",
            "연간",
            "시간",
            "일지",
            "월지",
            "연지",
            "시지",
            "천간",
            "지지",
            "목",
            "화",
            "토",
            "금",
            "수",
            "갑목",
            "을목",
            "인목",
            "묘목",
            "목생화",
            "수생목",
            "목극토",
            "생극제화",
            "비견",
            "겁재",
            "식신",
            "상관",
            "정재",
            "편재",
            "정관",
            "편관",
            "정인",
            "편인",
        ),
        "exclude": ("침묵", "과묵", "묵언", "묵직", "묵묵"),
    }

for pair in GEUK_AMBIGUOUS_PAIRS:
    PAIR_CONTEXT_RULES[pair] = {
        "include": (
            "사주",
            "오행",
            "일간",
            "월간",
            "연간",
            "시간",
            "일지",
            "월지",
            "연지",
            "시지",
            "목",
            "화",
            "토",
            "금",
            "수",
            "생극제화",
            "상극",
            "목극토",
            "토극수",
            "금극목",
            "수극화",
            "화극금",
            "천간",
            "지지",
            "십성",
        ),
        "exclude": ("잔치국수", "비빔국수", "국수집", "국토부", "전국"),
    }

for pair in SINGEUM_AMBIGUOUS_PAIRS:
    PAIR_CONTEXT_RULES[pair] = {
        "include": (
            "사주",
            "오행",
            "일간",
            "월간",
            "연간",
            "시간",
            "일지",
            "월지",
            "연지",
            "시지",
            "천간",
            "지지",
            "금",
            "수",
            "화",
            "토",
            "경금",
            "신금",
            "유금",
            "금생수",
            "토생금",
            "정재",
            "편재",
            "정관",
            "편관",
            "정인",
            "편인",
            "비견",
            "겁재",
            "식신",
            "상관",
            "십성",
        ),
        "exclude": ("울리", "울렸", "울리는", "심금을 울", "가슴", "마음", "노래", "시구", "문장"),
    }

for pair in GITO_AMBIGUOUS_PAIRS:
    PAIR_CONTEXT_RULES[pair] = {
        "include": (
            "사주",
            "오행",
            "일간",
            "월간",
            "연간",
            "시간",
            "일지",
            "월지",
            "연지",
            "시지",
            "천간",
            "지지",
            "기토",
            "무토",
            "임수",
            "계수",
            "갑목",
            "을목",
            "병화",
            "정화",
            "목",
            "화",
            "토",
            "금",
            "수",
            "토극수",
            "생목화",
            "탁임",
            "동류",
            "운",
            "관",
        ),
        "exclude": ("거품", "비누", "기포제", "탄산", "산소", "포말", "공기방울", "발포"),
    }

for pair in GYESU_AMBIGUOUS_PAIRS:
    PAIR_CONTEXT_RULES[pair] = {
        "include": (
            "사주",
            "오행",
            "일간",
            "월간",
            "연간",
            "시간",
            "일지",
            "월지",
            "연지",
            "시지",
            "천간",
            "지지",
            "계수",
            "임수",
            "갑목",
            "을목",
            "병화",
            "정화",
            "기토",
            "무토",
            "토극수",
            "생목화",
            "조호",
            "한난조습",
            "운",
        ),
        "exclude": ("배수로", "배수구", "배수관", "배수펌프", "배수시설", "배수층", "배수판", "배수구멍"),
    }

DOMAIN_CONTEXT_KEYWORDS = (
    "사주",
    "오행",
    "음양",
    "천간",
    "지지",
    "십성",
    "육친",
    "한난조습",
    "생극제화",
    "왕쇠강약",
    "일간",
    "월간",
    "연간",
    "일지",
    "월지",
    "연지",
    "대운",
    "세운",
    "용신",
    "희신",
    "기신",
    "관살",
    "관성",
    "재성",
    "인성",
    "비겁",
    "식상",
    "비견",
    "겁재",
    "식신",
    "상관",
    "편재",
    "정재",
    "편관",
    "정관",
    "편인",
    "정인",
    "갑목",
    "을목",
    "병화",
    "정화",
    "무토",
    "기토",
    "경금",
    "신금",
    "임수",
    "계수",
)

WORD_CHAR_RE = re.compile(r"[가-힣A-Za-z0-9]")
GEUK_COMPOUND_RE = re.compile(r"([목화토금수])[국곡]([목화토금수])")

SAJU_REGEX_REPLACEMENTS: tuple[
    tuple[re.Pattern[str], str, str, str], ...
] = (
    # Keep "한 무기" family fixes at token boundaries so adjective+noun phrases
    # like "굉장한 무기" do not collapse into "굉장한목이".
    (re.compile(r"(?<![가-힣A-Za-z0-9])한\s*[무모]기"), "한목이", "한 무기", "한목이"),
    (re.compile(r"(?<![가-힣A-Za-z0-9])한\s*목이"), "한목이", "한 목이", "한목이"),
    (re.compile(r"(?<![가-힣A-Za-z0-9])한\s*목에"), "한목에", "한 목에", "한목에"),
    (re.compile(r"(?<![가-힣A-Za-z0-9])한묵"), "한목", "한묵", "한목"),
    (re.compile(r"감묵"), "갑목", "감묵", "갑목"),
    (re.compile(r"관묵"), "갑목", "관묵", "갑목"),
    (re.compile(r"([갑을])묵"), r"\1목", "갑묵/을묵", "갑목/을목"),
    (re.compile(r"묵생([화토금수목])"), r"목생\1", "묵생*", "목생*"),
    (re.compile(r"([수금화토])생묵"), r"\1생목", "생묵*", "생목*"),
    (re.compile(r"묵[국곡극]([화토금수목])"), r"목극\1", "묵극*", "목극*"),
    (
        re.compile(
            r"심금(?=(?:은|는|의|이|가|에|을|를|도|만|과|와|로|으로|보다|처럼|같이|같은|하고|에서|한테|이나|이라든지|이에요|이든지|이니까|이잖아요|이면|이죠|입장에서|기준으로|기준에서|상대로|자체|생을|작용|역할|비견|겁재|식신|상관|편재|정재|편관|정관|편인|정인))"
        ),
        "신금",
        "심금+조사/용어",
        "신금+조사/용어",
    ),
    (
        re.compile(r"(?<![가-힣A-Za-z0-9])심금(?=(?:\s|[,.?!]|$))"),
        "신금",
        "심금",
        "신금",
    ),
    (re.compile(r"천간심금"), "천간신금", "천간심금", "천간신금"),
    (re.compile(r"지지심금"), "지지신금", "지지심금", "지지신금"),
    (
        re.compile(r"심금(?=(?:비견|겁재|식신|상관|편재|정재|편관|정관|편인|정인))"),
        "신금",
        "심금+십성",
        "신금+십성",
    ),
)

CURRENT_DICT_TOPIC = ""
CURRENT_SOURCE_UNDER_SAJU_RAW = False
CURRENT_SOURCE_RELATIVE_PATH = ""
CURRENT_TERM_STOPWORDS: set[str] = set()

FORCE_DOMAIN_REPLACEMENTS = {
    ("항만조습", "한난조습"),
    ("항만조습이에요", "한난조습이에요"),
    ("한란조습", "한난조습"),
    ("한난조섭", "한난조습"),
    ("한난 조수부", "한난 조습"),
    ("생극 재화", "생극제화"),
    ("생극 제화", "생극제화"),
    ("생극재화", "생극제화"),
    ("생극 재화를", "생극제화를"),
    ("생극 제화를", "생극제화를"),
    ("생극재화를", "생극제화를"),
    ("생극, 재화", "생극제화"),
    ("생국제화", "생극제화"),
    ("생급 재화", "생극제화"),
    ("생급재화", "생극제화"),
    ("생급 재화를", "생극제화를"),
    ("생급재화를", "생극제화를"),
    ("생극 재활", "생극제화"),
    ("생극 재활을", "생극제화를"),
    ("생극제화을", "생극제화를"),
    ("생급 재활", "생극제화"),
    ("생급 재활을", "생극제화를"),
    ("오행생극재화", "오행생극제화"),
    ("생각제화", "생극제화"),
    ("공적이다고", "공적이라고"),
    ("유두리", "유도리"),
    ("뉴런지에서", "요런데에서"),
    ("cg", "시지"),
    ("Cg", "시지"),
    ("CG", "시지"),
    ("진술층미", "진술축미"),
    ("모기 개입", "목이 개입"),
}


def is_short_korean_token(text: str) -> bool:
    return bool(text) and len(text) <= 4 and bool(re.fullmatch(r"[가-힣]+", text))


def is_word_boundary(text: str, start: int, end: int) -> bool:
    left_ok = start == 0 or not WORD_CHAR_RE.match(text[start - 1])
    right_ok = end >= len(text) or not WORD_CHAR_RE.match(text[end])
    return left_ok and right_ok


def has_context_keyword(
    text: str, start: int, end: int, keywords: tuple[str, ...], window: int = 120
) -> bool:
    left = max(0, start - window)
    right = min(len(text), end + window)
    snippet = text[left:right]
    return any(keyword in snippet for keyword in keywords)


def should_apply_replacement(
    text: str, start: int, end: int, wrong: str, right: str
) -> bool:
    if (wrong, right) in FORCE_DOMAIN_REPLACEMENTS:
        return True

    if CURRENT_DICT_TOPIC == "saju":
        if CURRENT_SOURCE_UNDER_SAJU_RAW and (wrong, right) in SAJU_RAW_PRIORITY_PAIRS:
            return True
        if (wrong, right) in SAJU_RAW_PRIORITY_PAIRS and not has_context_keyword(
            text, start, end, DOMAIN_CONTEXT_KEYWORDS, window=120
        ):
            return False

    # Ambiguous pairs are always context-gated.
    pair_rule = PAIR_CONTEXT_RULES.get((wrong, right))
    if pair_rule:
        includes = pair_rule.get("include", ())
        excludes = pair_rule.get("exclude", ())
        if excludes and has_context_keyword(text, start, end, excludes, window=120):
            return False
        if includes and not has_context_keyword(text, start, end, includes, window=120):
            return False

    # Short Korean token replacements are risky; require word-boundary + domain context.
    if is_short_korean_token(wrong):
        if not is_word_boundary(text, start, end):
            return False
        if not has_context_keyword(text, start, end, DOMAIN_CONTEXT_KEYWORDS, window=120):
            return False

    return True


def apply_context_aware_replacements(
    text: str, rules: list[tuple[str, str]]
) -> tuple[str, list[tuple[str, str, int]], list[tuple[str, str, int]]]:
    applied: list[tuple[str, str, int]] = []
    skipped: list[tuple[str, str, int]] = []

    for wrong, right in rules:
        if wrong not in text:
            continue

        segments: list[str] = []
        last = 0
        applied_count = 0
        skipped_count = 0

        for match in re.finditer(re.escape(wrong), text):
            start, end = match.span()
            if should_apply_replacement(text, start, end, wrong, right):
                segments.append(text[last:start])
                segments.append(right)
                last = end
                applied_count += 1
            else:
                skipped_count += 1

        if applied_count == 0:
            if skipped_count > 0:
                skipped.append((wrong, right, skipped_count))
            continue

        segments.append(text[last:])
        text = "".join(segments)
        applied.append((wrong, right, applied_count))
        if skipped_count > 0:
            skipped.append((wrong, right, skipped_count))

    return text, applied, skipped


def apply_literal_replacements(
    text: str, rules: list[tuple[str, str]]
) -> tuple[str, list[tuple[str, str, int]]]:
    applied: list[tuple[str, str, int]] = []
    for wrong, right in rules:
        count = text.count(wrong)
        if count == 0:
            continue
        text = text.replace(wrong, right)
        applied.append((wrong, right, count))
    return text, applied


def apply_saju_regex_replacements(text: str) -> tuple[str, list[tuple[str, str, int]]]:
    if CURRENT_DICT_TOPIC != "saju":
        return text, []

    applied_counts: dict[tuple[str, str], int] = {}

    def track_replacement(wrong: str, right: str) -> None:
        key = (wrong, right)
        applied_counts[key] = applied_counts.get(key, 0) + 1

    def replace_geuk_compound(match: re.Match[str]) -> str:
        wrong = match.group(0)
        right = f"{match.group(1)}극{match.group(2)}"
        track_replacement(wrong, right)
        return right

    text = GEUK_COMPOUND_RE.sub(replace_geuk_compound, text)

    for pattern, replacement, wrong_label, right_label in SAJU_REGEX_REPLACEMENTS:
        text, count = pattern.subn(replacement, text)
        if count > 0:
            applied_counts[(wrong_label, right_label)] = (
                applied_counts.get((wrong_label, right_label), 0) + count
            )

    applied = [
        (wrong, right, count) for (wrong, right), count in applied_counts.items() if count > 0
    ]
    applied.sort(key=lambda item: (len(item[0]), item[0]), reverse=True)
    return text, applied


def is_auto_dict_replace_candidate(wrong: str, right: str) -> bool:
    if not wrong or not right or wrong == right:
        return False
    if len(wrong) > 20 or len(right) > 20:
        return False
    if not AUTO_REPLACE_PAIR_RE.fullmatch(wrong):
        return False
    if not AUTO_REPLACE_PAIR_RE.fullmatch(right):
        return False
    return True


def normalize_term_candidate(text: str) -> str:
    candidate = text.strip()
    if candidate in CURRENT_TERM_STOPWORDS:
        return ""
    if " " in candidate:
        return ""
    if not KOREAN_RE.search(candidate):
        return ""
    if candidate.isdigit():
        return ""

    # Peel one grammatical tail when present.
    for suffix in TRAILING_SUFFIXES:
        if candidate.endswith(suffix) and len(candidate) - len(suffix) >= 2:
            candidate = candidate[: -len(suffix)]
            break

    for ending in REJECT_ENDINGS:
        if candidate.endswith(ending):
            return ""

    if candidate in CURRENT_TERM_STOPWORDS:
        return ""
    if len(candidate) < 2 or len(candidate) > 20:
        return ""
    if not KOREAN_RE.search(candidate):
        return ""
    return candidate


def is_term_candidate(text: str) -> bool:
    return bool(normalize_term_candidate(text))


def merge_terms_from_applied(
    existing_terms: list[str], applied: list[tuple[str, str, int]]
) -> tuple[list[str], list[str]]:
    merged = existing_terms.copy()
    seen = set(existing_terms)
    added: list[str] = []
    for _, right, _ in applied:
        normalized = normalize_term_candidate(right)
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        merged.append(normalized)
        added.append(normalized)
    return merged, added


def manual_pairs() -> list[tuple[str, str]]:
    # High-confidence fixes verified against terms usage in this domain.
    return [
        ("이제마 4조", "이제마 사주"),
        ("4조", "사주"),
        ("1주", "일주"),
        ("1조", "일주"),
        ("이정화 선생님", "이제마 선생님"),
        ("이정화 선생", "이제마 선생"),
        ("이자야마 선생", "이제마 선생"),
        ("이자마 선생", "이제마 선생"),
        ("이재명 선생님", "이제마 선생"),
        ("태는 금", "폐는 금"),
        ("푸는 비비", "토는 비위"),
        ("목국도", "목극토"),
        ("복국토다", "목극토다"),
        ("4.3 의학", "사상의학"),
        ("채용", "체용"),
        ("동의 수세보원", "동의수세보원"),
        ("동인수세보원", "동의수세보원"),
        ("그 복을 폐로", "그 목을 폐로"),
        ("관사를", "관살을"),
        ("사조를", "사주를"),
        ("사두에", "사주에"),
        ("귀신", "기신"),
        ("심금 편제", "신금 편재"),
        ("북을 이루어서", "국을 이루어서"),
        ("부관한다면은", "투간한다면은"),
        ("이사경은", "이 사주는"),
        ("수색묵", "수생목"),
        ("수온이라는", "수 운이라는"),
        ("공부한테", "공부할 때"),
        ("무반", "무관"),
        ("신자진 국을 지르고요", "신자진 국을 이루고요"),
        ("금극무", "금극목"),
        ("통정대구", "통정대부"),
        ("통운대구", "통훈대부"),
        ("당삼각", "당상관"),
        ("붕괴가", "품계가"),
        ("감복", "갑목"),
        ("왕세강약", "왕쇠강약"),
        ("새해질", "쇠해질"),
        ("붉어나가면", "불어나가면"),
        ("걸록", "건록"),
        ("쟁제쟁관", "쟁재쟁관"),
        ("술을 봐야", "수를 봐야"),
        ("10점을", "십성을"),
        ("1가능에는", "일간으로는"),
        ("빅업", "비겁"),
        ("상광은", "상관은"),
        ("Millering", "미러링"),
        ("쟤를 양생", "재를 양생"),
        ("음향 오행", "음양 오행"),
        ("음향적으로는", "음양적으로는"),
        ("음영오행", "음양오행"),
        ("지금 음영오행을 했는데요.", "지금 음양오행을 했는데요."),
        ("OEM으로는", "오행으로는"),
        ("OEM으로 얘기하면", "오행으로 얘기하면"),
        ("OEM을 한번", "오행을 한번"),
        ("OEM 불교할 때", "오행 분류할 때"),
        ("광풍 제월", "광풍제월"),
        ("향랑조습", "한난조습"),
        ("항만조습", "한난조습"),
        ("항만조습이에요", "한난조습이에요"),
        ("한난조석", "한난조습"),
        ("한난조섭", "한난조습"),
        ("한남조습", "한난조습"),
        ("한남조사", "한난조습"),
        ("한란교습", "한난조습"),
        ("한난 조수부", "한난 조습"),
        ("한남 조숙", "한난조습"),
        ("왕세강력", "왕쇠강약"),
        ("식신 상관은 다 같이 일관을 빅업의 출력이죠.", "식신 상관은 다 같이 일간을 비겁의 출력이죠."),
        ("그래서 빅업에서 식상으로 진행되는", "그래서 비겁에서 식상으로 진행되는"),
        ("그러니까 빅업을 운용을 잘한다면", "그러니까 비겁을 운용을 잘한다면"),
        ("빅업에 식상이 발현이 잘 되어 있어요.", "비겁에 식상이 발현이 잘 되어 있어요."),
        ("식상으로 빅업을 잘 끌어서 써요.", "식상으로 비겁을 잘 끌어서 써요."),
        ("오늘은 오행의 향랑조습을", "오늘은 오행의 한난조습을"),
        ("시간에는 왕세강력을", "시간에는 왕쇠강약을"),
        ("귀신을 버린다고", "기신을 버린다고"),
        ("귀신을 어떻게 다룰 수 있을까를", "기신을 어떻게 다룰 수 있을까를"),
        ("한남조습으로 보자고요.", "한난조습으로 보자고요."),
        ("음양의 한란교습을", "음양의 한난조습을"),
        ("이 한란교습은", "이 한난조습은"),
        ("요즘에 한남조석으로 궁합을", "요즘에 한난조습으로 궁합을"),
        ("그대로 한남조습의 관계로", "그대로 한난조습의 관계로"),
        ("그 내면에 있는 한남조습을", "그 내면에 있는 한난조습을"),
        ("이런 한난조석과 다 연결돼 있다고", "이런 한난조습과 다 연결돼 있다고"),
        ("지금 이걸 바탕으로 한남조습과", "지금 이걸 바탕으로 한난조습과"),
        ("한남조습을 지난 시간에 할 때", "한난조습을 지난 시간에 할 때"),
        ("한난조석을 이렇게 구분하셔서", "한난조습을 이렇게 구분하셔서"),
        ("처음 우리가 했던 한난조석이", "처음 우리가 했던 한난조습이"),
        ("명을 볼 때 명 전체 기준에서 한난조석 기세의 부분.", "명을 볼 때 명 전체 기준에서 한난조습 기세의 부분."),
        ("오행의 한남조습을 지금 하고 있고요.", "오행의 한난조습을 지금 하고 있고요."),
        ("이런 한남조습에서 이미 형식들이", "이런 한난조습에서 이미 형식들이"),
        ("다음 주에 수대한남조습을 하겠습니다.", "다음 주에 수의 한난조습을 하겠습니다."),
        ("생극 재화", "생극제화"),
        ("생극 제화", "생극제화"),
        ("생극재화", "생극제화"),
        ("생극 재화를", "생극제화를"),
        ("생극 제화를", "생극제화를"),
        ("생극재화를", "생극제화를"),
        ("생극, 재화", "생극제화"),
        ("생국제화", "생극제화"),
        ("생급 재화", "생극제화"),
        ("생급재화", "생극제화"),
        ("생급 재화를", "생극제화를"),
        ("생급재화를", "생극제화를"),
        ("생극 재활", "생극제화"),
        ("생극 재활을", "생극제화를"),
        ("생극제화을", "생극제화를"),
        ("생급 재활", "생극제화"),
        ("생급 재활을", "생극제화를"),
        ("오행생극재화", "오행생극제화"),
        ("생각제화", "생극제화"),
        ("공적이다고", "공적이라고"),
        ("유두리", "유도리"),
        ("뉴런지에서", "요런데에서"),
        ("공관은", "상관은"),
        ("단락해도", "달라고 해도"),
        ("활을 봐야", "화를 봐야"),
        ("모기 개입", "목이 개입"),
        ("한란조습", "한난조습"),
        ("cg", "시지"),
        ("Cg", "시지"),
        ("CG", "시지"),
        ("진술층미", "진술축미"),
        *GAPMOK_AMBIGUOUS_PAIRS,
        *GEUK_AMBIGUOUS_PAIRS,
        *SINGEUM_AMBIGUOUS_PAIRS,
        *GITO_AMBIGUOUS_PAIRS,
        *GYESU_AMBIGUOUS_PAIRS,
        *MOK_MISRECOGNITION_PAIRS,
        ("규정시키는 게 관여예요.", "규정시키는 게 관이에요."),
        ("그게 관여예요.", "그게 관이에요."),
        ("이게 관여예요.", "이게 관이에요."),
        ("조건의 관여예요.", "조건인 거예요."),
        ("고지식한 관여예요.", "고지식한 관이에요."),
        ("기포면은 이게 정관여예요.", "기토면은 이게 정관이에요."),
        ("이게 정관여예요.", "이게 정관이에요."),
        ("상관은 사례 정관여예요.", "상관은 살의 정관이에요."),
        ("이렇게 닥터이면은", "이렇게 박토이면은"),
        ("만약에 속이 차갑 겉이 여래 있는데", "만약에 속이 차갑고 겉에 열이 있는데"),
        # Context-bound fixes: only convert '과목' where it clearly means '갑목'.
        ("이 과목이 자수를 끌어내서 쓰는데", "이 갑목이 자수를 끌어내서 쓰는데"),
        ("이 과목이 이미 사목적 성향의 상징성을 띕니다.", "이 갑목이 이미 사목적 성향의 상징성을 띕니다."),
        ("과목 하나 따로 건드려야 돼.", "갑목 하나 따로 건드려야 돼."),
    ]


# Remove timestamp-only lines (mm:ss / hh:mm:ss) and timestamp+speaker lines.
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


def main() -> int:
    global CURRENT_DICT_TOPIC, CURRENT_SOURCE_RELATIVE_PATH, CURRENT_SOURCE_UNDER_SAJU_RAW, CURRENT_TERM_STOPWORDS

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
        CURRENT_SOURCE_UNDER_SAJU_RAW = is_daglo_raw_root
    except ValueError:
        # Fallback: preserve source filename under output root.
        relative = Path(source.name)
        CURRENT_SOURCE_UNDER_SAJU_RAW = False

    CURRENT_DICT_TOPIC = (args.topic_name or dict_dir.name).lower()
    CURRENT_SOURCE_RELATIVE_PATH = normalize_relative_path(relative)

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
    stopwords_path = dict_dir / TERM_STOPWORDS_FILENAME

    replace_pairs = load_replace_pairs(replace_path)
    runtime_replace_pairs = expand_replace_pairs_with_particles(replace_pairs)
    domain_terms = load_terms(terms_path)
    file_overrides = [
        rule
        for rule in load_file_overrides(file_overrides_path)
        if rule.matches(CURRENT_SOURCE_RELATIVE_PATH)
    ]
    CURRENT_TERM_STOPWORDS = load_stopwords(stopwords_path)
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
    text, regex_applied = apply_saju_regex_replacements(text)
    text, applied, skipped_by_context = apply_context_aware_replacements(text, all_pairs)
    reported_applied = regex_applied + applied

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
            replace_pairs, applied
        )
        merged_terms, added_terms = merge_terms_from_applied(domain_terms, applied)
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
