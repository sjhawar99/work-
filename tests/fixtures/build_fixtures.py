"""Build the synthetic workbooks the parser tests run against.

Fixtures are *generated*, not committed: an opaque binary nobody can diff is a poor test
input, and real client data must never enter the repository (spec §16.3). Each fixture is
a small but structurally faithful copy of the real four-sheet workbook — two campaigns,
three ad groups — varied in exactly one way.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from openpyxl import Workbook

Row = list[Any]
Block = list[Row]

BLANK: Row = []

CAMPAIGN_HEADERS = [
    "#",
    "Exact campaign name",
    "Monthly budget",
    "Avg daily budget",
    "Campaign type",
    "Networks",
    "Geo",
    "Location option",
    "Languages",
    "Launch bidding",
    "Legacy avg CPC (context)",
    "Launch Max CPC limit",
    "Bidding review gate",
    "Primary conversion / bidding goal",
    "Secondary conversions",
    "Call phone number",
    "Call schedule / reporting",
    "Automation guardrails",
    "Status",
    "Why this exists",
    "Launch date",
    "Owner",
]

AD_GROUP_HEADERS = [
    "#",
    "Campaign",
    "Exact ad group name",
    "What it owns",
    "Dominant intent",
    "Planned landing page",
    "Call asset",
    "Keyword source",
    "Negative lists / routing",
    "RSA",
    "Status",
    "Notes",
]

LANDING_PAGE_HEADERS = [
    "Ad group",
    "Planned URL",
    "User question",
    "Hero must answer",
    "Proof / trust",
    "Primary CTA",
    "Must include",
    "Tracking",
    "Status",
]

ASSET_HEADERS = [
    "Asset type",
    "Scope",
    "Text / Header",
    "URL / Values",
    "Description 1",
    "Description 2",
    "Status",
]

MEASUREMENT_HEADERS = [
    "Item",
    "Final rule",
    "Launch status",
    "Owner",
    "QA evidence",
    "Source / note",
]

REGISTRY_HEADERS = [
    "Campaign",
    "Ad group",
    "Scope",
    "Type",
    "Match type",
    "Keyword text",
    "COPY / PASTE VALUE",
    "List name",
    "Status",
    "Why",
    "Added by",
    "Date",
]

DAILY_HEADERS = [
    "Date",
    "Campaign",
    "Planned daily budget",
    "Spend",
    "Clicks",
    "Raw leads / calls",
    "Breakage check",
    "What we changed today (and who)",
    "Delivery / raw-lead signal",
    "Qualified leads (backfill)",
    "Appointments (backfill)",
    "Attended OPD (backfill)",
]

BLOCKING_HEADERS = [
    "#",
    "Task / problem",
    "Type",
    "Owner",
    "Due",
    "Status",
    "Severity",
    "Done when",
]

RUNNING_HEADERS = [
    "#",
    "Date raised",
    "Task or problem",
    "Type",
    "Required action / next step",
    "Owner",
    "Due",
    "Status",
    "Severity",
    "Blocked by",
    "Recurring?",
]

CALL_ASSET_REGISTRY_HEADERS = [
    "Level",
    "Campaign",
    "Ad group",
    "Call phone number",
    "Call schedule / reporting",
    "Status",
    "Why",
]

BRAND = "TST | Search | Brand | Jaipur"
NEURO = "TST | Search | Neuro | Jaipur"


def _campaign(
    number: int,
    name: str,
    monthly: Any,
    daily: Any,
    *,
    call_number: str = "[REQUIRED BEFORE LAUNCH]",
    call_schedule: str = "[REQUIRED] staffed hours",
    networks: str = "Google Search only · Partners OFF · Display OFF",
    extra: str | None = None,
) -> Row:
    row: Row = [
        number,
        name,
        monthly,
        daily,
        "Search",
        networks,
        "Jaipur",
        "Presence",
        "English + Hindi",
        "Maximize Clicks",
        14,
        50,
        "≥15 leads / 30d",
        "Qualified Lead — Primary",
        "Raw form = Secondary",
        call_number,
        call_schedule,
        "AI Max OFF",
        "APPROVED",
        "Isolate owned demand",
        "2026-08-27",
        "Gaurav",
    ]
    if extra is not None:
        row.append(extra)
    return row


def _registry(
    campaign: str,
    ad_group: str,
    scope: str,
    kind: str,
    match: str,
    text: str,
    copy_paste: str,
    list_name: str,
) -> Row:
    return [
        campaign,
        ad_group,
        scope,
        kind,
        match,
        text,
        copy_paste,
        list_name,
        "APPROVED",
        "Stage-1",
        "Strategy",
        "2026-08-17",
    ]


def _derived(text: str, match: str) -> str:
    """The workbook's COPY / PASTE VALUE convention, so fixtures satisfy KW-009."""
    if match.strip().casefold() in {"phrase", "modified broad"}:
        return f'"{text}"'
    if match.strip().casefold() == "exact":
        return f"[{text}]"
    return text


