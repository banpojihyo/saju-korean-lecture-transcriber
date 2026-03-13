from __future__ import annotations

import re
from collections.abc import Callable


HANGUL_TOKEN_RE = re.compile(r"[가-힣]+$")


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
) -> tuple[
    list[tuple[str, str]],
    dict[tuple[str, str], tuple[str, str]],
]:
    expanded_pair_to_base: dict[tuple[str, str], tuple[str, str]] = {}
    expanded: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for wrong, right in base_pairs:
        base_pair = (wrong, right)
        if base_pair not in seen:
            seen.add(base_pair)
            expanded.append(base_pair)
        expanded_pair_to_base.setdefault(base_pair, base_pair)

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
            expanded_pair_to_base.setdefault(expanded_pair, base_pair)

    return expanded, expanded_pair_to_base
