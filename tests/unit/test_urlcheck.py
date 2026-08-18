"""Landing-page reachability (Decision A6).

No test here touches the network: the fetcher is injected, so every state — including
the ones that only happen on a bad day — is exercised deterministically.
"""

from __future__ import annotations

import pytest

from apex_ads.ingest.urlcheck import FetchError, Response, UrlResult, absolute, check_all, check_url
from apex_ads.models.config import LandingPageRules, Rules

BASE = "https://www.apexhospitals.com"


@pytest.fixture()
def page_rules(fixture_rules: Rules) -> LandingPageRules:
    return fixture_rules.landing_pages


def responding(status: int, final: str | None = None, redirects: int = 0):
    def fetch(url: str, agent: str, timeout: float, follow: bool, max_redirects: int) -> Response:
        return Response(status_code=status, final_url=final or url, redirect_count=redirects)

    return fetch


def failing(message: str):
    def fetch(url: str, agent: str, timeout: float, follow: bool, max_redirects: int) -> Response:
        raise FetchError(message)

    return fetch


def test_workbook_paths_are_joined_onto_the_base_url() -> None:
    assert absolute("/google/apex-jaipur", BASE) == f"{BASE}/google/apex-jaipur"
    assert absolute("google/apex-jaipur", BASE) == f"{BASE}/google/apex-jaipur"
    assert absolute("https://other.example/x", BASE) == "https://other.example/x"


def test_a_reachable_page_passes(page_rules: LandingPageRules) -> None:
    result = check_url(f"{BASE}/x", page_rules, fetch=responding(200))
    assert result.status == "PASS"
    assert result.http_status == 200
    assert result.latency_seconds is not None


def test_a_404_blocks(page_rules: LandingPageRules) -> None:
    result = check_url(f"{BASE}/missing", page_rules, fetch=responding(404))
    assert result.status == "BLOCKER"
    assert "404" in result.reason


@pytest.mark.parametrize("status", [403, 500, 503])
def test_other_failures_block(page_rules: LandingPageRules, status: int) -> None:
    assert check_url(f"{BASE}/x", page_rules, fetch=responding(status)).status == "BLOCKER"


def test_an_off_domain_redirect_blocks(page_rules: LandingPageRules) -> None:
    result = check_url(
        f"{BASE}/x", page_rules, fetch=responding(200, "https://elsewhere.example.com/x")
    )
    assert result.status == "BLOCKER"
    assert "off-domain" in result.reason


def test_a_redirect_loop_blocks(page_rules: LandingPageRules) -> None:
    result = check_url(f"{BASE}/x", page_rules, fetch=failing("more than 5 redirects"))
    assert result.status == "BLOCKER"
    assert "redirect" in result.reason


def test_too_many_redirects_blocks(page_rules: LandingPageRules) -> None:
    result = check_url(f"{BASE}/x", page_rules, fetch=responding(200, redirects=99))
    assert result.status == "BLOCKER"


def test_a_timeout_is_unknown_not_a_pass(page_rules: LandingPageRules) -> None:
    """The rule that most invites a shortcut and most deserves not to get one."""
    result = check_url(f"{BASE}/x", page_rules, fetch=failing("connection timed out"))
    assert result.status == "UNKNOWN"
    assert not result.passed


def test_a_non_https_url_blocks(page_rules: LandingPageRules) -> None:
    assert (
        check_url("http://www.apexhospitals.com/x", page_rules, fetch=responding(200)).status
        == "BLOCKER"
    )


def test_a_disallowed_domain_blocks_before_any_request(page_rules: LandingPageRules) -> None:
    def explode(*args: object) -> Response:
        raise AssertionError("must not be requested")

    result = check_url("https://evil.example.com/x", page_rules, fetch=explode)
    assert result.status == "BLOCKER"
    assert "not an allowed domain" in result.reason


def test_googleadsbot_retry_rescues_a_page_that_refuses_unknown_agents(
    page_rules: LandingPageRules,
) -> None:
    """Some sites treat Google's crawler differently from everyone else."""
    seen: list[str] = []

    def fetch(url: str, agent: str, timeout: float, follow: bool, max_redirects: int) -> Response:
        seen.append(agent)
        return Response(200 if "AdsBot" in agent else 403, url)

    result = check_url(f"{BASE}/x", page_rules, fetch=fetch)
    assert result.status == "PASS"
    assert len(seen) == 2
    assert "AdsBot" in seen[1]


def test_no_network_marks_everything_unknown(page_rules: LandingPageRules) -> None:
    results = check_all(["/a", "/b"], page_rules, network_enabled=False)
    assert {check.status for check in results.values()} == {"UNKNOWN"}
    assert "no-network" in results["/a"].reason


def test_duplicate_urls_are_only_fetched_once(page_rules: LandingPageRules) -> None:
    calls: list[str] = []

    def fetch(url: str, agent: str, timeout: float, follow: bool, max_redirects: int) -> Response:
        calls.append(url)
        return Response(200, url)

    check_all(["/same", "/same", "/other"], page_rules, fetch=fetch)
    assert len(calls) == 2


def test_results_are_keyed_by_the_workbook_value(page_rules: LandingPageRules) -> None:
    results = check_all(["/google/apex-jaipur"], page_rules, fetch=responding(200))
    result: UrlResult = results["/google/apex-jaipur"]
    assert result.url == f"{BASE}/google/apex-jaipur"