def _actions_sheet(*, red_status: str = "Done") -> list[Block]:
    return [
        [["APEX · TEST WORKBOOK · v1.1"]],
        [
            ["BLOCKING — DO NOT LAUNCH UNTIL THESE CLOSE"],
            BLOCKING_HEADERS,
            [
                1,
                "Approve the lead definition",
                "BUILD",
                "Siddhant",
                "2026-08-18",
                red_status,
                "RED",
                "CRM has one field",
            ],
            [
                2,
                "Lock the data contract",
                "BUILD",
                "Tech",
                "2026-08-20",
                "Done",
                "RED",
                "Lead ID present",
            ],
        ],
        [
            ["RUNNING ACTIONS — BUILD + FIX IN THE SAME INBOX"],
            RUNNING_HEADERS,
            [
                1,
                "2026-08-18",
                "Lock Stage-1 BUILD",
                "BUILD",
                "Approve the budgets",
                "Siddhant",
                "2026-08-18",
                "Done",
                "RED",
                "—",
                "No",
            ],
            [
                2,
                "2026-08-18",
                "Build Neuro landing page",
                "BUILD",
                "Build the page",
                "Web",
                "2026-08-22",
                "Open",
                "AMBER",
                "—",
                "No",
            ],
        ],
    ]


def _build_sheet(
    *,
    monthly_budget: Any = 20000,
    headline_count: int = 12,
    description_count: int = 4,
    include_ad_groups: bool = True,
    campaign_budget_header: str = "Monthly budget",
    extra_registry_column: bool = False,
    unknown_campaign_column: bool = False,
    duplicate_campaign_column: bool = False,
    duplicate_ad_group_name: bool = False,
    declared_total: Any = 25000,
    routing_override: str | None = None,
    long_headline: bool = False,
    call_number: str = "[REQUIRED BEFORE LAUNCH]",
    call_schedule: str = "[REQUIRED] staffed hours",
    networks: str = "Google Search only · Partners OFF · Display OFF",
    call_asset_registry: list[Row] | None = None,
    registry_header_typo: bool = False,
    brand_daily_budget: Any = 164.47,
) -> list[Block]:
    campaign_headers = list(CAMPAIGN_HEADERS)
    campaign_headers[2] = campaign_budget_header
    extra_campaign_value: str | None = None
    if unknown_campaign_column:
        campaign_headers.append("Audience exclusion")
        extra_campaign_value = "Existing patients"
    if duplicate_campaign_column:
        # Differs only in case, which is exactly how this reaches a real sheet: somebody
        # pastes a column back in and the two headings look different to a person and
        # identical to the parser.
        campaign_headers.append("STATUS")
        extra_campaign_value = "APPROVED"

    blocks: list[Block] = [
        [["APEX · TEST BUILD · COPY FROM HERE"]],
        [
            ["CAMPAIGN SETTINGS — ONE ROW PER CAMPAIGN"],
            campaign_headers,
            _campaign(
                1,
                BRAND,
                5000,
                brand_daily_budget,
                call_number=call_number,
                call_schedule=call_schedule,
                networks=networks,
                extra=extra_campaign_value,
            ),
            _campaign(
                2,
                NEURO,
                monthly_budget,
                657.89,
                call_number=call_number,
                call_schedule=call_schedule,
                networks=networks,
                extra=extra_campaign_value,
            ),
            BLANK,
            ["", "APPROVED MONTHLY TOTAL", declared_total],
        ],
    ]

    if include_ad_groups:
        blocks.append(
            [
                ["AD GROUP BUILD — EXACT NAMES + DESTINATIONS"],
                AD_GROUP_HEADERS,
                [
                    1,
                    BRAND,
                    "Brand | Core",
                    "Brand searches",
                    "Brand",
                    "/google/apex-jaipur",
                    "Yes",
                    "03 KEYWORDS",
                    "ACCOUNT_JUNK · OUTSIDE_GEO",
                    "RSA 1",
                    "APPROVED",
                    "",
                ],
                [
                    2,
                    BRAND,
                    "Brand | Action",
                    "Booking searches",
                    "Transaction",
                    "/google/book-apex-jaipur",
                    "Yes",
                    "03 KEYWORDS",
                    "ACCOUNT_JUNK · OUTSIDE_GEO",
                    "RSA 1",
                    "APPROVED",
                    "",
                ],
                [
                    3,
                    NEURO,
                    "Neuro | Provider",
                    "Neurologist searches",
                    "Provider Discovery",
                    "/google/neurologist-jaipur",
                    "Yes",
                    "03 KEYWORDS",
                    routing_override or "ROUTE_BRAND",
                    "RSA 1",
                    "APPROVED",
                    "",
                ],
            ]
        )
        if duplicate_ad_group_name:
            # A second campaign reusing an ad-group name: legal in Google Ads, and fatal
            # to any lookup that assumes ad-group names are globally unique.
            blocks[-1].append(
                [
                    4,
                    BRAND,
                    "Neuro | Provider",
                    "Same name, different campaign",
                    "Provider Discovery",
                    "/google/neurologist-jaipur",
                    "Yes",
                    "03 KEYWORDS",
                    "ROUTE_BRAND",
                    "RSA 1",
                    "APPROVED",
                    "name collides across campaigns",
                ]
            )

    if call_asset_registry is not None:
        registry_headers = list(CALL_ASSET_REGISTRY_HEADERS)
        if registry_header_typo:
            # The realistic mistake: the section is there, somebody typed the heading
            # slightly wrong. "Present but malformed" must never read as "absent".
            registry_headers[3] = "Call phone no."
        blocks.append(
            [
                ["CALL ASSET REGISTRY — NUMBER BY LEVEL"],
                registry_headers,
                *call_asset_registry,
            ]
        )

    blocks.extend(
        [
            [
                ["LANDING PAGE BUILD BRIEFS — NINE PAGES, NO INTERPRETATION"],
                LANDING_PAGE_HEADERS,
                [
                    "Brand | Core",
                    "/google/apex-jaipur",
                    "Is this Apex?",
                    "Apex Jaipur",
                    "Address",
                    "Call",
                    "Map",
                    "GCLID",
                    "BUILD",
                ],
                [
                    "Brand | Action",
                    "/google/book-apex-jaipur",
                    "Book now?",
                    "Book",
                    "Contact",
                    "Book",
                    "Form",
                    "GCLID",
                    "BUILD",
                ],
                [
                    "Neuro | Provider",
                    "/google/neurologist-jaipur",
                    "Which neurologist?",
                    "Neurology",
                    "Credentials",
                    "Book",
                    "Doctors",
                    "GCLID",
                    "BUILD",
                ],
            ],
            [
                ["SUPPORTING ASSETS — BUILD BEFORE LAUNCH"],
                ASSET_HEADERS,
                [
                    "Sitelink",
                    "Account",
                    "Book Appointment",
                    "/google/book-apex-jaipur",
                    "Request an OPD appointment",
                    "Contact Apex",
                    "APPROVED",
                ],
                ["Callout", "Account", "OPD Appointments", "—", "—", "—", "APPROVED"],
            ],
            [
                ["MEASUREMENT CONTRACT — DO NOT LET GOOGLE OPTIMISE TO THE WRONG THING"],
                MEASUREMENT_HEADERS,
                [
                    "Primary conversion",
                    "Qualified Lead only; standard goal selected for bidding",
                    "REQUIRED",
                    "Gaurav",
                    "Screenshot",
                    "Business rule",
                ],
                [
                    "Click identity",
                    "Auto-tagging ON; preserve GCLID",
                    "REQUIRED",
                    "Tech",
                    "Test lead",
                    "GCLID is case-sensitive",
                ],
            ],
            _rsa_block(headline_count, description_count, extra_registry_column, long_headline),
        ]
    )
    return blocks


