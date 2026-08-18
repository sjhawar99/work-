"""Positive keyword rules (spec §9.4)."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable

from apex_ads.models.config import Rules
from apex_ads.models.findings import Finding, Severity
from apex_ads.models.workbook import WorkbookBundle
from apex_ads.policy import MODIFIED_BROAD_ALIASES
from apex_ads.util.text import tokenise
from apex_ads.validate.base import Rule

SHEET = "03 KEYWORDS"
INVALID_CHARACTERS = re.compile(r"[!@%,*~^()=;<>?{}\[\]|]")


class NoBroadPositives(Rule):
    """`KW-001` — no positive keyword compiles to Broad.

    A workbook row saying `Broad` fails the build. It is not normalised, not downgraded
    and not warned about: Stage 1 buys Exact and Phrase only.
    """

    rule_id = "KW-001"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        allowed = set(rules.keywords.allowed_positive_match_types)
        for keyword in bundle.keywords:
            if keyword.match_type not in allowed:
                yield self.finding(
                    f"keyword {keyword.text!r} uses {keyword.match_type} match; Stage 1 "
                    f"allows {sorted(allowed)} only",
                    sheet=keyword.sheet,
                    row=keyword.row,
                    section=keyword.section,
                    entity=str(keyword.key) if keyword.key else keyword.text,
                    remedy="Change the match type to Phrase or Exact in 03 KEYWORDS.",
                )


class OneAdGroupPerKeyword(Rule):
    """`KW-002` — a keyword text lives in one ad group. Duplication is self-competition."""

    rule_id = "KW-002"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        owners: dict[str, set[str]] = defaultdict(set)
        for keyword in bundle.keywords:
            if keyword.key is not None:
                owners[keyword.text].add(str(keyword.key))

        limit = rules.keywords.max_ad_groups_per_keyword
        for keyword in bundle.keywords:
            found = owners.get(keyword.text, set())
            if len(found) > limit:
                yield self.finding(
                    f"keyword {keyword.text!r} appears in {len(found)} ad groups "
                    f"({', '.join(sorted(found))})",
                    sheet=keyword.sheet,
                    row=keyword.row,
                    section=keyword.section,
                    entity=keyword.text,
                    remedy="Keep it in one ad group; the campaigns would otherwise bid "
                    "against each other.",
                )


class NoDuplicateKeywords(Rule):
    """`KW-003` — no exact duplicate (text, match type) inside one ad group."""

    rule_id = "KW-003"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        counts = Counter(
            (str(keyword.key), keyword.text, keyword.match_type)
            for keyword in bundle.keywords
            if keyword.key is not None
        )
        for (group, text, match), count in counts.items():
            if count > 1:
                yield self.finding(
                    f"keyword {text!r} ({match.lower()}) appears {count} times in {group}",
                    sheet=SHEET,
                    section="keyword_registry",
                    entity=text,
                    remedy="Remove the duplicate rows.",
                )


class KeywordTextIsUsable(Rule):
    """`KW-004` — within Google's length limit and free of unsupported characters."""

    rule_id = "KW-004"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        limit = rules.keywords.max_keyword_chars
        for keyword in bundle.keywords:
            if len(keyword.text) > limit:
                yield self.finding(
                    f"keyword {keyword.text!r} is {len(keyword.text)} characters; the "
                    f"limit is {limit}",
                    sheet=keyword.sheet,
                    row=keyword.row,
                    section=keyword.section,
                    entity=keyword.text,
                    remedy="Shorten it.",
                )
            if found := INVALID_CHARACTERS.findall(keyword.text):
                yield self.finding(
                    f"keyword {keyword.text!r} contains unsupported characters "
                    f"{sorted(set(found))}",
                    sheet=keyword.sheet,
                    row=keyword.row,
                    section=keyword.section,
                    entity=keyword.text,
                    remedy="Remove the punctuation Google does not accept in keywords.",
                )


