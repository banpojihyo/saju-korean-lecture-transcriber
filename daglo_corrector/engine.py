from __future__ import annotations

import re

from .models import CorrectionContext
from .rules_saju import (
    DOMAIN_CONTEXT_KEYWORDS,
    FORCE_DOMAIN_REPLACEMENTS,
    GEUK_COMPOUND_RE,
    KOREAN_RE,
    PAIR_CONTEXT_RULES,
    REJECT_ENDINGS,
    SAJU_CONTEXT_REGEX_RULES,
    SAJU_FAMILY_REPLACEMENT_RULES,
    SAJU_RAW_PRIORITY_PAIRS,
    SAJU_REGEX_REPLACEMENTS,
    SAJU_TERM_ALLOWED_COMPOUND_PREFIXES,
    SAJU_TERM_CONTEXT_KEYWORDS,
    TRAILING_SUFFIXES,
    WORD_CHAR_RE,
)

AUTO_REPLACE_PAIR_RE = re.compile(r"^[가-힣A-Za-z0-9]+(?: [가-힣A-Za-z0-9]+)?$")


def merge_replace_pairs(
    existing: list[tuple[str, str]],
    applied: list[tuple[str, str, int]],
    expanded_pair_to_base: dict[tuple[str, str], tuple[str, str]],
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    merged = existing.copy()
    seen = set(existing)
    added: list[tuple[str, str]] = []
    for wrong, right, _ in applied:
        wrong, right = expanded_pair_to_base.get((wrong, right), (wrong, right))
        if not is_auto_dict_replace_candidate(wrong, right):
            continue
        pair = (wrong, right)
        if pair in seen:
            continue
        seen.add(pair)
        merged.append(pair)
        added.append(pair)
    return merged, added


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


def is_scenic_gyeonggwan_context(text: str, start: int, end: int) -> bool:
    left = max(0, start - 24)
    right = min(len(text), end + 24)
    snippet = text[left:right]
    return bool(
        re.search(
            r"(?:외부|자연)\s*경관|경관(?:을|이|은|는|으로|로)?\s*(?:끌어들|감상|조망|수려|좋)|조경|정원|원림|차경|풍경|경치",
            snippet,
        )
    )


JI_STEM_ALLOWED_TERMS = (
    "정재",
    "편재",
    "정제",
    "편제",
    "정관",
    "편관",
    "정인",
    "편인",
    "비견",
    "겁재",
    "식신",
    "상관",
    "재성",
    "관성",
    "인성",
    "식상",
    "비겁",
    "재백궁",
    "제백궁",
    "육합",
    "한난",
    "관",
    "왕지",
    "발달",
    "제가",
    "있는",
    "있고",
    "있다",
    "있다는",
)

JI_STEM_PARTICLES = ("의", "가", "는", "이", "에", "로", "으로")


def is_saju_ji_stem_context(suffix: str, text: str, end: int) -> bool:
    tail = (suffix + text[end : end + 24]).lstrip()
    if tail.startswith(("강점기", "강", "식", "때", "때부터")):
        return False
    if any(tail.startswith(term) for term in JI_STEM_ALLOWED_TERMS):
        return True
    for particle in JI_STEM_PARTICLES:
        if not tail.startswith(particle):
            continue
        rest = tail[len(particle) :].lstrip()
        if any(rest.startswith(term) for term in JI_STEM_ALLOWED_TERMS):
            return True
    return False


def should_apply_replacement(
    text: str,
    start: int,
    end: int,
    wrong: str,
    right: str,
    context: CorrectionContext,
    expanded_pair_to_base: dict[tuple[str, str], tuple[str, str]],
) -> bool:
    pair = (wrong, right)
    base_pair = expanded_pair_to_base.get(pair, pair)

    if pair in FORCE_DOMAIN_REPLACEMENTS:
        return True

    if context.dict_topic == "saju":
        if context.source_under_saju_raw and base_pair in SAJU_RAW_PRIORITY_PAIRS:
            return True
        if base_pair in SAJU_RAW_PRIORITY_PAIRS and not has_context_keyword(
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
    text: str,
    rules: list[tuple[str, str]],
    context: CorrectionContext,
    expanded_pair_to_base: dict[tuple[str, str], tuple[str, str]],
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
            if should_apply_replacement(
                text,
                start,
                end,
                wrong,
                right,
                context,
                expanded_pair_to_base,
            ):
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


def apply_saju_regex_replacements(
    text: str, context: CorrectionContext
) -> tuple[str, list[tuple[str, str, int]]]:
    if context.dict_topic != "saju":
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

    def normalize_saju_contextual_patterns(source_text: str) -> str:
        for pattern, replacement, wrong_label, right_label, include_keywords, exclude_keywords in (
            SAJU_CONTEXT_REGEX_RULES
        ):
            def replace_contextual(match: re.Match[str]) -> str:
                start, end = match.span()
                if exclude_keywords and has_context_keyword(
                    source_text, start, end, exclude_keywords, window=120
                ):
                    return match.group(0)
                if include_keywords and not has_context_keyword(
                    source_text, start, end, include_keywords, window=120
                ):
                    return match.group(0)
                track_replacement(wrong_label, right_label)
                return match.expand(replacement)

            source_text = pattern.sub(replace_contextual, source_text)

        return source_text

    def normalize_saju_term_families(source_text: str) -> str:
        for pattern, wrong_stem, right_stem, skip_prefixes, needs_context, exclude_contexts in (
            SAJU_FAMILY_REPLACEMENT_RULES
        ):
            def replace_family(match: re.Match[str]) -> str:
                token = match.group(0)
                suffix = token[len(wrong_stem) :]
                start, end = match.span()

                if wrong_stem in {"정제", "편제", "생제"} and start > 0 and WORD_CHAR_RE.match(
                    source_text[start - 1]
                ):
                    if not any(
                        source_text[:start].endswith(prefix)
                        for prefix in SAJU_TERM_ALLOWED_COMPOUND_PREFIXES
                    ):
                        return token

                if skip_prefixes and any(suffix.startswith(prefix) for prefix in skip_prefixes):
                    return token

                if exclude_contexts and has_context_keyword(
                    source_text, start, end, exclude_contexts, window=120
                ):
                    return token

                if wrong_stem == "경관" and is_scenic_gyeonggwan_context(
                    source_text, start, end
                ):
                    return token

                if wrong_stem in {"일제", "월제", "연제", "시제"} and not is_saju_ji_stem_context(
                    suffix, source_text, end
                ):
                    return token

                if needs_context and not has_context_keyword(
                    source_text, start, end, SAJU_TERM_CONTEXT_KEYWORDS, window=120
                ):
                    return token

                replacement = right_stem + suffix
                if replacement != token:
                    track_replacement(f"{wrong_stem}*", f"{right_stem}*")
                return replacement

            source_text = pattern.sub(replace_family, source_text)

        return source_text

    text = normalize_saju_contextual_patterns(text)
    text = normalize_saju_term_families(text)
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


SAJU_STABLE_NORMALIZATIONS: tuple[tuple[str, str], ...] = (
    ("묵의 입장에서는", "목의 입장에서는"),
    ("목 절딘다는", "목절된다는"),
    ("관계딘", "관계된"),
    ("붐디는 게", "분되는게"),
    ("화생토된 상태 상태 유지하는 것", "화생토된 상태를 유지하는 것"),
    ("토생금디는 것", "토생금되는 것"),
    ("재생 살 디는 구조", "재생살되는 구조"),
    ("머리가 디는 것", "머리가 되는 것"),
    ("조호도 디고 수생목도 디고", "조후도 되고 수생목도 되고"),
    ("디테일하게 건디니까", "디테일하게 건드리니까"),
    ("알갱이딘 상태", "알갱이된 상태"),
    ("벌룩", "건록"),
    ("신앙하다는", "신왕하다는"),
    ("정관을 응했다", "정관을 용했다"),
    ("금강목", "금극목"),
    ("기억 디지 않는 것들", "기억되지 않는 것들"),
    ("대수가 있든지", "계수가 있든지"),
    ("호국수까지", "토극수까지"),
    ("건록격의 정관을 용했다.", "건록격에 정관을 용했다."),
    ("무의식 적 형태의 시간이죠.", "무의식적 형태의 시간이죠."),
    ("화를 화 금이고", "화극금이고"),
    ("금악 교역", "금화교역"),
    ("얘기한금화교역", "얘기한 금화교역"),
    ("얘기한금", "얘기한 금"),
    ("화급금", "화극금"),
    ("토검상관", "토금상관"),
    ("묵과", "목과"),
    ("하당", "하강"),
    ("승목", "습목"),
    ("금생술을", "금생수를"),
    ("군생술을", "금생수를"),
    ("한한금", "한한 금"),
    ("하난금극목", "한한 금극목"),
    ("근궁묵", "금극목"),
    ("긍긍묵", "금극목"),
    ("조환금", "조한 금"),
    ("사활을", "사화를"),
    ("수생목 디는", "수생목되는"),
    ("금생수 디는", "금생수되는"),
    ("금생수디는", "금생수되는"),
    ("금생수호디는", "금생수되는"),
    ("화생 토디는", "화생토되는"),
    ("화생토디는", "화생토되는"),
    ("화생토 디는", "화생토되는"),
    ("귀일 디는", "귀일되는"),
    ("통일 디는", "통일되는"),
    ("화생터디는", "화생토되는"),
    ("화생토딘 상태", "화생토된 상태"),
    ("토극수딘", "토극수된"),
    ("토극수 디는 것", "토극수되는 것"),
    ("토생금디는 형태", "토생금되는 형태"),
    ("토국소딘 상태", "토극수된 상태"),
    ("목생화디는", "목생화되는"),
    ("부여디는 품수디는", "부여되는 품수되는"),
    ("돈디는 것과 연관해서", "돈 되는 것과 연관해서"),
    ("돈디는", "돈 되는"),
    ("돈딘다", "돈 된다"),
    ("돈디지", "돈 되지"),
    ("돈디기 어렵다", "돈 되기 어렵다"),
    ("주딘 작용", "주된 작용"),
    ("주딘 역할", "주된 역할"),
    ("교차딘다", "교차된다"),
    ("공유딘다", "공유된다"),
    ("대대딘다고", "대대된다고"),
    ("재가 설딘다", "재가 설된다"),
    ("목생화, 디는 것", "목생화되는 것"),
    ("내 몫을 건디는", "내 몫을 건드리는"),
    ("출디는데", "출되는데"),
    ("가시화 디는", "가시화되는"),
    ("이렇게 디는 것을", "이렇게 되는 것을"),
    ("재생 살디는 명", "재생살되는 명"),
    ("재생관디는", "재생관되는"),
    ("사회충디는", "사해충되는"),
    ("고무디는", "고무되는"),
    ("고무딘다", "고무된다"),
    ("토생금디는명이", "토생금되는 명이"),
    ("발아 디지만", "발아되지만"),
    ("발아 안 디는", "발아 안 되는"),
    ("화극금딘 상태", "화극금된 상태"),
    ("금생수 딘 상태", "금생수된 상태"),
    ("하들끼리", "화들끼리"),
    ("화생토딘 사회문화", "화생토된 사회문화"),
    ("목극토디는", "목극토되는"),
    ("목 붐디지 않으려면", "목분되지 않으려면"),
    ("오야죠", "와야죠"),
    ("플랭크", "블랭크"),
    ("경검", "경금"),
    ("더디딘다", "더딘다"),
    ("허왕딘 꿈", "허황된 꿈"),
    ("교차딘 영역", "교차된 영역"),
    ("그렇게 디는 것을", "그렇게 되는 것을"),
    ("무의식을 건딘 프로이트", "무의식을 건드린 프로이트"),
    ("금생 수딘다는", "금생수된다는"),
    ("금극목이 안딘 목", "금극목이 안 된 목"),
    ("화극 금디는", "화극금되는"),
    ("면천디고", "면천되고"),
    ("목 분딘다는", "목분된다는"),
    ("목극 토디는", "목극토되는"),
    ("응어리딘", "응어리된"),
    ("덩어리딘", "덩어리된"),
    ("삼재팔란", "삼재팔난"),
    ("사막과 반국", "삼합과 방국"),
    ("임묘진", "인묘진"),
    ("사인상생", "살인상생"),
    ("살인 상생", "살인상생"),
    ("살인상징", "살인상생"),
    ("건디는", "건드리는"),
    ("근근복", "금극목"),
    ("병호일조", "병오일주"),
    ("개해일조", "계해일주"),
    ("일조론", "일주론"),
    ("화일조", "화일주"),
    ("일조들은", "일주들은"),
    ("일조이다", "일주이다"),
    ("일지가 근기이긴 한데", "일지가 근이긴 한데"),
    ("수생 목생화", "수생목생화"),
    ("목생 화", "목생화"),
    ("목생활을", "목생화를"),
    ("목생활", "목생화"),
    ("목생화을", "목생화를"),
    ("손 대면", "손대면"),
    ("화생토된 상태 상태 유지하는 것", "화생토된 상태를 유지하는 것"),
)

SAJU_STABLE_REGEX_NORMALIZATIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(?<![가-힣])한 금(?=(?:\s|$|[.,?!]|은|는|이|가|을|를|의|에|와|과|로|도|만|뿐|이라|이면|이고|이죠|이잖|인데|이다|이니|하게|하는|하다))"
        ),
        "한금",
    ),
    (
        re.compile(
            r"(?<![가-힣])난 금(?=(?:\s|$|[.,?!]|은|는|이|가|을|를|의|에|와|과|로|도|만|뿐|이라|이면|이고|이죠|이잖|인데|이다|이니|하게|하는|하다))"
        ),
        "난금",
    ),
    (
        re.compile(
            r"(?<![가-힣])남금(?=(?:\s|$|[.,?!]|은|는|이|가|을|를|의|에|와|과|로|도|만|뿐|이라|이면|이고|이죠|이잖|인데|이다|이니|하게|하는|하다))"
        ),
        "난금",
    ),
    (
        re.compile(r"금생 수(?=(?:가|는|를|로|의|도|만|하|\s|$|[.,?!]))"),
        "금생수",
    ),
    (
        re.compile(r"(?<![가-힣])활을(?=[^가-힣]|$)"),
        "화를",
    ),
    (
        re.compile(r"([갑을병정무기경신임계][자축인묘진사오미신유술해])일조"),
        r"\1일주",
    ),
    (
        re.compile(
            r"(?<!제)4주(?=(?:가|는|를|로|에|에서|의|하고)|\s+(?:공부|하고|전체|구성|보\S*|볼\S*|딱|펼쳐\S*|뽑\S*|갖고|그러니까|이렇게))"
        ),
        "사주",
    ),
)