def _rsa_block(
    headline_count: int, description_count: int, extra_column: bool, long_headline: bool = False
) -> Block:
    headers = ["Campaign", "Ad group"]
    headers += [f"H{n}" for n in range(1, headline_count + 1)]
    headers += [f"D{n}" for n in range(1, description_count + 1)]
    if extra_column:
        headers.append("Reviewer notes")

    def ad(campaign: str, ad_group: str, tag: str) -> Row:
        row: Row = [campaign, ad_group]
        row += [
            (
                f"{tag} headline {n}"
                if not (long_headline and n == 1)
                else "This headline is far too long for Google Ads"
            )
            for n in range(1, headline_count + 1)
        ]
        row += [f"{tag} description {n}" for n in range(1, description_count + 1)]
        if extra_column:
            # Deliberately EMPTY: an unread notes column is an INFO, a populated one is a
            # blocker (ING-102), and the two cases need separate fixtures.
            row.append("")
        return row

    return [
        ["RSA 1 — DISTINCT COPY PER AD GROUP · 12 HEADLINES + 4 DESCRIPTIONS"],
        headers,
        ad(BRAND, "Brand | Core", "Core"),
        ad(BRAND, "Brand | Action", "Action"),
        ad(NEURO, "Neuro | Provider", "Neuro"),
    ]


