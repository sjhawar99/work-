# Apex Google Ads Operating System — Codex Build Specification

**Version:** 1.0
**Status:** Specification frozen for Phase 0–7 implementation
**Audience:** A coding agent (Codex / Claude Code) and the human reviewing its output

---

## 0. How to read this document

This is a build contract, not a strategy deck. Everything in it is meant to be
implementable and testable.

- **MUST / MUST NOT** — a hard requirement. A violation is a bug, and in most cases
  there is a named acceptance test in §19 that will catch it.
- **SHOULD** — the strong default. Deviating requires a note in the PR description.
- **MAY** — genuinely optional.

Numeric thresholds shown in this document (budgets, character limits, ratios) are
**illustrative defaults that live in `config/rules.yaml`**. They MUST NOT be hard-coded
in Python. If you find yourself typing `62000` or `30` into a module, you are writing
the wrong file.

---

## 1. Purpose and scope

Apex runs its Google Ads account from an Excel workbook. The workbook encodes the
approved strategy: campaign structure, budget split, keyword and match-type policy,
negatives, ad copy, landing pages, tracking, and the weekly review loop.

Today that workbook is translated into a live account **by hand**. Manual translation
is where the account acquires its defects: a Broad match that nobody approved, a budget
that drifts, a negative keyword that silently blocks a keyword we are paying for, an ad
group with no call number, a landing page that 404s.

This system removes the manual translation step and replaces it with three programs:

| Pillar | When | Input | Output |
| --- | --- | --- | --- |
| **Build Compiler** | Pre-launch, and on every structural change | Workbook `.xlsx` | Google Ads Editor import CSVs + `PRE_FLIGHT_REPORT.txt` |
| **Search-Term Watchdog** | Weekly, post-launch | Search-terms export `.csv` + workbook | Analysis, **negative-policy observations**, routing issues, actions report. It does not author negative policy (§13.5, amended) |
| **Account Drift Checker** | Weekly, post-launch | Live Editor export + workbook | Drift report: approved vs actual |

Scope of v1 is deliberately narrow: **files in, files out.** No Google Ads API. No
automatic uploads. No autonomous account management.

### 1.1 The design principle

> The workbook remains the team's operating interface. The code becomes an invisible
> enforcement layer around it.

Nobody on the marketing side should have to learn a new tool to benefit from this
system. They edit the workbook exactly as they do today. The compiler is the thing that
refuses to let a bad workbook become a live account.

---

## 2. Non-goals for v1

The following are explicitly out of scope. Implementing any of them without a spec
revision is a defect, not initiative.

1. **No Google Ads API integration.** No OAuth, no `google-ads` client library, no
   uploads, no mutate calls. Deployment happens through Google Ads Editor, driven by a
   human.
2. **No campaign enabling.** Everything the compiler emits is `PAUSED`. Enabling is a
   human action taken in the Google Ads UI after QA.
3. **No automatic negative application.** The Watchdog *suggests*. A human approves.
   The next compiler run applies what the human wrote back into the workbook.
4. **No bid management, no budget optimisation, no seasonality modelling.**
5. **No writes to the source workbook.** The compiler is read-only against `input/`.
   Watchdog "write-back" is a separate, explicitly-invoked command that emits a *new*
   file, never an in-place edit (§13.7).
6. **No replacement of human judgement on ad copy.** The compiler validates copy; it
   does not generate or rewrite it.
7. **No CRM / revenue attribution.** That is a later system that consumes these outputs.

---

## 3. Vocabulary

| Term | Meaning |
| --- | --- |
| **Workbook** | The Apex Google Ads OS Excel file. The single source of truth. |
| **Desired state** | What the workbook says the account should be. |
| **Live state** | What the account actually is, observed via a Google Ads Editor export. |
| **Drift** | A difference between desired and live state. |
| **Blocker** | A validation failure that stops the build. No output files are produced. |
| **Warning** | A validation failure that is reported but does not stop the build. |
| **Info** | An observation, for the record. |
| **Pre-flight** | The full validation pass that runs before any file is written. |
| **Fail closed** | On any BLOCKER, or on any unexpected exception, produce no deployable artifacts. |
| **Routing** | Which campaign/ad group a search term *should* have been served by. |
| **Leakage** | A search term served by the wrong campaign/ad group. |
| **Collision** | A negative keyword that would block a positive keyword we deliberately buy. |

---

## 4. The workbook: source-of-truth contract

### 4.1 Operating sheets

The current operating workbook (`APEX_Google_Ads_Operating_System_v1.1.xlsx`) is
organised around four working sheets:

| Sheet | Meaning | Role in the pipeline |
| --- | --- | --- |
| `01 ACTIONS` | What needs doing — open items, owners, severity, sign-off | Read for open BLOCKER-severity items (§9.9); written to by the Watchdog write-back |
| `02 BUILD` | Desired Google Ads state — campaigns, ad groups, budgets, settings, ads, landing pages, extensions, tracking | Primary compiler input |
| `03 KEYWORDS` | What we buy and what we block — positives with match types, negatives with scope | Primary compiler input |
| `04 DAILY` | What happened — daily/weekly performance log | Watchdog context only; never affects the build |

### 4.2 Capability areas are not sheets

**DECISION A1 (locked).** There is exactly one source-of-truth workbook,
`APEX_Google_Ads_Operating_System_v1.1.xlsx`, and it has exactly the four sheets above.
The parser MUST read only those four sheets.

An earlier architecture document described eleven areas — Setup, Campaign Blueprint,
Keyword Map, Ads, Landing Pages, Extensions, Negative Keywords, Tracking, Budget,
Search-Term Monitor, Review/Sign-off. Those are **capabilities of this software**, not
Excel tabs. No workbook with eleven tabs exists or will exist. Looking for one is an
excellent way to spend half a day debugging a file that has never existed.

Each capability lives inside one of the four real sheets:

| Capability | Lives in |
| --- | --- |
| Setup / account defaults | `02 BUILD` |
| Campaign blueprint, budget split | `02 BUILD` |
| Keyword map | `03 KEYWORDS` |
| Ads / RSA assets | `02 BUILD` |
| Landing pages | `02 BUILD` |
| Extensions and call assets | `02 BUILD` |
| Negative keywords | `03 KEYWORDS` |
| Tracking and conversions | `02 BUILD` |
| Budget guide | `02 BUILD` |
| Search-term monitor | `04 DAILY` (log) + Watchdog outputs |
| Review / sign-off | `01 ACTIONS` |

**Implementation consequence:** the parser is driven by a *section registry* in
`config/workbook_schema.yaml` mapping a logical section to (sheet, section header text,
required columns). Each section names exactly one sheet. Moving a section between sheets
is a config change, not a code change — but inventing a sheet is neither.

### 4.3 Parsing contract (non-negotiable)

1. **Header-driven, never row-index-driven.** Locate a section by scanning for its
   header text; locate a column by matching its header cell. `df.iloc[7]` is forbidden.
   Humans insert rows. Row numbers are a lie waiting to happen.
2. **Column matching is normalised**: case-insensitive, whitespace-collapsed,
   punctuation-stripped comparison. `Net Daily Budget`, `net daily budget` and
   `Net  Daily  Budget ` are the same column.
3. **Required columns missing → BLOCKER**, naming the sheet, the section and the exact
   missing column. Never guess a column by position.
4. **Unknown extra columns are ignored** and reported once as INFO. Humans add notes
   columns; that is not an error.
5. **Blank rows terminate a section.** Two consecutive fully-blank rows end the block.
6. **Every parsed record carries provenance**: `sheet`, `row_number`, `section`. Every
   validation finding MUST cite that provenance so a human can open the workbook and go
   straight to the offending cell.
7. **Type coercion is explicit and total.** Currency strings (`₹10,000`, `Rs 10000`,
   `10,000.00`) parse to `Decimal`. Percentages (`35%`, `0.35`) parse to `Decimal`
   fractions. Booleans (`Y`, `Yes`, `TRUE`, `✅`) parse to `bool`. Anything unparseable
   is a BLOCKER naming the cell — never a silent `NaN`, never a silent `0`.
8. **Read-only.** The workbook file is opened read-only and its SHA-256 is recorded in
   the run manifest (§10.6).

### 4.4 Google Sheets as the editing surface

The team may edit the workbook in Google Sheets rather than desktop Excel. Nothing in the
parser cares: **File → Download → Microsoft Excel (.xlsx)** into `input/workbook.xlsx`
and every rule in this document applies unchanged. That is the supported v1 path, and it
keeps the guarantee in §16 that this tool holds no credentials of any kind.

Direct Sheets API reading is deliberately **not** in v1. It would require a Google Cloud
project, a service account and a stored key — the exact class of thing §16.2 forbids —
in exchange for saving one menu click.

#### The source-of-edits rule (non-negotiable)

> **All human edits happen in the canonical Google Sheet.**
> **`input/workbook.xlsx` is an export artifact and must never be edited directly.**

An edit made in the exported `.xlsx` is invisible to the team, absent from the Sheet's
revision history, and silently destroyed by the next export. Anyone who "just fixed one
cell" in the export has forked the source of truth without telling anyone.

This rule is human policy — the software cannot enforce it, and must not pretend to.
It appears in `AGENTS.md`, in `MANUAL_STEPS.md`, and in every report header.

#### Staleness is advisory only

The real risk of the Sheets path is that someone edits the Sheet, forgets to re-export,
and the compiler faithfully builds last week's plan.

| ID | Severity | Rule |
| --- | --- | --- |
| `WB-001` | WARNING (advisory) | The local export file is older than `workbook.export_staleness_warning_days`. |
| `WB-002` | INFO | Every report header prints the export's file modification time next to its SHA-256, so "which version was this?" is answerable from the artifact alone. |

**What `WB-001` is not.** It measures **the age of the local export file, nothing else.**
It is *not* evidence that `input/workbook.xlsx` matches the current Google Sheet, and it
must never be described, logged or reported as if it were:

- A fresh export of a stale Sheet passes `WB-001` and is still current. Fine.
- An export taken five minutes ago from a Sheet edited four minutes ago passes `WB-001`
  and is already **wrong**. `WB-001` cannot see that.
- An export from three weeks ago whose Sheet nobody has touched warns, and is perfectly
  correct.