def apply_saju_stable_normalizations(
    text: str,
    context: CorrectionContext,
) -> tuple[str, list[tuple[str, str, int]]]:
    if context.dict_topic != "saju":
        return text, []

    applied: list[tuple[str, str, int]] = []
    for wrong, right in SAJU_STABLE_NORMALIZATIONS:
        count = text.count(wrong)
        if count == 0:
            continue
        text = text.replace(wrong, right)
        applied.append((wrong, right, count))

    for pattern, right in SAJU_STABLE_REGEX_NORMALIZATIONS:
        text, count = pattern.subn(right, text)
        if count == 0:
            continue
        applied.append((pattern.pattern, right, count))

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


def normalize_term_candidate(text: str, term_stopwords: frozenset[str]) -> str:
    candidate = text.strip()
    if candidate in term_stopwords:
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

    if candidate in term_stopwords:
        return ""
    if len(candidate) < 2 or len(candidate) > 20:
        return ""
    if not KOREAN_RE.search(candidate):
        return ""
    return candidate


def is_term_candidate(text: str) -> bool:
    return bool(normalize_term_candidate(text, frozenset()))


def merge_terms_from_applied(
    existing_terms: list[str],
    applied: list[tuple[str, str, int]],
    context: CorrectionContext,
) -> tuple[list[str], list[str]]:
    merged = existing_terms.copy()
    seen = set(existing_terms)
    added: list[str] = []
    for _, right, _ in applied:
        normalized = normalize_term_candidate(right, context.term_stopwords)
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        merged.append(normalized)
        added.append(normalized)
    return merged, added