def _keywords_sheet(
    *,
    keyword_type: str = "Keyword",
    keyword_match: str = "Phrase",
    keyword_copy_paste: str | None = None,
    extra_negatives: list[tuple[str, str, str, str]] | None = None,
) -> list[Block]:
    return [
        [["APEX · TEST KEYWORDS + NEGATIVES"]],
        [
            REGISTRY_HEADERS,
            _registry(
                BRAND,
                "Brand | Core",
                "Ad group",
                keyword_type,
                keyword_match,
                "apex hospital",
                keyword_copy_paste or _derived("apex hospital", keyword_match),
                "—",
            ),
            _registry(
                BRAND,
                "Brand | Core",
                "Ad group",
                keyword_type,
                "Exact",
                "apex hospital",
                "[apex hospital]",
                "—",
            ),
            _registry(
                NEURO,
                "Neuro | Provider",
                "Ad group",
                keyword_type,
                "Phrase",
                "neurologist in jaipur",
                '"neurologist in jaipur"',
                "—",
            ),
            _registry(
                BRAND,
                "Brand | Action",
                "Ad group",
                keyword_type,
                "Phrase",
                "apex hospital appointment",
                '"apex hospital appointment"',
                "—",
            ),
            _registry("—", "—", "Account", "Negative", "Broad", "job", "job", "ACCOUNT_JUNK"),
            _registry(
                "—", "—", "Account", "Negative", "Broad", "vacancy", "vacancy", "OUTSIDE_GEO"
            ),
            _registry(
                "—",
                "—",
                "Shared list → Neuro",
                "Negative",
                "Phrase",
                "apex hospital",
                '"apex hospital"',
                "ROUTE_BRAND",
            ),
            _registry(
                "—",
                "—",
                f"Campaign: {NEURO}",
                "Negative",
                "Phrase",
                "orthopedic",
                '"orthopedic"',
                "GENERIC_EXCLUDE_SPECIALTY",
            ),
            _registry(
                NEURO,
                "Neuro | Provider",
                "Ad group",
                "Negative",
                "Phrase",
                "knee replacement",
                '"knee replacement"',
                "ORTHO_PROVIDER_TO_KNEE",
            ),
            *[
                _registry("—", "—", scope, "Negative", match, text, _derived(text, match), name)
                for scope, match, text, name in (extra_negatives or ())
            ],
        ],
    ]