Without reading the Sheet — which v1 deliberately cannot do, because that needs stored
credentials (§16.2) — no local check can establish agreement between the two. The honest
framing is "this file is N days old, confirm it is the export you meant", and the report
wording MUST stay that modest. Reporting a passing `WB-001` as "workbook up to date"
would be exactly the false assurance §18.13 forbids.

If Apex later wants live Sheets reading, it is a self-contained phase with its own spec
section covering read-only scope, key storage and failure behaviour — not a quiet
addition to the ingest layer.

---

## 5. Repository layout

```
apex-google-ads-os/
├── AGENTS.md                     # short agent rules
├── CODEX_TASKS.md                # sequential implementation tasks
├── README.md
├── pyproject.toml
├── config/
│   ├── rules.yaml                # all business thresholds
│   ├── workbook_schema.yaml      # sheet/section/column registry
│   └── editor_schema.yaml        # Google Ads Editor CSV column maps
├── docs/
│   ├── CODEX_BUILD_SPEC.md       # this document
│   └── CODEX_KICKOFF_PROMPT.md
├── input/                        # manual inputs (git-ignored)
│   ├── workbook.xlsx
│   ├── search_terms/              # weekly exports, newest wins
│   └── live_export/              # Google Ads Editor export for drift checks
├── output/                       # generated; git-ignored
│   ├── build/<run_id>/
│   ├── watchdog/<run_id>/
│   └── drift/<run_id>/
├── logs/
├── src/apex_ads/
│   ├── __init__.py
│   ├── cli.py                    # argparse entry point
│   ├── models/                   # pydantic models (§7)
│   ├── ingest/                   # workbook + CSV readers (§4, §13.1)
│   ├── validate/                 # validator framework + rules (§9)
│   ├── compile_/                 # transform + Editor export (§10, §11)
│   ├── watchdog/                 # search-term pipeline (§13)
│   ├── drift/                    # desired-vs-live diff (§14)
│   ├── report/                   # pre-flight, actions, dashboard renderers
│   └── util/                     # currency, text, url, hashing, logging
└── tests/
    ├── fixtures/                 # golden workbooks + expected outputs
    ├── unit/
    ├── integration/
    └── golden/
```

`src/` layout with `pyproject.toml`; the package is installed in editable mode
(`pip install -e .`) so imports are `from apex_ads...` everywhere. No `sys.path` hacks.

---

## 6. Technology stack

| Concern | Choice | Note |
| --- | --- | --- |
| Language | Python 3.10+ | Target 3.11 in CI |
| Excel read | `openpyxl` (via `pandas.read_excel`) | `data_only=True` — we want values, not formulas |
| Data frames | `pandas` | Ingest and tabular transforms only; models are the contract |
| Validation | `pydantic` v2 | All records are models before any rule runs |
| Rules config | `PyYAML` | `config/*.yaml` |
| URL checks | `requests` + bounded retry | Opt-in, network-dependent (§9.6) |
| CSV export | `csv` stdlib / `pandas` | UTF-8 with BOM for Editor compatibility (§11.2) |
| CLI | `argparse` | No heavyweight CLI framework needed |
| Tables in reports | `tabulate` | Plain-text pre-flight report |
| Optional dashboard | `jinja2` | Single self-contained HTML file |
| Logging | stdlib `logging` | JSON lines to `logs/`, human text to stderr |
| Tests | `pytest` | Golden-file driven |
| Lint / format | `ruff` | `ruff check` + `ruff format` in CI |
| Types | `mypy` | Strict on `src/apex_ads/models` and `validate` |

No dependency may be added without a line in `pyproject.toml` and a sentence in the PR
saying why. Keep the tree small enough that a marketing-ops laptop can run it.

---

## 7. Data model

All models are `pydantic` v2, in `src/apex_ads/models/`. Every model inherits a
`Provenance` mixin carrying `sheet: str`, `row: int`, `section: str`.

```python
class Provenance(BaseModel):
    sheet: str
    row: int
    section: str

class Account(Provenance):
    account_name: str
    currency: str = "INR"
    monthly_budget: Decimal
    timezone: str
    brand_terms: list[str]
    default_final_url_suffix: str | None = None

class Campaign(Provenance):
    name: str                      # "MLN | Search | Ortho | Jaipur"
    channel: Literal["SEARCH"]     # v1 is Search only
    status: Literal["PAUSED"]      # compiler forces PAUSED; see §18
    daily_budget: Decimal
    budget_share: Decimal | None   # fraction of monthly budget
    bid_strategy: str
    locations: list[str]
    languages: list[str]
    ad_schedule: list[AdSchedule]
    search_partners: bool = False
    display_expansion: bool = False
    conversion_goals: list[str]
    tracking_template: str | None

class AdGroup(Provenance):
    campaign: str
    name: str
    default_max_cpc: Decimal | None
    final_url: HttpUrl
    theme: str                     # specialty / intent theme, used by the Watchdog

class Keyword(Provenance):
    campaign: str
    ad_group: str
    text: str
    match_type: Literal["EXACT", "PHRASE", "BROAD"]
    max_cpc: Decimal | None
    final_url: HttpUrl | None

class Negative(Provenance):
    level: Literal["ACCOUNT", "CAMPAIGN", "AD_GROUP", "SHARED_LIST"]
    campaign: str | None          # required for CAMPAIGN / AD_GROUP
    ad_group: str | None          # required for AD_GROUP
    text: str
    match_type: Literal["EXACT", "PHRASE", "BROAD"]
    list_name: str | None         # required for SHARED_LIST

class NegativeList(Provenance):
    """A shared negative list and the campaigns it is applied to (Decision A4)."""
    name: str                     # e.g. "ROUTE_COMPETITORS"
    applied_to: list[str]         # campaign names; empty list is a BLOCKER (NEG-006)

class CallAsset(Provenance):
    """Decision A5: one default number, optional overrides. Most specific wins."""
    level: Literal["ACCOUNT", "CAMPAIGN", "AD_GROUP"]
    campaign: str | None
    ad_group: str | None
    country_code: str = "IN"
    number: str
    schedule: str

class ResponsiveSearchAd(Provenance):class ResponsiveSearchAd(Provenance):
    campaign: str
    ad_group: str
    headlines: list[str]           # 3–15
    descriptions: list[str]        # 2–4
    final_url: HttpUrl
    path1: str | None
    path2: str | None
    pinned: dict[str, int] | None

class Extension(Provenance):
    level: Literal["ACCOUNT", "CAMPAIGN", "AD_GROUP"]
    campaign: str | None
    ad_group: str | None
    kind: Literal["SITELINK", "CALLOUT", "STRUCTURED_SNIPPET", "CALL", "LOCATION"]
    payload: dict[str, str]

class Conversion(Provenance):
    name: str
    category: str
    value: Decimal | None
    counting: Literal["ONE", "EVERY"]
    primary: bool

class ActionItem(Provenance):
    id: str
    description: str
    owner: str
    severity: Literal["RED", "AMBER", "GREEN"]
    status: Literal["OPEN", "DONE", "WAIVED"]
    waiver_reason: str | None

class WorkbookBundle(BaseModel):
    """Everything parsed from one workbook, plus the file hash."""
    source_path: Path
    source_sha256: str
    account: Account
    campaigns: list[Campaign]
    ad_groups: list[AdGroup]
    keywords: list[Keyword]
    negatives: list[Negative]
    negative_lists: list[NegativeList]
    call_assets: list[CallAsset]
    ads: list[ResponsiveSearchAd]
    extensions: list[Extension]
    conversions: list[Conversion]
    actions: list[ActionItem]
```

### 7.1 Findings

```python
class Severity(StrEnum):
    BLOCKER = "BLOCKER"   # build fails, no files written
    WARNING = "WARNING"   # build proceeds, fix recommended
    INFO    = "INFO"      # for the record

class Finding(BaseModel):
    rule_id: str          # "KW-002"
    severity: Severity
    message: str          # one line, specific, no jargon
    sheet: str
    row: int | None
    entity: str | None    # "MLN | Search | Ortho | Jaipur / Ortho — Knee"
    remedy: str           # what the human should actually change
```

`rule_id` is stable forever. Reports, tests and human conversation all key off it.
Never renumber a rule; retire it instead.

---

## 8. Configuration

### 8.1 `config/rules.yaml`

Every business threshold lives here, with two deliberate exceptions noted in §8.4. The
file shipped in this repo carries the decisions locked in `DECISIONS.md`; read the file
itself for authoritative values. Shape:

```yaml
account:
  currency: INR
  monthly_budget: 62000            # Stage-1 invariant, exact
  expected_campaign_count: 5       # Stage-1 invariant, exact
  expected_ad_group_count: 9       # Stage-1 invariant, exact
  primary_domain: apexhospitals.com

keywords:
  allowed_match_types: [EXACT, PHRASE]     # BROAD positives blocked

negatives:
  use_shared_lists: true
  shared_lists:                    # Decision A4 — declared, scope-aware
    ROUTE_COMPETITORS: {applies_to: [ ... campaign names ... ]}

call_assets:
  default:
    country: IN
    number: "REQUIRED"             # must be filled before first build
    schedule: "REQUIRED"
  overrides:
    campaigns: {}
    ad_groups: {}

landing_pages:
  allowed_domains: [apexhospitals.com, www.apexhospitals.com]
  extra_allowed_domains: []        # explicit whitelist, reviewed per entry
  follow_redirects: true
  max_redirect_depth: 5
  googleadsbot_retry: true
  unknown_blocks_ready_build: true # UNKNOWN is never PASS

watchdog:
  input_dir: input/search_terms/
  cadence: weekly-friday
  lookback_days: 7
```

### 8.4 What is deliberately NOT configurable

Two policies are hard-coded in Python, on purpose, because a YAML file is too easy to
edit and both are safety rails rather than tuning knobs:

1. **`Modified Broad` → `PHRASE`** (Decision A3). There is no config key that could point
   this at `BROAD`.
2. **The waivable-rule list, which in Stage 1 is empty** (§9.9). No workbook row can
   suppress a validation rule.

### 8.2 `config/workbook_schema.yaml`

Maps logical sections to where they live. One entry per section:

