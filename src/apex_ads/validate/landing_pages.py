"""Landing-page rules (spec §9.6, Decision A6).

The workbook stores **paths** (`/google/apex-jaipur`); the base URL is joined here, at
check time, and never written back into the workbook.
"""

from __future__ import annotations

from collections.abc import Iterable

from apex_ads.ingest.urlcheck import UrlResult, absolute
from apex_ads.models.config import Rules
from apex_ads.models.findings import Finding, Severity
from apex_ads.models.workbook import WorkbookBundle
from apex_ads.validate.base import Rule
from apex_ads.validate.structure import resolve_landing_pages

SHEET = "02 BUILD"


class LandingPageUrlIsValid(Rule):
    """`LP-001` — every destination is a valid absolute https URL within the length cap."""

    rule_id = "LP-001"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        page_rules = rules.landing_pages
        for page in bundle.landing_pages:
            url = absolute(page.planned_url, page_rules.base_url)
            if page_rules.require_https and not url.startswith("https://"):
                yield self.finding(
                    f"{page.ad_group} resolves to {url!r}, which is not https",
                    sheet=page.sheet,
                    row=page.row,
                    section=page.section,
                    entity=page.ad_group,
                    remedy="Correct the path, or landing_pages.base_url in config.",
                )
            if len(url) > page_rules.max_url_chars:
                yield self.finding(
                    f"{page.ad_group} resolves to a {len(url)}-character URL "
                    f"(limit {page_rules.max_url_chars})",
                    sheet=page.sheet,
                    row=page.row,
                    section=page.section,
                    entity=page.ad_group,
                    remedy="Shorten the path.",
                )


class OneLandingPagePerAdGroup(Rule):
    """`LP-002` — every ad group has exactly one destination, and the two sheets agree."""

    rule_id = "LP-002"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        if not rules.landing_pages.one_landing_page_per_ad_group:
            return
        resolved = resolve_landing_pages(bundle)

        for group in bundle.ad_groups:
            brief = resolved.get(group.key)
            if brief is None:
                yield self.finding(
                    f"{group.key} has no landing-page brief",
                    sheet=group.sheet,
                    row=group.row,
                    section=group.section,
                    entity=str(group.key),
                    remedy="Add a row in LANDING PAGE BUILD BRIEFS for this ad group.",
                )
            elif group.planned_landing_page and group.planned_landing_page != brief:
                yield self.finding(
                    f"{group.key} points at {group.planned_landing_page!r} in AD GROUP "
                    f"BUILD but {brief!r} in LANDING PAGE BUILD BRIEFS",
                    sheet=group.sheet,
                    row=group.row,
                    section=group.section,
                    entity=str(group.key),
                    remedy="Make the two sheets agree; they describe the same destination.",
                )


class LandingPageReachable(Rule):
    """`LP-003` — every destination actually loads.

    Constructed with the results of the URL check, because the check is I/O and the
    validators are pure. When no results are supplied the rule says so rather than
    staying silent: a check that did not run must never read as a check that passed.
    """

    rule_id = "LP-003"
    severity = Severity.BLOCKER

    def __init__(self, results: dict[str, UrlResult] | None = None) -> None:
        self.results = results

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        if not rules.landing_pages.check_http:
            return
        if self.results is None:
            yield self.finding(
                "landing-page reachability was not checked in this run",
                sheet=SHEET,
                section="landing_pages",
                severity=Severity.WARNING,
                remedy="Run without --no-network to verify the destinations.",
            )
            return

        for page in bundle.landing_pages:
            result = self.results.get(page.planned_url)
            if result is None or result.status == "PASS":
                continue
            severity = Severity.BLOCKER if result.status == "BLOCKER" else Severity.WARNING
            label = "unreachable" if result.status == "BLOCKER" else "UNKNOWN"
            yield self.finding(
                f"{page.ad_group} → {result.url} is {label}: {result.reason}",
                sheet=page.sheet,
                row=page.row,
                section=page.section,
                severity=severity,
                entity=page.ad_group,
                remedy="Fix the page or the path. An UNKNOWN result is not a pass — no "
                "deployable build is produced while any destination is unverified.",
            )


class LandingPageDomainAllowed(Rule):
    """`LP-004` — the final URL after redirects is still on an approved domain."""

    rule_id = "LP-004"
    severity = Severity.BLOCKER

    def __init__(self, results: dict[str, UrlResult] | None = None) -> None:
        self.results = results

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        allowed = rules.landing_pages.allowed_domains + rules.landing_pages.extra_allowed_domains
        for page in bundle.landing_pages:
            url = absolute(page.planned_url, rules.landing_pages.base_url)
            host = url.split("/")[2] if "//" in url else ""
            if host and host.casefold() not in {name.casefold() for name in allowed}:
                yield self.finding(
                    f"{page.ad_group} points at {host!r}, which is not an approved domain",
                    sheet=page.sheet,
                    row=page.row,
                    section=page.section,
                    entity=page.ad_group,
                    remedy=f"Approved domains: {allowed}. Add it to "
                    "landing_pages.extra_allowed_domains only after review.",
                )

            result = (self.results or {}).get(page.planned_url)
            if result and result.status == "BLOCKER" and "off-domain" in result.reason:
                yield self.finding(
                    f"{page.ad_group} {result.reason}",
                    sheet=page.sheet,
                    row=page.row,
                    section=page.section,
                    entity=page.ad_group,
                    remedy="A redirect is sending paid traffic off the approved domain.",
                )