def _daily_sheet() -> list[Block]:
    return [
        [["APEX · TEST DAILY"]],
        [
            DAILY_HEADERS,
            ["2026-08-27", BRAND, 164.47, "", "", "", "", "Nothing", "", "", "", ""],
            ["2026-08-27", NEURO, 657.89, "", "", "", "", "Nothing", "", "", "", ""],
        ],
    ]


def _write(path: Path, sheets: dict[str, list[Block]], *, shift: int = 0) -> Path:
    book = Workbook()
    book.remove(book.active)
    for name, blocks in sheets.items():
        sheet = book.create_sheet(title=name)
        for index, block in enumerate(blocks):
            if shift and index:
                for _ in range(shift):
                    sheet.append([])
            for row in block:
                sheet.append(row)
            sheet.append([])
    book.save(path)
    return path


def _sheets(**kwargs: Any) -> dict[str, list[Block]]:
    """Assemble one workbook. Unknown keyword arguments are a typo, not a silent no-op."""
    build_parameters = set(inspect.signature(_build_sheet).parameters)
    known = build_parameters | {
        "red_status",
        "keyword_type",
        "keyword_match",
        "keyword_copy_paste",
        "extra_negatives",
    }
    unknown = set(kwargs) - known
    if unknown:
        raise TypeError(f"unknown fixture option(s): {sorted(unknown)}")

    build_kwargs = {key: value for key, value in kwargs.items() if key in build_parameters}
    return {
        "01 ACTIONS": _actions_sheet(red_status=kwargs.get("red_status", "Done")),
        "02 BUILD": _build_sheet(**build_kwargs),
        "03 KEYWORDS": _keywords_sheet(
            keyword_type=kwargs.get("keyword_type", "Keyword"),
            keyword_match=kwargs.get("keyword_match", "Phrase"),
            keyword_copy_paste=kwargs.get("keyword_copy_paste"),
            extra_negatives=kwargs.get("extra_negatives"),
        ),
        "04 DAILY": _daily_sheet(),
    }