```yaml
sections:
  campaigns:
    sheet: ["02 BUILD", "01 CAMPAIGN BLUEPRINT"]     # first match wins
    header_contains: "CAMPAIGN"
    required_columns: [campaign, daily budget, bid strategy, locations]
    optional_columns: [notes, owner]
```

### 8.3 `config/editor_schema.yaml`

Maps our model fields to Google Ads Editor CSV column headers, per entity type, plus
the list of fields Editor cannot safely encode (§11.4).

**Rule:** if a validator, compiler or watchdog module needs a number, a limit, a
threshold, a column name or a regex, it reads it from config. Code contains logic;
config contains policy.

---

## 9. Validation framework

### 9.1 Validator interface

```python
class Validator(Protocol):
    rule_id: str
    severity: Severity          # default severity; a rule may downgrade per-finding
    def check(self, wb: WorkbookBundle, cfg: Config) -> Iterable[Finding]: ...
```

Validators are registered in `src/apex_ads/validate/registry.py`. Each lives in its own
module, is independently unit-testable, and MUST NOT mutate the bundle. The runner
executes **every** validator and collects **every** finding — it MUST NOT stop at the
first BLOCKER. A human fixing the workbook wants the whole list, not a game of
whack-a-mole.

### 9.2 Severity model

| Severity | Effect | Symbol in report |
| --- | --- | --- |
| `BLOCKER` | Build fails. No deployable files are written. Exit code 2. | ❌ |
| `WARNING` | Build proceeds. Listed prominently in the report. Exit code 0. | ⚠️ |
| `INFO` | Recorded in the report appendix. | ✅ / ℹ️ |

There is **no `--force`**. A BLOCKER is resolved by fixing the workbook, or by an
explicit, signed waiver row in `01 ACTIONS` (§9.9) — which is itself a workbook change,
visible in review, and recorded in the report.

### 9.3 Budget and structure rules

Decision A2 makes the three headline figures **Stage-1 invariants**: they are exact, and
they are not waivable. If the strategy legitimately changes, `config/rules.yaml` changes
and a human approves that change — the build is not talked around.

| ID | Severity | Rule |
| --- | --- | --- |
| `BUD-001` | BLOCKER | Sum of campaign monthly budgets equals `account.monthly_budget` (₹62,000) exactly, within `budget_tolerance_pct` for rounding only. |
| `BUD-002` | BLOCKER | Every campaign has a positive daily budget; no zero, no blank, no negative. |
| `BUD-003` | BLOCKER | Declared budget split percentages sum to 100% (±0.5pp) and match the derived daily budgets. |
| `BUD-004` | WARNING | Daily budget × `days_per_month` deviates from the campaign's declared monthly share by more than tolerance. |
| `STR-001` | BLOCKER | Campaign count equals `expected_campaign_count` (5). Not waivable. |
| `STR-002` | BLOCKER | Ad-group count equals `expected_ad_group_count` (9). Not waivable. |
| `STR-003` | BLOCKER | Every ad group references an existing campaign; every keyword and ad references an existing ad group. No orphans. |
| `STR-004` | BLOCKER | Campaign names match `naming.campaign_pattern`. |
| `STR-005` | BLOCKER | No duplicate campaign names; no duplicate ad-group names within a campaign. |
| `STR-006` | BLOCKER | Every campaign's status compiles to `PAUSED`. |
| `STR-007` | WARNING | Every ad group contains at least `min_keywords_per_ad_group` keywords. |

### 9.4 Keyword rules

| ID | Severity | Rule |
| --- | --- | --- |
| `KW-001` | BLOCKER | No positive keyword compiles to `BROAD`. A workbook row saying `Broad` fails the build — it is not normalised, not downgraded, not warned about. Stage 1 buys Exact and Phrase only. |
| `KW-002` | BLOCKER | No keyword text appears in more than one ad group (`max_ad_groups_per_keyword`). Cross-ad-group duplication is self-competition. |
| `KW-003` | BLOCKER | No exact duplicate (text, match type) pair within an ad group. |
| `KW-004` | BLOCKER | Keyword text contains no invalid characters and is within Google's 80-character limit. |
| `KW-005` | WARNING | Near-duplicate keywords across ad groups (normalised: lowercase, punctuation stripped, word-order-insensitive). |
| `KW-006` | BLOCKER | Every keyword belongs to an ad group whose theme is declared in `02 BUILD`. |
| `KW-007` | WARNING | Keyword-level final URL, where present, resolves to the same domain as the ad-group final URL. |
| `KW-008` | WARNING | `Modified Broad` normalised to `PHRASE`. Finding code `LEGACY_MATCH_TYPE_NORMALIZED`. |
| `KW-009` | BLOCKER | The workbook's derived `COPY / PASTE VALUE` matches the value the compiler regenerates from `Keyword text` + `Match type` (`"text"` for Phrase, `[text]` for Exact, bare for Broad). |

**`KW-008` — Decision A3, implemented exactly:**

```python
if raw_match_type.casefold() in MODIFIED_BROAD_ALIASES:   # "modified broad", "bmm", "+modified"
    match_type = MatchType.PHRASE
    findings.append(Finding(
        rule_id="KW-008",
        severity=Severity.WARNING,
        message="LEGACY_MATCH_TYPE_NORMALIZED: Modified Broad is discontinued. "
                "Converted to Phrase.",
        ...
    ))
elif raw_match_type.casefold() == "broad":
    findings.append(Finding(rule_id="KW-001", severity=Severity.BLOCKER, ...))
```

The mapping is a module constant, **not** a config key (§8.4). Broad Match Modifier no
longer exists as a distinct match behaviour at Google — legacy BMM keywords behave as
Phrase, and new ones cannot be created — so normalising is correct and safe. An actual
`Broad` positive is a different thing entirely and still fails the build.

Leaving the two paths separate is the point: legacy nomenclature in the workbook does not
break the compiler, and a real Broad keyword does not sneak in behind a "we normalise
match types" rule.

### 9.5 Negative-keyword rules, scope hierarchy and collision semantics

**Decision A4: the hierarchy is hybrid and MUST be preserved.** Negatives are not
flattened to campaign level. Duplicating a hundred negatives across five campaigns is how
a negative set becomes unmaintainable and how one of the five copies quietly goes stale.

```
ACCOUNT                          universal, applies everywhere
├── ACCOUNT_JUNK
└── OUTSIDE_GEO

SHARED LISTS                     reusable, applied to selected campaigns only
├── ROUTE_BRAND
├── ROUTE_COMPETITORS
├── STAGE1_HOLD_COMPARISON
├── STAGE1_HOLD_ACTION
└── STAGE1_HOLD_URGENCY

CAMPAIGN                         one-off routing for a single campaign
└── GENERIC_EXCLUDE_SPECIALTY

AD GROUP                         intra-campaign routing
└── ORTHO_PROVIDER_TO_KNEE
```

| ID | Severity | Rule |
| --- | --- | --- |
| `NEG-001` | BLOCKER | No negative keyword blocks a positive keyword **within the negative's own scope**. See below. |
| `NEG-002` | BLOCKER | Every negative declares a valid level and, for `CAMPAIGN`/`AD_GROUP`/`SHARED_LIST`, an existing target. |
| `NEG-003` | BLOCKER | No exact duplicate negative at the same level and scope. |
| `NEG-004` | WARNING | A campaign-level or list negative is redundant because an identical account-level negative exists. |
| `NEG-005` | WARNING | The same negative appears in more than one shared list applied to the same campaign. |
| `NEG-006` | BLOCKER | Every declared shared list is applied to at least one campaign. An unapplied list does nothing and reads as protection that is not there. |
| `NEG-007` | BLOCKER | Every negative whose level is `SHARED_LIST` names a list declared in `config/rules.yaml → negatives.shared_lists`. |
| `NEG-008` | BLOCKER | The campaigns a shared list serves agree between the workbook's `Scope` cell and `rules.yaml → shared_lists.*.applies_to`. |

**On `NEG-008` — two sources, deliberately.** The real workbook encodes list application
inside the `Scope` column as a human sentence:

```
Shared list → Neuro, Generic, Ortho, Nephro
```

`rules.yaml` also declares `applies_to` as approved routing policy. These are not
redundant: config is what was *approved*, the workbook is what was *written*, and the
validator asserts they match. Disagreement is a BLOCKER naming both sides. The compiler
MUST NOT silently prefer one source — that would let routing policy drift in whichever
file nobody was reading.

**Collision semantics (`NEG-001`) — implement exactly this:**

A negative `N` collides with a positive keyword `K` when both hold:

1. **Scope overlap** — `N` must actually apply where `K` lives:
   - `N.level == ACCOUNT` → applies to every `K`.
   - `N.level == SHARED_LIST` → applies to `K` iff `K.campaign` is in that list's
     `applies_to` campaigns. **Resolve the list first, then compare.** This is the part
     that is easy to get wrong and expensive to get wrong.
   - `N.level == CAMPAIGN` → `N.campaign == K.campaign`.
   - `N.level == AD_GROUP` → `N.campaign == K.campaign` and `N.ad_group == K.ad_group`.
2. **Match semantics** — Google's negative-match rules, on normalised tokens (lowercase,
   trim, collapse whitespace, strip punctuation; **no close-variant or plural
   expansion** — negatives do not match close variants):
   - negative broad: every token of `N` appears in `K`'s tokens (order-independent).
   - negative phrase: `N`'s token sequence is a contiguous subsequence of `K`'s tokens.
   - negative exact: `N`'s token sequence equals `K`'s token sequence.

A negative is not dangerous because it *could* block some positive somewhere in the
account. It is dangerous when it blocks a positive **in a place where that negative
actually applies**. A validator that ignores scope produces a wall of false BLOCKERs, and
a wall of false BLOCKERs teaches everyone to stop reading the report.

