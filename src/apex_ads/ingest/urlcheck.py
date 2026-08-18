"""Landing-page reachability (Decision A6, spec §9.6).

Twelve steps per URL, ending in exactly one of three states:

    PASS      200, allowed domain, within the redirect cap
    BLOCKER   404 / 403 / 5xx / redirect loop / off-domain redirect / bad scheme
    UNKNOWN   the check could not be completed

**`UNKNOWN` is not `PASS`.** This is the rule that most invites a shortcut and most
deserves not to get one: a build whose destinations were never verified is a build that
may be dead on arrival, and Google disapproves ads whose destination it cannot reach.

The network layer is injected (`fetch`), so tests exercise every state without touching
the network — and `requests` is imported lazily, so `--no-network` runs on a machine that
does not have it installed.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urljoin, urlparse

from apex_ads.models.config import LandingPageRules

Status = Literal["PASS", "BLOCKER", "UNKNOWN"]


@dataclass(frozen=True)
class Response:
    """What a fetcher reports back. Deliberately smaller than a `requests.Response`."""

    status_code: int
    final_url: str
    redirect_count: int = 0


class FetchError(Exception):
    """The request could not be completed at all — DNS, timeout, connection refused."""


Fetcher = Callable[[str, str, float, bool, int], Response]
"""(url, user_agent, timeout, follow_redirects, max_redirects) -> Response."""


@dataclass(frozen=True)
class UrlResult:
    """One URL's verdict, with the evidence a human needs to act on it."""

    url: str
    status: Status
    reason: str
    http_status: int | None = None
    final_url: str | None = None
    latency_seconds: float | None = None

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


def absolute(path_or_url: str, base_url: str) -> str:
    """Join a workbook path (`/google/apex-jaipur`) onto the configured base URL."""
    if path_or_url.startswith(("http://", "https://")):
        return path_or_url
    return urljoin(base_url.rstrip("/") + "/", path_or_url.lstrip("/"))


def _host_allowed(url: str, rules: LandingPageRules) -> bool:
    host = (urlparse(url).hostname or "").casefold()
    allowed = {name.casefold() for name in rules.allowed_domains + rules.extra_allowed_domains}
    return host in allowed


def _requests_fetcher() -> Fetcher:
    """The real network fetcher. Imported lazily so `--no-network` needs no `requests`."""
    import requests

    def fetch(
        url: str, user_agent: str, timeout: float, follow_redirects: bool, max_redirects: int
    ) -> Response:
        session = requests.Session()
        session.max_redirects = max_redirects
        try:
            response = session.get(
                url,
                headers={"User-Agent": user_agent},
                timeout=timeout,
                allow_redirects=follow_redirects,
            )
        except requests.TooManyRedirects as exc:
            raise FetchError(f"more than {max_redirects} redirects") from exc
        except requests.RequestException as exc:
            raise FetchError(str(exc)) from exc
        return Response(
            status_code=response.status_code,
            final_url=response.url,
            redirect_count=len(response.history),
        )

    return fetch


def check_url(url: str, rules: LandingPageRules, *, fetch: Fetcher) -> UrlResult:
    """Run the twelve-step sequence for one URL."""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return UrlResult(url, "BLOCKER", "not a valid absolute URL")
    if rules.require_https and parsed.scheme != "https":
        return UrlResult(url, "BLOCKER", f"scheme is {parsed.scheme}, not https")
    if len(url) > rules.max_url_chars:
        return UrlResult(
            url, "BLOCKER", f"URL is {len(url)} characters (limit {rules.max_url_chars})"
        )
    if not _host_allowed(url, rules):
        return UrlResult(url, "BLOCKER", f"host {parsed.hostname!r} is not an allowed domain")

    agents = ["apex-ads-preflight/1.0"]
    if rules.googleadsbot_retry:
        agents.append(rules.googleadsbot_user_agent)

    last_error = ""
    for agent in agents:
        started = time.monotonic()
        try:
            response = fetch(
                url,
                agent,
                float(rules.timeout_seconds),
                rules.follow_redirects,
                rules.max_redirect_depth,
            )
        except FetchError as exc:
            last_error = str(exc).split("(Caused by")[0].strip()
            if "redirect" in last_error.casefold():
                return UrlResult(url, "BLOCKER", last_error)
            continue

        latency = round(time.monotonic() - started, 3)

        if response.redirect_count > rules.max_redirect_depth:
            return UrlResult(
                url,
                "BLOCKER",
                f"more than {rules.max_redirect_depth} redirects",
                response.status_code,
                response.final_url,
                latency,
            )
        if rules.final_url_must_be_allowed_domain and not _host_allowed(response.final_url, rules):
            return UrlResult(
                url,
                "BLOCKER",
                f"redirected off-domain to {response.final_url}",
                response.status_code,
                response.final_url,
                latency,
            )
        if response.status_code in rules.allowed_status:
            return UrlResult(
                url, "PASS", "reachable", response.status_code, response.final_url, latency
            )
        last_error = f"returned {response.status_code}"

    if last_error.startswith("returned"):
        return UrlResult(url, "BLOCKER", last_error)
    return UrlResult(url, "UNKNOWN", f"network validation could not complete: {last_error}")


def check_all(
    paths: Sequence[str],
    rules: LandingPageRules,
    *,
    network_enabled: bool = True,
    fetch: Fetcher | None = None,
) -> dict[str, UrlResult]:
    """Check each distinct URL once, keyed by the workbook value that produced it."""
    results: dict[str, UrlResult] = {}
    seen: dict[str, UrlResult] = {}

    if not network_enabled:
        for path in paths:
            url = absolute(path, rules.base_url)
            results[path] = UrlResult(url, "UNKNOWN", "network checks disabled (--no-network)")
        return results

    if fetch is None:
        try:
            fetch = _requests_fetcher()
        except ImportError:
            for path in paths:
                url = absolute(path, rules.base_url)
                results[path] = UrlResult(
                    url,
                    "UNKNOWN",
                    "network validation could not complete: requests is not installed",
                )
            return results

    for path in paths:
        url = absolute(path, rules.base_url)
        if url not in seen:
            seen[url] = check_url(url, rules, fetch=fetch)
        results[path] = seen[url]
    return results