def build_all(directory: Path) -> dict[str, Path]:
    """Write every fixture into `directory` and return `{name: path}`."""
    directory.mkdir(parents=True, exist_ok=True)
    fixtures = {
        "clean": (_sheets(), 0),
        "shifted": (_sheets(), 3),
        "missing_section": (_sheets(include_ad_groups=False), 0),
        "renamed_column": (_sheets(campaign_budget_header="Monthly budgets"), 0),
        "wide_rsa": (_sheets(headline_count=5, description_count=2, extra_registry_column=True), 0),
        "malformed_currency": (_sheets(monthly_budget="₹ twenty thousand"), 0),
        "malformed_keyword_row": (_sheets(keyword_type="Kyeword"), 0),
        "budget_mismatch": (_sheets(monthly_budget=19000, declared_total=24000), 0),
        "open_red_action": (_sheets(red_status="Open"), 0),
        "duplicate_ad_group_name": (_sheets(duplicate_ad_group_name=True), 0),
        # Phase 3
        "broad_positive": (_sheets(keyword_match="Broad"), 0),
        "modified_broad": (_sheets(keyword_match="Modified Broad"), 0),
        "copy_paste_mismatch": (_sheets(keyword_copy_paste="[apex hospital]"), 0),
        "collision_account": (
            _sheets(extra_negatives=[("Account", "Broad", "apex", "ACCOUNT_JUNK")]),
            0,
        ),
        "collision_campaign": (
            _sheets(
                extra_negatives=[
                    (f"Campaign: {NEURO}", "Phrase", "neurologist", "GENERIC_EXCLUDE_SPECIALTY")
                ]
            ),
            0,
        ),
        "collision_other_campaign": (
            _sheets(
                extra_negatives=[
                    (f"Campaign: {BRAND}", "Phrase", "neurologist", "GENERIC_EXCLUDE_SPECIALTY")
                ]
            ),
            0,
        ),
        "collision_shared_applied": (
            _sheets(
                extra_negatives=[("Shared list → Neuro", "Phrase", "neurologist", "ROUTE_BRAND")]
            ),
            0,
        ),
        "collision_shared_not_applied": (
            _sheets(
                extra_negatives=[("Shared list → Brand", "Phrase", "neurologist", "ROUTE_BRAND")]
            ),
            0,
        ),
        "unknown_scope_alias": (
            _sheets(
                extra_negatives=[("Shared list → Cardio", "Phrase", "cardiologist", "ROUTE_BRAND")]
            ),
            0,
        ),
        "populated_unknown_column": (_sheets(unknown_campaign_column=True), 0),
        "duplicate_column": (_sheets(duplicate_campaign_column=True), 0),
        "long_headline": (_sheets(long_headline=True), 0),
        "real_call_number": (
            _sheets(call_number="+91 141 000 0000", call_schedule="Mon-Sat 08:00-20:00 IST"),
            0,
        ),
        "search_partners_on": (_sheets(networks="Google Search · Partners ON · Display OFF"), 0),
        "routing_mismatch": (
            _sheets(extra_negatives=[("Shared list → Brand", "Phrase", "zzz", "ROUTE_BRAND")]),
            0,
        ),
        # An account-wide number plus one ad-group exception: the fixture that proves the
        # number validated is the number rendered, whichever level supplied it.
        # Monthly budget correct, daily cell wrong: BUD-004 warns and CMP-101 records
        # that the DERIVED figure is what gets exported. Copying the cell through was the
        # most dangerous defect this repo has had.
        "wrong_daily_budget": (
            _sheets(
                brand_daily_budget=999.99,
                call_number="+91 141 000 0000",
                call_schedule="Mon-Sat 08:00-20:00 IST",
            ),
            0,
        ),
        # The registry exists, carries a deliberate override, and one required heading is
        # misspelled. This must BLOCK, not quietly fall back to the campaign row.
        "call_asset_registry_malformed": (
            _sheets(
                call_number="+91 141 000 0000",
                call_schedule="Mon-Sat 08:00-20:00 IST",
                registry_header_typo=True,
                call_asset_registry=[
                    [
                        "AD_GROUP",
                        NEURO,
                        "Neuro | Provider",
                        "+91 141 222 2222",
                        "24x7 neuro coordinator",
                        "APPROVED",
                        "staffed specialty line",
                    ],
                ],
            ),
            0,
        ),
        "call_asset_override": (
            _sheets(
                call_number="+91 141 000 0000",
                call_schedule="Mon-Sat 08:00-20:00 IST",
                call_asset_registry=[
                    [
                        "AD_GROUP",
                        NEURO,
                        "Neuro | Provider",
                        "+91 141 222 2222",
                        "24x7 neuro coordinator",
                        "APPROVED",
                        "staffed specialty line",
                    ],
                ],
            ),
            0,
        ),
    }
    return {
        name: _write(directory / f"wb_{name}.xlsx", sheets, shift=shift)
        for name, (sheets, shift) in fixtures.items()
    }


if __name__ == "__main__":
    written = build_all(Path(__file__).parent / "generated")
    for name, path in written.items():
        print(f"{name:<24} {path}")