Each collision is one BLOCKER finding naming: the negative (text, match, level, scope or
list name, sheet/row), the blocked keyword (text, match, campaign, ad group, sheet/row),
and the remedy (narrow the negative, move it down a level, remove the campaign from the
list's `applies_to`, or drop the positive).

This is the single highest-value check in the system: the defect class that is invisible
in the UI and expensive in the account. It gets its own test file
(`tests/unit/test_negative_collisions.py`) with, at minimum, a case per match type per
level, plus shared-list-applied and shared-list-not-applied cases.

### 9.6 Ads, assets and landing pages

| ID | Severity | Rule |
| --- | --- | --- |
| `AD-001` | BLOCKER | Headline count within `ads.headlines.min..max`. |
| `AD-002` | BLOCKER | Every headline ≤ `ads.headlines.max_chars`, measured after trimming. |
| `AD-003` | BLOCKER | Description count within `ads.descriptions.min..max`. |
| `AD-004` | BLOCKER | Every description ≤ `ads.descriptions.max_chars`. |
| `AD-005` | BLOCKER | Every ad group has at least one RSA with a final URL. |
| `AD-006` | BLOCKER | Every ad group resolves to exactly one call asset (`ads.require_resolved_call_asset`), with a schedule (`ads.require_call_asset_schedule`). See below. |
| `AD-007` | BLOCKER | No duplicate headline or description text within one RSA. |
| `AD-008` | WARNING | Business hours declared where `ads.require_business_hours` is set. |
| `AD-009` | BLOCKER | No special/unsupported characters; no emoji; no double spaces; no ALL-CAPS words beyond `ads.allowed_all_caps_tokens`. |
| `AD-010` | BLOCKER | Path fields ≤ `ads.paths.max_chars`. |
| `AD-011` | BLOCKER | No duplicate asset names across extensions. |
| `AD-012` | BLOCKER (READY builds only) | The resolved call number and schedule are real values, not one of `call_assets.placeholder_tokens`. |
| `AD-013` | BLOCKER (READY builds only) | Every supporting asset carries a status in `ads.approved_asset_statuses`. |
| `AD-014` | BLOCKER | `CALL ASSET REGISTRY` grammar: `ACCOUNT` requires campaign and ad group blank; `CAMPAIGN` requires a campaign and a blank ad group; `AD_GROUP` requires both. Targets must exist, a number and staffed schedule are required, and no two rows may govern the same effective scope. |
| `AD-015` | BLOCKER (READY builds only) | Every `CALL ASSET REGISTRY` row carries a status in `ads.approved_asset_statuses`. |

#### Call assets (`AD-006`, Decision A5)

Stage 1 uses **one default call number applied across all five campaigns**, with optional
overrides. Nine ad groups do not imply nine phone numbers; a number nobody answers is
worse than a number that is merely generic.

**The number itself is an approved account value and therefore lives in the workbook**,
not in config: `02 BUILD → CAMPAIGN SETTINGS`, columns `Call phone number` and
`Call schedule / reporting`. Today both hold placeholders (`[REQUIRED BEFORE LAUNCH]`,
`[REQUIRED] staffed days/hours …`). Config holds only the resolution rule and the
vocabulary of placeholder tokens:

```yaml
call_assets:
  resolution_order: [AD_GROUP, CAMPAIGN, ACCOUNT]
  placeholder_tokens: ["[REQUIRED]", "[REQUIRED BEFORE LAUNCH]", "REQUIRED", "TBD", "—"]
  placeholder_blocks_ready_build: true
```

Resolution is **most-specific-wins**, matching how Google resolves call assets across
account, campaign and ad-group levels: ad group → campaign → account. The validator
resolves an asset for every ad group and fails if the result is empty. It does not require
nine entries; it requires nine *resolutions*.

**Every level reads the workbook.** Exceptions live in an optional section of `02 BUILD`,
`CALL ASSET REGISTRY — NUMBER BY LEVEL`, with columns `Level`, `Campaign`, `Ad group`,
`Call phone number`, `Call schedule / reporting`, `Status`, `Why`. `Level` is `ACCOUNT`,
`CAMPAIGN` or `AD_GROUP`. The section is absent today, and absent means *no exceptions*:
all nine ad groups resolve through their campaign row. `AD-014` enforces a strict grammar over it and `AD-015`
requires an approving status. A row that targets nothing is not an override — it is an
override that silently did not happen; and a cell the machine ignores is a cell a human
will trust, so a row must never read narrower than it acts.

The section being optional means **absence is permitted**, never that broken data is
ignored: a registry that is present but malformed is a structural BLOCKER, because absent
means the human made no claim while malformed means they made one the machine could not
read.

An earlier version put the account default and the overrides in `rules.yaml`, where they
could hold a real phone number. That broke the layering rule and, more dangerously, gave
the system two answers to one question: `AD-006` and `AD-012` resolved the config
override, while `MANUAL_STEPS.md` printed the campaign row. With an override in play, the
number checked and the number an operator was told to type were different numbers, and
nothing in the system could notice.

`callassets.resolve()` is now the only producer of a `CallAsset`. `transform()` calls it
once, stores the result on `CompiledAccount.call_assets`, and `MANUAL_STEPS.md` and the
manifest render from that object. Nothing else may read `campaign.call_phone_number`
directly.

**A placeholder is not a parse error.** `AD-012` fires only when a build would otherwise
be `READY` — so Phases 0–3, fixture builds and `apex validate` all run fine against a
workbook whose number is still `[REQUIRED BEFORE LAUNCH]`, and a deployable build remains
impossible until a real number is filled in. Tests 37 and 38 prove both halves.

#### Landing pages

| ID | Severity | Rule |
| --- | --- | --- |
| `LP-001` | BLOCKER | Every final URL is a syntactically valid absolute `https://` URL ≤ `landing_pages.max_url_chars`. |
| `LP-002` | BLOCKER | Every ad group maps to exactly one landing page. |
| `LP-003` | BLOCKER | Every distinct final URL passes the reachability check below. |
| `LP-004` | BLOCKER | The **final** URL after redirects is on an allowed domain: `apexhospitals.com`, `www.apexhospitals.com`, or an entry explicitly listed in `landing_pages.extra_allowed_domains`. |

**`LP-003` reachability check — Decision A6, implement exactly this sequence per URL:**

```
 1. Parse the URL. Malformed → BLOCKER.
 2. Scheme must be https. Anything else → BLOCKER.
 3. Host must be on the allowed-domain list → else BLOCKER (LP-004).
 4. GET the URL (not HEAD — some servers lie about HEAD).
 5. Timeout: landing_pages.timeout_seconds (default 10s).
 6. Follow redirects.
 7. Cap redirect depth at landing_pages.max_redirect_depth (default 5).
    Exceeded, or a loop detected → BLOCKER.
 8. Final response status must be 200 → else BLOCKER, reporting the actual status.
 9. Final URL host must still be on the allowed-domain list → else BLOCKER.
10. On a non-200 or a connection failure, retry once with a GoogleAdsBot-style
    user agent before concluding. Some sites treat unknown agents differently
    from how they treat Google's crawler.
11. Record latency in seconds.
12. Record the final URL.
```

Each URL ends in exactly one of three states:

| State | Meaning | Effect |
| --- | --- | --- |
| `PASS` | 200, allowed domain, within redirect depth | none |
| `BLOCKER` | 404 / 403 / 5xx / redirect loop / off-domain redirect / bad scheme | build fails |
| `UNKNOWN` | the check could not be completed — no network, DNS failure, timeout after retry, or `--no-network` was passed | **no deployable build** (§10.5) |

**`UNKNOWN` is not `PASS`.** This is the rule that most invites a shortcut and most
deserves not to get one. Google disapproves ads whose destination is inaccessible —
404s, 403s, 5xx, and pages its crawler cannot reach — so a build produced without
verified destinations is a build that may be dead on arrival. It is worth twelve seconds
of waiting, and it stops us shipping ads to a page the web team renamed on Wednesday
afternoon.

Results are reported per URL in the pre-flight report (§12) with status, final URL and
latency. Checks are deduplicated per distinct URL and use `landing_pages.retries` with
exponential backoff.

### 9.7 Tracking and conversions

Auto-tagging and GCLID survival are load-bearing for Apex measurement. UTM parameters and
tracking templates are **not**, and must never block an otherwise valid campaign — a
build that fails because nobody added an unnecessary tracking template is beautiful
software producing the wrong outcome.

| ID | Severity | Rule |
| --- | --- | --- |
| `TRK-001` | BLOCKER | At least one primary conversion goal is defined, and the workbook's `MEASUREMENT CONTRACT` marks it Primary and selected for bidding. |
| `TRK-002` | BLOCKER | Every conversion goal referenced by a campaign exists in the measurement contract. |
| `TRK-003` | BLOCKER | Auto-tagging is declared ON (`tracking.require_auto_tagging`). |
| `TRK-004` | BLOCKER | GCLID preservation is declared for every landing page (`tracking.preserve_gclid`). |
| `TRK-005` | WARNING | A recommended UTM parameter is absent. Recommended, never required. |
| `TRK-006` | BLOCKER | **If** a tracking template is present, it is syntactically valid: balanced `{}`, contains `{lpurl}`, no spaces. Absent template → no finding. |
| `TRK-007` | BLOCKER | Enhanced Conversions is not enabled for health-related Qualified Lead data where the measurement contract marks it `LOCKED`. |

`TRK-006` is conditional on purpose. `tracking.tracking_template.required` is `false`;
`require_lpurl_if_present` is what makes a *present* template correct.

### 9.8 Settings hygiene

| ID | Severity | Rule |
| --- | --- | --- |
| `SET-001` | BLOCKER | `search_partners` is `false` on every campaign unless explicitly approved in the workbook. |
| `SET-002` | BLOCKER | Display expansion is off for Search campaigns. |
| `SET-003` | BLOCKER | Every campaign declares at least one location target and one language. |
| `SET-004` | WARNING | Ad schedule declared where the account requires business-hours-only serving. |

### 9.9 Action items and waivers

| ID | Severity | Rule |
| --- | --- | --- |
| `ACT-001` | BLOCKER | No `RED`-severity action item in `01 ACTIONS` is still `OPEN`. |
| `ACT-002` | WARNING | `AMBER` action items still open are listed in the report. |
| `ACT-003` | BLOCKER | A `WAIVED` action item has a non-empty `waiver_reason` and a named owner. |

**In Stage 1 the waivable-rule list is empty.** Decision A2 made the structural counts
invariants, which were the only rules a waiver was ever going to suppress. A waiver in
`01 ACTIONS` therefore records that a human consciously accepted an open item — it is an
audit trail, not an override. No workbook row can turn a BLOCKER off.

The allowlist is a constant in code, not config (§8.4), so widening it is a code review
rather than a YAML edit.

---

## 10. Build Compiler

### 10.1 Sequence

```
1. INGEST     read workbook (read-only) → WorkbookBundle, record source SHA-256
2. VALIDATE   run every validator → list[Finding]
3. GATE       any BLOCKER? → write PRE_FLIGHT_REPORT.txt, exit 2, write no CSVs
4. TRANSFORM  normalise, dedupe, derive IDs, force PAUSED, expand negatives
5. EXPORT     write Google Ads Editor CSVs + MANUAL_STEPS.md into output/build/<run_id>/
6. REPORT     write PRE_FLIGHT_REPORT.txt (PASS), manifest.json, run summary
```

Steps 1–3 MUST complete before any byte is written into the output directory.
The output directory for a run is created only at step 5.

### 10.2 Transform rules

1. **Normalise text**: trim, collapse internal whitespace, strip zero-width and
   non-breaking spaces, normalise unicode to NFKC. Never change case of ad copy.
2. **Deduplicate** exact-duplicate keywords, negatives and extensions; each removal is
   an INFO finding.
3. **Force status**: every campaign and ad group is emitted `Paused`. This is applied
   in the transform, and asserted again in the export writer. Two independent gates,
   deliberately.
4. **Derive daily budgets** where the workbook declares only a monthly split:
   `daily = round(monthly_share / 30.4, 2)`, rounded half-up, in `Decimal`.
5. **Expand negatives** to the level Editor requires: account-level negatives are
   emitted as a shared negative list plus its campaign associations; campaign- and
   ad-group-level negatives are emitted inline.
6. **Map identifiers**: campaign name, ad-group name, keyword text and match type form
   the natural keys. The compiler MUST NOT invent numeric IDs — Editor matches on names.
7. **Stable ordering**: every output file is sorted deterministically (campaign, then
   ad group, then text). Two runs over the same workbook produce byte-identical files.

### 10.3 Output files

Written to `output/build/<run_id>/`:

| File | Contents |
| --- | --- |
| `campaigns.csv` | Campaign-level rows: name, status, budget, bid strategy, locations, languages, networks, schedule, tracking template |
| `adgroups.csv` | Ad-group rows: campaign, ad group, status, default max CPC |
| `keywords.csv` | Positives: campaign, ad group, keyword, match type, max CPC, final URL |
| `account_negatives.csv` | Account-level negatives |
| `shared_negative_lists.csv` | Shared lists, their terms and the campaigns they serve |
| `campaign_negatives.csv` | Campaign-level negatives |
| `adgroup_negatives.csv` | Ad-group-level negatives |
| `ads_headlines.csv` | RSA headlines, one row per ad with numbered headline columns |
| `ads_descriptions.csv` | RSA descriptions, likewise |
| `extensions.csv` | Sitelinks, callouts, structured snippets, call extension |
| `PRE_FLIGHT_REPORT.txt` | Human-readable validation summary (§12) |
| `MANUAL_STEPS.md` | Everything Editor cannot encode (§11.4) |
| `manifest.json` | Run metadata and hashes (§10.6) |
| `findings.json` | Machine-readable findings, for CI and the dashboard |

Negatives are **four files, never one** (Decision A4). Flattening the hierarchy into a
single `negatives.csv`, or expanding a shared list's terms across its campaigns to make
importing easier, is forbidden — see `config/editor_schema.yaml → negative_artifacts`.
If the verified Editor schema cannot import shared-list creation and application, then
`shared_negative_lists.csv` becomes a human deployment artifact driven by
`MANUAL_STEPS.md`. That is an acceptable outcome; flattening is not.

`ads_headlines.csv` and `ads_descriptions.csv` are kept separate (matching the current
workbook's asset layout) even though Editor can accept a combined RSA row; the export
writer MAY additionally emit `ads_rsa.csv` in Editor's combined shape when
`editor_schema.yaml` declares it. If both are emitted, `MANUAL_STEPS.md` states which
one to import so nobody imports the same ad twice.

### 10.4 Run IDs

`<run_id>` is `YYYYMMDD-HHMMSS-<short-hash>` where the short hash is the first 8 hex
characters of the workbook SHA-256. Timestamps are UTC. Two runs from the same workbook
are therefore visibly related, and no run ever overwrites another.
`output/build/latest` is a symlink (or, on Windows, a copy of `manifest.json`)
pointing at the newest successful run.

### 10.5 Build outcomes and fail-closed behaviour

A run ends in exactly one of three outcomes. Only one of them produces files anybody may
import.

| Outcome | When | Output | Exit |
| --- | --- | --- | --- |
| `READY` | No BLOCKERs, and every landing-page URL returned `PASS` | Full CSV set in `output/build/<run_id>/`, `latest` pointer updated | 0 |
| `DRAFT` | No BLOCKERs, but one or more URLs are `UNKNOWN` (network unavailable, or `--no-network`) | CSVs written to `output/build/<run_id>.DRAFT/` plus a `DO_NOT_IMPORT.txt`; `latest` **not** updated | 6 |
| `FAILED` | Any BLOCKER | Report only. No CSVs. | 2 |

`DRAFT` exists so the toolchain can be developed and tested offline without ever
producing something that looks importable. A `DRAFT` directory is not a slightly worse
`READY` directory — it is quarantined by name, carries a file telling a human not to
import it, and is invisible to anything following `latest`.

Other failure behaviour:

- Any unhandled exception → catch at the CLI boundary, log the traceback to
  `logs/<run_id>.log`, print a short human message, exit 3, and **delete any partially
  written output directory**. A half-written export is worse than no export.
- Writing is staged: files are written to `output/build/<run_id>.partial/` and the
  directory is renamed to its final name on success. Readers never see a partial run.

### 10.6 Manifest

`manifest.json` records: `run_id`, UTC timestamp, tool version, git commit (if
available), workbook path and SHA-256, config file paths and their SHA-256s, counts
(campaigns, ad groups, keywords, negatives, ads, extensions), finding counts by
severity, per-output-file SHA-256, and whether network URL checks ran.

This makes any imported account state traceable back to an exact workbook and an exact
ruleset. When somebody asks "what did we import on the 14th and under which rules", the
manifest answers it.

---

## 11. Google Ads Editor export contract

### 11.1 Why Editor and not the API

Editor gives a human the review-before-post step that an API integration would remove.
The import is reviewed in Editor, `Check changes` surfaces errors before anything is
posted, and posting is a deliberate human click. That is exactly the control we want in
v1, and it is why §2 forbids API writes.

### 11.2 CSV mechanics

- Encoding: **UTF-8 with BOM** (`utf-8-sig`). Editor is happier with it, and Excel does
  not mangle `₹` on the way through.
- Line endings: `\r\n`.
- Quoting: `csv.QUOTE_MINIMAL`, `"` as the quote char, doubled to escape.
- Headers: exactly the English Editor column names from `config/editor_schema.yaml`.
  Editor imports keyed on English headers; do not translate or prettify them.
- One entity type per file. No blended sheets.
- Empty means "do not set". Never write `None`, `nan`, `NULL` or `-` into a cell.

### 11.3 Column mapping

`config/editor_schema.yaml` holds, per entity, an ordered list of
`{model_field, editor_column, required, transform}`. The writer is generic: it iterates
the schema, applies the named transform (`currency`, `match_type`, `status`, `bool_yes_no`,
`join_semicolon`), and writes the row. Adding a column is a YAML change.

Unknown or unmapped model fields MUST raise at export time (`UnmappedFieldError`) rather
than being dropped. Silent field-dropping is how a tracking template goes missing.

### 11.4 What Editor cannot safely encode → `MANUAL_STEPS.md`

Some settings either cannot be imported reliably, or are risky to import blind. These
MUST be emitted as explicit, ordered, human-executable steps rather than half-encoded
into a CSV. At minimum:

1. Conversion actions and goal configuration (created in the Google Ads UI, not Editor).
2. Conversion values, counting rules and attribution settings.
3. Shared negative-list creation and campaign association (Decision A4). Editor cannot
   reliably create a list and bind it to campaigns in one import, so every list in
   `negatives.shared_lists` is emitted as a named step with its member terms and its
   `applies_to` campaigns.
4. Call asset creation and phone-number verification, including any campaign or
   ad-group overrides resolved from `call_assets.overrides`.
5. Ad-schedule nuances that depend on account timezone.
6. Audience attachment, bid strategy portfolio membership, and any experiment settings.
7. Any field present in the workbook for which `editor_schema.yaml` has no mapping —
   these are enumerated by name, with their values, so nothing is lost.

`MANUAL_STEPS.md` is generated per run, is ordered, and every step is checkable. Point 7
is what stops this system from quietly pretending automation is magic.

### 11.5 Post-import human procedure

`MANUAL_STEPS.md` ends with the standing procedure:

```
1. Open Google Ads Editor, get latest changes for the account.
2. Account → Import → From file. Import each CSV in this order:
     campaigns → adgroups → keywords → negatives → ads_* → extensions
3. Review the proposed changes in the import preview. Do not post yet.
4. Run "Check changes". Resolve every error and warning it reports.
5. Post. Confirm every campaign shows status Paused.
6. Complete the manual steps listed above in the Google Ads UI.
7. QA against PRE_FLIGHT_REPORT.txt, then record sign-off in 01 ACTIONS.
8. Only then enable campaigns, in the UI, deliberately.
```

---

## 12. Pre-flight report

`PRE_FLIGHT_REPORT.txt` is plain text, ≤ 100 columns, readable in a terminal or pasted
into a chat. Structure:

```
APEX GOOGLE ADS OS — PRE-FLIGHT REPORT
Run:        20260818-114233-9f3ac1d2
Workbook:   input/workbook.xlsx  (sha256 9f3ac1d2…)
Rules:      config/rules.yaml    (sha256 4b8e01aa…)

RESULT: BUILD FAILED — 3 BLOCKERS, 5 WARNINGS

SUMMARY
  ✅ Monthly budget        ₹62,000
  ✅ Campaigns             5
  ✅ Ad groups             9
  ✅ Broad positives       0
  ✅ Negative collisions   0
  ⚠️  Legacy match types   2  (normalised to Phrase)
  ❌ Open RED blockers     3
  ❌ Landing pages         2 BLOCKER, 1 UNKNOWN

LANDING PAGES
  PASS      /google/neurologist-jaipur          200   1.23s
  BLOCKER   /google/knee-replacement-jaipur     404
  BLOCKER   /google/dialysis-jaipur             redirected to unrelated domain
  UNKNOWN   /google/apex-jaipur                 network validation could not complete

BLOCKERS
  [ACT-001] 01 ACTIONS r14 — RED action "Confirm Ortho landing page" still OPEN
            Fix: close or waive the item, with an owner, in 01 ACTIONS.
  [LP-003]  02 BUILD  r48 — /google/knee-replacement-jaipur returned 404
            Fix: correct the URL in 02 BUILD, or restore the page.
  ...

WARNINGS
  [KW-008]  03 KEYWORDS r91 — LEGACY_MATCH_TYPE_NORMALIZED: Modified Broad is
            discontinued. Converted to Phrase.
  ...

INFO
  ...

NO DEPLOYABLE FILES GENERATED
```

The `RESULT:` line is one of:

```
RESULT: BUILD READY — 0 BLOCKERS, 4 WARNINGS
RESULT: BUILD DRAFT — URL VALIDATION INCOMPLETE (3 UNKNOWN) — NOT DEPLOYABLE
RESULT: BUILD FAILED — 3 BLOCKERS, 5 WARNINGS
```

On `READY` the footer lists the generated files with row counts. On `DRAFT` the footer
names the quarantined directory and says why. The strings `BUILD READY`, `BUILD DRAFT`,
`BUILD FAILED`, `NOT DEPLOYABLE` and `NO DEPLOYABLE FILES GENERATED` are asserted by
tests — do not reword them.

---

## 13. Search-Term Watchdog

Weekly, post-launch. Input: a Google Ads search-terms export CSV plus the same workbook.
Output: analysis, suggested negatives, routing issues, and an actions report. It never
changes the account and never changes the workbook in place.

### 13.1 Cadence, ownership and ingest

**Decision A7 — the operating rhythm:**

```
MONDAY    Siddhant + Gaurav — efficiency review
          Qualified / Appointment / OPD; budget and bidding decisions if warranted

FRIDAY    Gaurav — Google Ads search-terms export, previous 7 days
          → save to input/search_terms/
          → run: apex watchdog
          → review routing / junk / concentration
          → approved changes go into 03 KEYWORDS and 01 ACTIONS
```

v1 is a **manually triggered** export. Google Ads API ingestion is a later phase and v1
MUST NOT block on it. Reliable software a human triggers on Friday beats an autonomous
process poking an API at 3 a.m. before anyone trusts either.

Ingest:

- `--search-terms` may name a file, or a directory (default `watchdog.input_dir`,
  `input/search_terms/`). Given a directory, the **most recently modified** CSV is used
  and its filename is echoed in the report — never picked silently.
- Column names vary by locale and report version, so resolution is **alias-driven** from
  `config/rules.yaml → watchdog.column_aliases`.
- Required columns: search term, campaign, ad group, matched keyword, match type,
  impressions, clicks, cost, conversions.
- Missing required column → BLOCKER, exit 2, no outputs. Same fail-closed discipline as
  the compiler.
- The export is checked against `watchdog.lookback_days` (7); a range that does not look
  like the previous 7 days produces a WARNING naming the actual range. Reviewing last
  month's data by accident is a quiet way to make a bad decision.
- Rows that fail to parse go to `parse_errors.csv` and are counted in the report. Never
  dropped silently.

### 13.2 Classification

Each search term is classified against the **existing Apex intent taxonomy** declared in
the workbook — brand terms, specialty themes, city/geo terms, intent modifiers
(`treatment`, `surgery`, `cost`, `doctor`, `near me`, `hospital`), and the negative
vocabulary. The classifier is rule-based and deterministic: normalised tokens matched
against taxonomy term lists, with a documented precedence order.

The classifier MUST NOT invent a classification. A term it cannot resolve is labelled
`CLASSIFIER_UNRESOLVED` and surfaced for human reading. An honest "I don't know" list is
more useful than a confident wrong bucket, and it is how the taxonomy gets improved.

### 13.3 Finding types — rank and surface, do not adjudicate

**Stage 1 has no thresholds.** Every cutoff in `watchdog.thresholds` is `null` on
purpose. We have no clean Apex data yet, and a number invented today would silently
become policy. The Watchdog's Stage-1 job is to **rank and surface**, not to declare
statistical verdicts it has not earned.

So it may say *"this query consumed 34% of last week's spend in Ortho | Knee"*. It may
not declare 30% morally unacceptable because a YAML file said so.

| Type | Meaning | Stage-1 behaviour |
| --- | --- | --- |
| `BRAND_LEAK` | A brand term served by a non-brand campaign, or a competitor-brand term served at all | Deterministic — taxonomy match plus campaign mismatch. Reported. |
| `SPECIALTY_LEAK` | Term belongs to specialty A, served by specialty B | Deterministic. Reported. |
| ~~`HELD_DEMAND`~~ | ~~A converting or high-intent term with no **approved** keyword covering it~~ | **REMOVED (eighth audit) — do not implement.** See the amendment below. |
| `JUNK` | Irrelevant or quality-weak traffic | Vocabulary matches reported outright; *statistical* junk is ranked by spend and impressions and marked `REVIEW`, never auto-declared. |
| `CONCENTRATION` | One term dominates spend or clicks | `concentration_mode: rank_and_review` — report the share, rank descending, decide nothing. |
| `CLASSIFIER_UNRESOLVED` | Could not be classified against the taxonomy | Surfaced for human reading. Never force-fitted. |
| `EXPLICIT_KEYWORD_GAP` | A covered, converting term with no keyword of its own | Ranked. An opportunity to bid and write for it deliberately — **not** held demand. |
| `UNAPPROVED_KEYWORD` | Served by a keyword the workbook does not contain, or by an approved keyword running in an ad group that does not own it | Reported. Adjudicating live-account state is §14's job. |

When a threshold is `null`, the corresponding finding is emitted in **rank-and-review**
form: sorted by money at stake, with the observed figure printed, and no automatic
verdict attached. When a threshold is later set to a real number — after
`learn_thresholds_after_days` (28) of clean data, by a human — the same finding gains a
verdict. The code path is identical; only the config changes.

A validator MUST NOT invent a default when a threshold is `null`. `null` means "we do not
know yet", and the honest implementation of "we do not know yet" is to show the evidence
and let a person decide.

#### `HELD_DEMAND` — removed (AMENDED, eighth audit)

`HELD_DEMAND` was specified as "demand the account is not capturing". A search-terms
export cannot support that finding, and the implementation proved it twice.

The export lists searches Google **did** serve. A search Google never served — the actual
held demand — leaves no row. So every `HELD_DEMAND` the code emitted was computed from
rows that were served, which means it was never measuring held demand at all; it was
measuring something else and wearing the name. The two honest questions that dataset *can*
answer already have their own types:

* `EXPLICIT_KEYWORD_GAP` — this term converted and the workbook has no keyword of its own
  for it. An opportunity to bid for it deliberately.
* `UNAPPROVED_KEYWORD` — this term was served by a keyword the workbook does not contain.
  That is account drift, not a coverage gap.

Genuinely unserved demand needs a different input — keyword-planner or impression-share
data — and Stage 1 does not have it. Inventing a proxy and keeping the original name is
how a dashboard ends up confidently reporting a quantity it cannot see.

Recorded because the name is more attractive than the evidence: anyone re-reading this
spec will want to re-add it. The dataset has not changed.

### 13.4 Routing analysis

For every term, compute the **expected owner** (campaign + ad group implied by its
classification) and compare with the **actual owner** (from the export). A mismatch is
leakage, reported with expected owner, actual owner, spend, clicks and conversions, so
the size of the problem is visible, not just its existence.

### 13.5 Negative policy — observation only (AMENDED, Stage 1)

> **This section was amended after Phase 6 was built. The original text is preserved
> below, because a spec that quietly changes is worse than one that argues with itself.**

**Stage-1 decision: the Watchdog does not author negative policy. It observes and
reports.** It proposes no new negative keyword, and it proposes no change to which
campaigns a shared list covers.

Both halves of that are deliberate:

* **No new negatives.** The narrowest defensible text for a novel exclusion is either a
  token nobody approved or the query itself — and the query is a patient's own words,
  which may not leave `search_term_analysis.csv`. A safe path exists (human review of
  candidate text before it is written anywhere) but it does not exist *yet*, and shipping
  the capability without it was how a proposal to negate the word `hospital` got as far as
  a paste-ready row.
* **No reach changes.** `ROUTE_COMPETITORS` is approved against four campaigns with Brand
  deliberately excluded. A shared negative list only affects the campaigns it is applied
  to, so extending it into Brand is a change to approved exclusion policy — a strategy
  decision, not an enforcement repair. It also could not survive the rest of this system:
  `NEG-008` requires `rules.yaml`, the `03 KEYWORDS` Scope cell and the `02 BUILD` routing
  column to agree, and a Watchdog writeback can only touch one of the three.

So the Watchdog emits two **observations**, both identified by query ID, neither
paste-ready:

| Observation | What it states | What it does not state |
| --- | --- | --- |
| `POLICY_SCOPE_REVIEW` | an approved negative's list does not apply where the term served | that it should |
| `OBSERVED_DESPITE_NEGATIVE` | an approved negative did not prevent this term | that the account is misconfigured |

The second wording is load-bearing. The Watchdog has no live account state and no change
history, so "the negative is not live" is stronger than its evidence: the term may have
served before the negative was added, the list may not be applied, or the workbook may
simply be ahead of the account. The observation names those checks and leaves the
live-account half to the Drift Checker (§14).

`--propose-writeback` therefore emits **no keyword block** — only `01_ACTIONS_append.csv`.
An action a person works is honest output; a paste-ready row the next compiler run rejects
is not.

**What this costs.** A genuinely new junk term — say `neurologist salary course`, which
nobody has put on a list — is ranked, classified and surfaced, and the Watchdog will not
propose the exclusion. A person writes it. That is the accepted trade for Stage 1, and it
is why this product is a **negative-policy watchdog** rather than a negative-discovery
engine. Reopening it is a deliberate Stage-2 decision, not a bug.

<details>
<summary>Original §13.5, superseded</summary>

For `JUNK`, `BRAND_LEAK` (competitor) and `SPECIALTY_LEAK` findings the Watchdog proposes
negatives: narrowest text, lowest sufficient level, `PHRASE` over `BROAD`, each run through
the §9.5 collision check, with a conflict emitted as `ROUTING_CONFLICT`. Suggestions are
never applied automatically.

Superseded because "narrowest text" has no safe source in Stage 1, and because the
collision check — which is real and still runs elsewhere — validates a negative's *effect*
without asking whether proposing it was the Watchdog's decision to make.

</details>

### 13.6 Outputs

Written to `output/watchdog/<run_id>/`:

| File | Contents |
| --- | --- |
| `search_term_analysis.csv` | Every term with classification, expected/actual owner, metrics, finding types. **The only artifact that contains raw search terms.** |
| `negative_observations.csv` | Approved negatives that did not prevent a term, with the list, its approved reach, and what to check. No proposals. |
| `routing_issues.csv` | Leakage: expected owner vs actual owner, with spend at stake |
| `actions_report.txt` | Human summary, ranked by money at stake |
| `parse_errors.csv` | Rows that could not be parsed (empty file if none) |
| `dashboard.html` | Optional, self-contained, no external assets |
| `manifest.json` | As §10.6 |

### 13.7 Write-back to the workbook

Optional and explicit: `apex watchdog --propose-writeback` emits
`output/watchdog/<run_id>/writeback/` containing **new** files — appendable blocks for
`06 NEGATIVE KEYWORDS` / `03 KEYWORDS` and rows for `01 ACTIONS` / `09 SEARCH TERM
MONITOR`. The source workbook is never modified in place. A human pastes what they
approve, and the next compiler run enforces it. That closes the loop through the
workbook, which is exactly where the audit trail should be.

---

## 14. Account Drift Checker

The third program, and over a year probably the most valuable one. The compiler makes us
good at building the account correctly once. The drift checker keeps us that way.

- **Desired state**: the workbook, parsed by the same ingest layer as the compiler.
- **Live state**: a Google Ads Editor export of the account (CSV export from Editor,
  placed in `input/live_export/`). No API.
- **Output**: `output/drift/<run_id>/drift_report.txt` + `drift.csv` + `manifest.json`.

### 14.1 What is compared

Entity-by-entity, keyed on names (campaign, ad group, keyword+match, negative+scope):

| Class | Examples | Default severity |
| --- | --- | --- |
| Budget | daily budget changed | CRITICAL |
| Match type | a keyword became `BROAD` | CRITICAL |
| Status | a campaign was enabled that the workbook has paused; something was removed | CRITICAL |
| Networks | Search Partners or Display expansion turned on | CRITICAL |
| Negatives | an approved negative is missing live; an unapproved negative was added | CRITICAL |
| Final URLs | landing page changed | CRITICAL |
| Keywords | a positive exists live that is not in the workbook, or vice versa | CRITICAL |
| Ad copy | headline/description text differs | WARNING |
| Bids | max CPC differs | WARNING |
| Extensions | present live but not approved | WARNING |

`drift.critical_fields` in config decides which classes are CRITICAL. Everything else is
WARNING. Exit code 4 when any CRITICAL drift is found, so a scheduled run can alert.

### 14.2 Report shape

```
APEX GOOGLE ADS OS — DRIFT REPORT
Run: 20260818-090000-9f3ac1d2      Live export: input/live_export/ (2026-08-18)

CRITICAL DRIFT (3)

MLN | Search | Ortho | Jaipur
  Budget
    Approved: ₹329/day
    Live:     ₹600/day

MLN | Search | Generic | Jaipur
  Keyword added (not in workbook):
    hospital in rajasthan
  Match type:
    BROAD

MLN | Search | Neuro | Jaipur
  Search Partners
    Approved: OFF
    Live:     ON

WARNINGS (7)
  ...
```

### 14.3 Resolution rule

Drift is not automatically "wrong in the account". It is a disagreement. Either the
account is wrong (revert it) or the workbook is stale (update and re-approve it).
The report says which entity and which field; a human decides which side moves. The tool
MUST NOT propose reverting the live account automatically, and MUST NOT edit the
workbook to match reality — that would launder unapproved changes into the source of
truth, which is the exact failure mode this program exists to prevent.

---

## 15. CLI contract

Entry point: `python src/cli.py <command>` and, once installed, the `apex` console
script. Both MUST work; the tasks file uses the module path so a fresh clone runs without
installation.

```
apex build     --workbook input/workbook.xlsx
               [--config config/rules.yaml] [--out output/build]
               [--no-network] [--verbose]
               # --no-network forces every URL to UNKNOWN → DRAFT build, exit 6

apex validate  --workbook input/workbook.xlsx [--config …] [--no-network]
               # validation only; never writes CSVs; same report

apex watchdog  --workbook input/workbook.xlsx
               [--search-terms input/search_terms/]     # file or directory
               [--config …] [--propose-writeback] [--dashboard]

apex drift     --workbook input/workbook.xlsx
               --live-export input/live_export [--config …]

apex version   # tool version, config hashes, git commit
```

### 15.1 Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success — `READY` build. Warnings may exist. |
| `2` | Validation BLOCKER. No deployable output. |
| `3` | Unexpected error. Traceback in `logs/<run_id>.log`. Partial output removed. |
| `4` | Drift check found CRITICAL drift. |
| `5` | Bad invocation: missing file, unreadable config, unknown argument. |
| `6` | `DRAFT` build — no BLOCKERs, but URL validation was incomplete. Not deployable. |

Exit codes are part of the contract — CI and any future scheduler depend on them.
In particular, `0` means "importable". Nothing else does.

---

## 16. Logging, privacy and security

1. **No PII anywhere a human or a machine will later read it.** Search queries can
   contain phone numbers, email addresses and patient-identifying text, and the Watchdog
   *persists reports*. "No PII in logs" is necessary and insufficient.

   Forbidden: logs, exception messages and tracebacks, console output, `dashboard.html`,
   `findings.json`, `actions_report.txt`, and any diagnostic preview of raw rows.

   Permitted: the raw search-term CSVs in `input/` and the analysis CSVs in `output/` —
   both git-ignored — because the operator needs the original query to review it.

   Required: `util/redact.py` masks obviously phone-number-shaped and email-shaped
   substrings in **every human-readable generated report**, not only in logs.

   The classifier may hold raw text in memory. There is no reason for a traceback to
   proudly print somebody's mobile number because Python met an unexpected comma.
2. **No credentials anywhere.** v1 has no API access, therefore no tokens. Never add a
   credential-shaped constant, never read one from the environment, never write one to a
   file. If a future phase needs OAuth it gets its own spec section and its own review.
3. **Inputs are git-ignored.** `input/` holds real client data. `.gitignore` excludes it
   and the tests never read from it — tests use `tests/fixtures/` only.
4. **Outputs are git-ignored.** Generated artifacts are reproducible from workbook +
   config + tool version, so they do not belong in version control.
5. **Logs**: JSON lines in `logs/<run_id>.log` (machine), concise human text on stderr.
   Every log line carries `run_id`. Log level defaults to INFO; `--verbose` gives DEBUG.
6. **Network egress** is limited to landing-page URL checks (`LP-003`), to hosts derived
   from workbook URLs, with timeout and bounded retries. Nothing else makes a request.
7. **No telemetry.** The tool phones nobody home.

---

## 17. Failure behaviour

| Situation | Behaviour |
| --- | --- |
| Workbook file missing / unreadable | Exit 5, one clear sentence. No traceback spew. |
| Sheet or required column missing | BLOCKER finding naming sheet + column, exit 2. |
| Cell fails type coercion | BLOCKER naming sheet, row, column and the offending value. |
| Any BLOCKER | Report written; no CSVs; exit 2. |
| Network unavailable during `LP-003` | Affected URLs are `UNKNOWN`. Outcome is `DRAFT`: CSVs quarantined in `<run_id>.DRAFT/`, exit 6. Never a `READY` build, never a false pass. |
| Unhandled exception | Log traceback, remove partial output dir, exit 3. |
| Output directory already exists | Impossible by construction (run_id includes a timestamp); if it happens, exit 3 rather than overwrite. |
| Config file invalid YAML or missing key | Exit 5 naming the file and the key. No defaults are silently invented. |

The through-line: **never produce a deployable artifact from a doubtful input, and never
report a check as passed when it did not run.**

---

## 18. Guardrails (safety first)

These are absolute. Each has a named test in §19. A PR that weakens one is rejected on
sight.

The system MUST NOT:

1. Upload anything directly to Google Ads. Deployment is via Editor, by a human.
2. Generate any campaign in a status other than `PAUSED`.
3. Auto-enable, un-pause, or schedule the enabling of any campaign or ad group.
4. Provide any flag, environment variable or config key that bypasses a BLOCKER.
5. Emit a Broad-match positive keyword — including by "normalising" one.
6. Auto-apply Watchdog negative suggestions.
7. **Author negative policy at all (Stage 1).** The Watchdog proposes no new negative
   keyword and no change to a shared list's reach; it observes and reports, and a person
   decides. Amended §13.5 records why, and what it costs.
7. Silently drop a workbook field that has no Editor mapping (§11.4 point 7).
8. Delete, disable or modify existing live campaigns.
9. Overwrite, rewrite or modify the source workbook.
10. Rewrite or extend the Apex taxonomy on its own.
11. Log patient-identifying data.
12. Invent a classification for an unresolved query.
13. Treat `UNKNOWN` as `PASS`, for landing pages or anything else — including reporting a
    passing `WB-001` as proof the export matches the Google Sheet (§4.4).
14. Produce a `READY` build when any landing-page check did not complete.
15. Flatten the negative hierarchy to campaign level, or ignore scope when checking
    collisions.
16. Continue past an unexpected exception and still write outputs.

The system MUST:

17. Always generate campaigns PAUSED, asserted twice (transform and writer).
18. Always write a timestamped, hash-stamped report for every run, whatever the outcome.
19. Always keep outputs by run_id — never overwrite a previous run.
20. Always quarantine a `DRAFT` build by directory name and mark it `DO_NOT_IMPORT`.
21. Always require human sign-off before launch, and say so in `MANUAL_STEPS.md`.
22. Always block the build on any critical error.

---

## 19. Testing strategy

### 19.1 Golden fixtures

`tests/fixtures/` contains small, hand-built workbooks — each is a scenario, not a copy
of production:

| Fixture | Purpose |
| --- | --- |
| `wb_clean.xlsx` | Fully valid: 2 campaigns, 3 ad groups, passes everything |
| `wb_broad_positive.xlsx` | One Broad positive keyword |
| `wb_negative_collision.xlsx` | One negative that blocks a bought keyword, per level |
| `wb_budget_mismatch.xlsx` | Campaign budgets do not sum to the monthly figure |
| `wb_missing_column.xlsx` | A required column removed |
| `wb_shifted_rows.xlsx` | `wb_clean` with 3 rows inserted above every section |
| `wb_bad_ad_copy.xlsx` | 31-char headline, 91-char description, duplicate headline |
| `wb_open_red_action.xlsx` | An open RED action item |
| `wb_no_call_number.xlsx` | Ad group with no call number in scope |
| `st_clean.csv`, `st_leakage.csv`, `st_junk.csv` | Search-term exports |
| `live_export_drift/` | Editor export with budget, match-type and network drift |

Expected outputs live beside them in `tests/golden/`. Golden files are regenerated only
by an explicit `pytest --update-golden` run, and the diff is reviewed by a human.

### 19.2 Acceptance tests

| # | Test | Expectation |
| --- | --- | --- |
| 1 | Clean workbook builds | Exit 0, all CSVs present, report says `BUILD READY` |
| 2 | Every emitted campaign row | Status column is `Paused`, in every fixture that builds |
| 3 | Broad positive present | Exit 2, `KW-001` BLOCKER, **zero CSVs written** |
| 4 | Negative collision (account level) | Exit 2, `NEG-001` naming both keyword and negative |
| 5 | Negative collision (campaign level, phrase) | Exit 2, `NEG-001` |
| 6 | Negative in a different campaign | No finding — scope matters |
| 7 | Budget mismatch | Exit 2, `BUD-001` with both figures in the message |
| 8 | Missing required column | Exit 2, message names sheet and column |
| 9 | Rows shifted by 3 | Identical findings to `wb_clean` — header-driven parsing proven |
| 10 | 31-char headline | Exit 2, `AD-002` citing the ad group and the headline |
| 11 | Open RED action | Exit 2, `ACT-001` |
| 12 | No call asset resolves for an ad group | Exit 2, `AD-006` |
| 13 | `--no-network` | Exit **6**, `BUILD DRAFT`, CSVs in `<run_id>.DRAFT/` with `DO_NOT_IMPORT.txt`, `latest` unchanged |
| 14 | Determinism | Two runs on one workbook produce byte-identical CSVs |
| 15 | Failed build leaves no artifacts | Output dir contains only the report; no `.partial` dir remains |
| 16 | Manifest completeness | Contains workbook hash, config hash, counts, per-file hashes, URL-check outcome |
| 17 | Unmapped field | Export raises `UnmappedFieldError`; nothing is silently dropped |
| 18 | Watchdog leakage | `st_leakage.csv` produces `SPECIALTY_LEAK` rows with expected vs actual owner |
| 19 | Watchdog junk → negatives | Suggestions produced, each with evidence |
| 20 | Watchdog suggestion collides | Emitted as `ROUTING_CONFLICT`, never as a suggestion |
| 21 | Watchdog unresolved term | Labelled `CLASSIFIER_UNRESOLVED`, not force-fitted |
| 22 | Watchdog never writes the workbook | Workbook SHA-256 identical before and after every command |
| 23 | Drift: budget + match + partners | Exit 4, all three CRITICAL, approved and live values both shown |
| 24 | No bypass flag exists | Grep the CLI surface: no `--force`, `--skip-validation`, `--ignore-blockers` |
| 25 | No API client imported | Grep `src/`: no `google.ads`, no OAuth, no upload path |
| 26 | `Modified Broad` input | Compiles to `Phrase`, `KW-008` WARNING with code `LEGACY_MATCH_TYPE_NORMALIZED`, exit 0 |
| 27 | `Broad` input | Exit 2 — normalisation never applies to `Broad` |
| 28 | Shared-list collision, list applied | Exit 2, `NEG-001` naming the list |
| 29 | Shared-list collision, list **not** applied to that campaign | No finding — list scope respected |
| 30 | Unapplied shared list declared | Exit 2, `NEG-006` |
| 31 | Landing page 404 (mocked) | Exit 2, `LP-003` reporting status 404 |
| 32 | Landing page redirects off-domain (mocked) | Exit 2, `LP-004` naming the final URL |
| 33 | Landing page times out (mocked) | State `UNKNOWN`, `BUILD DRAFT`, exit 6 — never `PASS` |
| 34 | Redirect loop (mocked) | Exit 2, `LP-003` naming the loop, depth cap respected |
| 35 | Call asset override | Campaign-level override wins over default; ad-group override wins over campaign |
| 36 | Watchdog directory input | Newest CSV in `input/search_terms/` chosen, filename echoed in the report |
| 37 | Call-number placeholder, fixture build | Parses and validates fine; `apex validate` exits 0 with a WARNING, not a parse error |
| 38 | Call-number placeholder, READY build | `AD-012` BLOCKER — a deployable build is impossible until a real number is supplied |
| 39 | Shared-list scope disagreement | Workbook `Scope` and `rules.yaml applies_to` differ → `NEG-008` BLOCKER naming both |
| 40 | Export never flattens negatives | Four negative files emitted; no shared-list term duplicated into campaign negatives |
| 41 | Null watchdog threshold | Finding emitted in rank-and-review form with the observed figure and no verdict |
| 42 | Tracking template absent | No finding — `TRK-006` is conditional |
| 43 | Budget sums to ₹61,900 | `BUD-001` BLOCKER — zero tolerance, no ±2% |
| 44 | PII in a search term | Masked in `actions_report.txt`, `findings.json` and `dashboard.html`; present in the analysis CSV |

Tests 24 and 25 enforce §18 and matter as much as the functional ones. Tests 13, 33 and
27 exist because those three are exactly where a future contributor will be tempted to be
"pragmatic".

### 19.3 Coverage expectations

`validate/` and `compile_/` at ≥ 90% line coverage. `models/` fully typed under `mypy
--strict`. `ruff check` clean. Integration tests run the CLI as a subprocess so exit
codes are tested for real, not mocked.

---

## 20. Delivery phases

Full task breakdown in [`CODEX_TASKS.md`](../CODEX_TASKS.md). Summary:

| Phase | Deliverable | Done when |
| --- | --- | --- |
| 0 | Repo skeleton, config, CI, `apex version` | `pytest` runs green on an empty suite; lint clean |
| PRE | Workbook Schema Reconnaissance — inspect the real workbook, freeze `workbook_schema.yaml`, present the diff | ✅ Complete. Schema approved. No parser code written. |
| 1B | Ingest + models | `wb_clean.xlsx` parses into a `WorkbookBundle`; test 9 passes |
| 2 | Validator framework + budget/structure rules | Tests 7, 8, 9, 11 pass |
| 3 | Keyword + negative rules incl. scope-aware collisions | Tests 3–6, 26–30 pass |
| 4 | Ads, call assets, landing pages, tracking, settings | Tests 10, 12, 13, 31–35 pass |
| 5 | Transform + Editor export + report + manifest | Tests 1, 2, 14, 15, 16, 17 pass |
| 6 | Search-Term Watchdog | Tests 18–22, 36 pass |
| 7 | Drift checker | Test 23 passes |

Each phase is one PR. A phase is not done until its tests are in the same PR and green.

---

## 21. Decisions taken, and what is still open

Seven decisions were locked by the account owner before implementation began. They are
recorded in [`DECISIONS.md`](../DECISIONS.md) with rationale and sources, and encoded in
`config/`. Summary:

| ID | Decision |
| --- | --- |
| A1 | The four-sheet workbook is the only workbook. The eleven "sections" are software capabilities, not tabs. |
| A2 | ₹62,000 / 5 campaigns / 9 ad groups / `apexhospitals.com` are Stage-1 invariants, not waivable. |
| A3 | `Modified Broad` → `Phrase` + `LEGACY_MATCH_TYPE_NORMALIZED` warning. `Broad` blocks the build. |
| A4 | Hybrid negative hierarchy: account / shared list / campaign / ad group. Scope-aware collisions. |
| A5 | One default call asset, most-specific-wins overrides. Not nine numbers. |
| A6 | Landing-page reachability is a blocking pre-flight check. `UNKNOWN` ≠ `PASS`. |
| A7 | Gaurav exports search terms every Friday to `input/search_terms/`. Manual in v1. |

### Still open — these need a human before the phase that depends on them

1. **Real column names.** `config/workbook_schema.yaml` names the four correct sheets,
   but the column names inside each section are inferred. Phase 1 MUST reconcile them
   against `input/workbook.xlsx` and correct the file.
2. **Editor column headers.** `config/editor_schema.yaml` is UNVERIFIED. Phase 5 MUST
   regenerate it from a real Google Ads Editor export. A wrong header is a failed import.
3. **Shared-list membership.** The list *names* are decided (§9.5); which campaigns each
   list applies to must be declared in the workbook or in `rules.yaml` before Phase 3.
4. **The call number itself.** `call_assets.default.number` and `.schedule` are the
   placeholder `REQUIRED` and fail `AD-012` until filled.
5. **Taxonomy source.** The Watchdog classifier reads the Apex intent taxonomy from the
   workbook. If it lives elsewhere, Phase 6 needs its location before it starts.
6. **Live export cadence** for drift checks — who produces the Editor export, and when.
   A7 covers search terms; it does not cover the drift export.

---

## 22. What "done" looks like

A marketing operator edits the workbook, runs one command, and gets either a list of
exactly what is wrong with their strategy — in workbook coordinates they can act on — or
a set of files that import cleanly into Google Ads Editor and create a paused, correct,
fully-tracked account structure that a human then reviews and enables.

After launch, two more commands tell them whether Google behaved and whether people did.

Boring, repeatable, and very hard to get wrong. That is the whole point.