class NearDuplicateKeywords(Rule):
    """`KW-005` — near-duplicates across ad groups, word-order-insensitive."""

    rule_id = "KW-005"
    severity = Severity.WARNING

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        seen: dict[frozenset[str], list[tuple[str, str]]] = defaultdict(list)
        for keyword in bundle.keywords:
            if keyword.key is not None:
                seen[frozenset(tokenise(keyword.text))].append((str(keyword.key), keyword.text))

        for _, entries in seen.items():
            groups = {group for group, _ in entries}
            if len(groups) > 1:
                texts = sorted({text for _, text in entries})
                yield self.finding(
                    f"near-duplicate keywords across {len(groups)} ad groups: {texts}",
                    sheet=SHEET,
                    section="keyword_registry",
                    entity=texts[0],
                    remedy="Decide which ad group should own this demand.",
                )


class AdGroupThemeDeclared(Rule):
    """`KW-006` — every keyword's ad group declares what it is for."""

    rule_id = "KW-006"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        themes = {group.key: group.dominant_intent for group in bundle.ad_groups}
        reported: set[str] = set()
        for keyword in bundle.keywords:
            if keyword.key is None or keyword.key not in themes:
                continue
            if not themes[keyword.key] and str(keyword.key) not in reported:
                reported.add(str(keyword.key))
                yield self.finding(
                    f"{keyword.key} has keywords but no declared dominant intent",
                    sheet="02 BUILD",
                    section="ad_groups",
                    entity=str(keyword.key),
                    remedy="Fill the Dominant intent column in AD GROUP BUILD.",
                )


class KeywordLevelUrls(Rule):
    """`KW-007` — keyword-level final URLs share the ad group's domain.

    The registry has no keyword-level URL column, so this reports itself as not
    applicable. A check that did not apply is never silently counted as a pass.
    """

    rule_id = "KW-007"
    severity = Severity.INFO

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        yield self.finding(
            "not applicable: 03 KEYWORDS declares no keyword-level final URLs",
            sheet=SHEET,
            section="keyword_registry",
            severity=Severity.INFO,
        )


class LegacyMatchTypeNormalised(Rule):
    """`KW-008` — `Modified Broad` was converted to Phrase.

    Broad Match Modifier no longer exists at Google: legacy BMM keywords behave as
    Phrase, and new ones cannot be created. Normalising is correct and safe. A real
    `Broad` keyword is a different thing and still fails `KW-001`.
    """

    rule_id = "KW-008"
    severity = Severity.WARNING

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        for row in [*bundle.keywords, *bundle.negatives]:
            if row.match_type_raw.strip().casefold() in MODIFIED_BROAD_ALIASES:
                yield self.finding(
                    f"LEGACY_MATCH_TYPE_NORMALIZED: Modified Broad is discontinued. "
                    f"Converted to Phrase for {row.text!r}.",
                    sheet=row.sheet,
                    row=row.row,
                    section=row.section,
                    entity=row.text,
                    remedy="Update the Match type column to Phrase so the workbook says "
                    "what will actually be built.",
                )


class DerivedCopyPasteValue(Rule):
    """`KW-009` — the workbook's `COPY / PASTE VALUE` matches what the tool regenerates.

    That column is derived data, not source truth. When it disagrees with the keyword
    text and match type beside it, somebody edited one and not the other — and the
    disagreement is exactly what would get pasted into Google Ads.
    """

    rule_id = "KW-009"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        if not rules.keywords.verify_copy_paste_column:
            return
        for row in [*bundle.keywords, *bundle.negatives]:
            if not row.copy_paste_matches:
                yield self.finding(
                    f"COPY / PASTE VALUE reads {row.copy_paste_value!r} but "
                    f"{row.text!r} ({row.match_type.lower()}) should give "
                    f"{row.copy_paste_expected!r}",
                    sheet=row.sheet,
                    row=row.row,
                    section=row.section,
                    entity=row.text,
                    remedy="Correct the COPY / PASTE VALUE cell, or the text or match "
                    "type beside it.",
                )
