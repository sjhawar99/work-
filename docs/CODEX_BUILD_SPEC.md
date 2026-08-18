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
| **Search-Term Watchdog** | Weekly, post-launch | Search-terms export `.csv` + workbook | Analysis, negative suggestions, routing issues, actions report |
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

### 4.2 Reference structure mapping

The workbook has also been documented in an expanded, section-per-topic form. The
compiler MUST support both shapes, because the same logical sections appear in both —
either as separate sheets or as titled blocks inside `02 BUILD` / `03 KEYWORDS`:

| Section | Contents |
| --- | --- |
| `00 SETUP` | Account-level settings, brand, targets, defaults |
| `01 CAMPAIGN BLUEPRINT` | Campaign structure, budget split, net daily budget |
| `02 KEYWORD MAP` | Keywords mapped to campaigns, ad groups, match types |
| `03 ADS` | RSA assets, headlines, descriptions, callouts |
| `04 LANDING PAGES` | Landing-page URLs mapped to campaigns / ad groups |
| `05 EXTENSIONS` | Sitelinks, callouts, structured snippets |
| `06 NEGATIVE KEYWORDS` | Account-, campaign- and ad-group-level negatives |
| `07 TRACKING & CONVERSIONS` | Conversion goals, values, tracking links, UTM structure |
| `08 BUDGET GUIDE` | Budget rules, guidelines, checks |
| `09 SEARCH TERM MONITOR` | Weekly search-term analysis template |
| `10 REVIEW & SIGN OFF` | Checklist, sign-off, final approval |

**Implementation consequence:** the parser is driven by a *section registry* in
`config/workbook_schema.yaml` that maps a logical section (e.g. `campaigns`,
`keywords`, `negatives`) to (sheet name pattern, section header text, required columns).
Adding a sheet, renaming a sheet, or moving a section between sheets MUST be a config
change, not a code change.

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
│   ├── search_terms_weekly.csv
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
    level: Literal["ACCOUNT", "CAMPAIGN", "AD_GROUP"]
    campaign: str | None
    ad_group: str | None
    text: str
    match_type: Literal["EXACT", "PHRASE", "BROAD"]
    list_name: str | None          # shared negative list, if any

class ResponsiveSearchAd(Provenance):
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

Every business threshold lives here. The file shipped in this repo carries the current
Apex defaults; see the file itself for the authoritative values. Structure:

```yaml
account:
  currency: INR
  monthly_budget: 62000
  budget_tolerance_pct: 2          # net daily × days must land within ±2%
  expected_campaign_count: 5
  expected_ad_group_count: 9

naming:
  campaign_pattern: "^[A-Z]{2,4} \\| (Search) \\| [A-Za-z0-9 &+-]+ \\| [A-Za-z ]+$"

keywords:
  allowed_match_types: [EXACT, PHRASE]     # BROAD positives are forbidden
  max_ad_groups_per_keyword: 1
  min_keywords_per_ad_group: 1

negatives:
  collision_check: true
  allowed_levels: [ACCOUNT, CAMPAIGN, AD_GROUP]

ads:
  headlines: {min: 3, max: 15, max_chars: 30}
  descriptions: {min: 2, max: 4, max_chars: 90}
  paths: {max_chars: 15}
  require_call_number_in_ad: true
  require_business_hours: true

landing_pages:
  max_url_chars: 200
  check_http: true
  allowed_status: [200]
  follow_redirects: false
  timeout_seconds: 10
  retries: 2

tracking:
  require_conversion_goal: true
  require_conversion_value: true
  require_utm_params: [utm_source, utm_medium, utm_campaign]

watchdog:
  junk_min_impressions: 20
  junk_max_ctr: 0.005
  concentration_spend_share: 0.30
  held_demand_min_conversions: 1
  leak_report_threshold: 1

drift:
  critical_fields: [budget, match_type, search_partners, status, final_url, negatives]
```

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

| ID | Severity | Rule |
| --- | --- | --- |
| `BUD-001` | BLOCKER | Sum of campaign monthly budgets equals `account.monthly_budget` within `budget_tolerance_pct`. |
| `BUD-002` | BLOCKER | Every campaign has a positive daily budget; no zero, no blank, no negative. |
| `BUD-003` | BLOCKER | Declared budget split percentages sum to 100% (±0.5pp) and match the derived daily budgets. |
| `BUD-004` | WARNING | Daily budget × 30.4 deviates from the campaign's declared monthly share by more than tolerance. |
| `STR-001` | BLOCKER | Campaign count equals `expected_campaign_count`, or the difference is waived in `01 ACTIONS`. |
| `STR-002` | BLOCKER | Ad-group count equals `expected_ad_group_count`, or waived. |
| `STR-003` | BLOCKER | Every ad group references an existing campaign; every keyword and ad references an existing ad group. No orphans. |
| `STR-004` | BLOCKER | Campaign names match `naming.campaign_pattern`. |
| `STR-005` | BLOCKER | No duplicate campaign names; no duplicate ad-group names within a campaign. |
| `STR-006` | BLOCKER | Every campaign's status compiles to `PAUSED`. |
| `STR-007` | WARNING | Every ad group contains at least `min_keywords_per_ad_group` keywords. |

### 9.4 Keyword rules

| ID | Severity | Rule |
| --- | --- | --- |
| `KW-001` | BLOCKER | No positive keyword uses Broad match. Allowed match types come from `keywords.allowed_match_types`. |
| `KW-002` | BLOCKER | No keyword text appears in more than one ad group (`max_ad_groups_per_keyword`). Cross-ad-group duplication is self-competition. |
| `KW-003` | BLOCKER | No exact duplicate (text, match type) pair within an ad group. |
| `KW-004` | BLOCKER | Keyword text contains no invalid characters and is within Google's length limit (80 chars). |
| `KW-005` | WARNING | Near-duplicate keywords across ad groups (normalised: lowercase, punctuation stripped, word-order-insensitive). |
| `KW-006` | BLOCKER | Every keyword belongs to an ad group whose theme is declared in `02 BUILD`. |
| `KW-007` | WARNING | Keyword-level final URL, where present, resolves to the same domain as the ad-group final URL. |

### 9.5 Negative-keyword rules and collision semantics

| ID | Severity | Rule |
| --- | --- | --- |
| `NEG-001` | BLOCKER | No negative keyword blocks a positive keyword in scope. See collision semantics below. |
| `NEG-002` | BLOCKER | Every negative declares a valid level and, for `CAMPAIGN`/`AD_GROUP`, an existing target. |
| `NEG-003` | BLOCKER | No exact duplicate negative at the same level and scope. |
| `NEG-004` | WARNING | A campaign-level negative is redundant because an identical account-level negative exists. |
| `NEG-005` | INFO | Negative appears in a shared list that is not applied to any campaign. |

**Collision semantics (`NEG-001`) — implement exactly this:**

A negative `N` collides with a positive keyword `K` when both of the following hold:

1. **Scope overlap.** `N.level == ACCOUNT`; or `N.level == CAMPAIGN` and
   `N.campaign == K.campaign`; or `N.level == AD_GROUP` and `N.campaign == K.campaign`
   and `N.ad_group == K.ad_group`.
2. **Match semantics.** Using Google's negative-match rules, with all comparison done on
   normalised tokens (lowercase, trim, collapse whitespace, strip punctuation; **no
   close-variant or plural expansion** — negatives do not match close variants):
   - `N` is **negative broad**: every token of `N` appears in `K`'s tokens (order-independent).
   - `N` is **negative phrase**: `N`'s token sequence appears as a contiguous subsequence of `K`'s tokens.
   - `N` is **negative exact**: `N`'s token sequence equals `K`'s token sequence.

Each collision is one BLOCKER finding naming: the negative (text, match, level, scope,
sheet/row), the blocked keyword (text, match, campaign, ad group, sheet/row), and the
remedy (narrow the negative, move it down a level, or drop the positive).

This rule is the single highest-value check in the system. It is the defect class that
is invisible in the UI and expensive in the account. It gets its own test file
(`tests/unit/test_negative_collisions.py`) with, at minimum, a case per match type per
level.

### 9.6 Ads, assets and landing pages

| ID | Severity | Rule |
| --- | --- | --- |
| `AD-001` | BLOCKER | Headline count within `ads.headlines.min..max`. |
| `AD-002` | BLOCKER | Every headline ≤ `ads.headlines.max_chars`, measured in characters after trimming. |
| `AD-003` | BLOCKER | Description count within `ads.descriptions.min..max`. |
| `AD-004` | BLOCKER | Every description ≤ `ads.descriptions.max_chars`. |
| `AD-005` | BLOCKER | Every ad group has at least one RSA with a final URL. |
| `AD-006` | BLOCKER | A call/phone number is present per `ads.require_call_number_in_ad` (in ad copy or a call extension in scope). |
| `AD-007` | BLOCKER | No duplicate headline or description text within one RSA. |
| `AD-008` | WARNING | Business hours are declared where `ads.require_business_hours` is set. |
| `AD-009` | BLOCKER | No special/unsupported characters; no emoji; no double spaces; no ALL-CAPS words beyond permitted abbreviations. |
| `AD-010` | BLOCKER | Path fields ≤ `ads.paths.max_chars`. |
| `AD-011` | BLOCKER | No duplicate asset names across extensions. |
| `LP-001` | BLOCKER | Every final URL is a syntactically valid absolute `https://` URL ≤ `landing_pages.max_url_chars`. |
| `LP-002` | BLOCKER | Every ad group maps to exactly one landing page as declared in `04 LANDING PAGES`. |
| `LP-003` | BLOCKER (network) | Every distinct final URL returns an allowed status; redirect chains and loops are failures when `follow_redirects: false`. |
| `LP-004` | WARNING | Landing page domain differs from the account's declared primary domain. |

`LP-003` requires network access. It runs when enabled in config and not disabled by
`--no-network`. When it cannot run (flag set, or the host is unreachable), it emits one
`INFO` finding stating clearly that URL checks were skipped, and the pre-flight report
header says `URL CHECKS: SKIPPED`. Skipped checks are never silently reported as passed.
Requests are deduplicated per distinct URL, use `landing_pages.retries` with exponential
backoff, and honour `timeout_seconds`.

### 9.7 Tracking and conversions

| ID | Severity | Rule |
| --- | --- | --- |
| `TRK-001` | BLOCKER | At least one primary conversion goal is defined. |
| `TRK-002` | BLOCKER | Every conversion goal used by a campaign exists in `07 TRACKING & CONVERSIONS`. |
| `TRK-003` | WARNING | Conversion value is defined where `tracking.require_conversion_value` is set. |
| `TRK-004` | BLOCKER | Tracking template / final URL suffix contains every parameter in `tracking.require_utm_params`. |
| `TRK-005` | BLOCKER | Tracking template is syntactically valid: balanced `{}`, `{lpurl}` present, no spaces. |

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

A waiver suppresses a *specific* structural expectation (`STR-001`, `STR-002`) only. It
can never suppress `KW-001`, `NEG-001`, `AD-00x`, `LP-001`, `SET-001` or `STR-006`. The
list of waivable rule IDs is a constant in code, not config, so nobody can widen it by
editing a YAML file.

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
| `negatives.csv` | Negatives with level and scope |
| `ads_headlines.csv` | RSA headlines, one row per ad with numbered headline columns |
| `ads_descriptions.csv` | RSA descriptions, likewise |
| `extensions.csv` | Sitelinks, callouts, structured snippets, call extension |
| `PRE_FLIGHT_REPORT.txt` | Human-readable validation summary (§12) |
| `MANUAL_STEPS.md` | Everything Editor cannot encode (§11.4) |
| `manifest.json` | Run metadata and hashes (§10.6) |
| `findings.json` | Machine-readable findings, for CI and the dashboard |

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

### 10.5 Fail-closed behaviour

- Any BLOCKER → no CSVs. The report is still written, to `output/build/<run_id>/`.
- Any unhandled exception → catch at the CLI boundary, log the traceback to
  `logs/<run_id>.log`, print a short human message, exit 3, and **delete any partially
  written output directory**. A half-written export is worse than no export.
- Writing is staged: files are written to `output/build/<run_id>.partial/` and the
  directory is renamed on success. Readers never see a partial run.

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
3. Account-level shared negative-list creation and association, where the workbook
   declares a list that does not yet exist.
4. Call extension verification / phone-number verification.
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
7. QA against PRE_FLIGHT_REPORT.txt, then obtain sign-off in 10 REVIEW & SIGN OFF.
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
URL checks: RUN (37 URLs, 37 OK)

RESULT: BUILD FAILED — 3 BLOCKERS, 5 WARNINGS

SUMMARY
  ✅ Monthly budget        ₹62,000
  ✅ Campaigns             5
  ✅ Ad groups             9
  ✅ Broad positives       0
  ✅ Negative collisions   0
  ❌ Open RED blockers     3
  ❌ Missing call numbers  5

BLOCKERS
  [ACT-001] 01 ACTIONS r14 — RED action "Confirm Ortho landing page" still OPEN
            Fix: close or waive the item, with an owner, in 01 ACTIONS.
  [AD-006]  02 BUILD  r61 — MLN | Search | Ortho | Jaipur / Ortho — Knee has no call number
            Fix: add the call number to the RSA or attach a call extension.
  ...

WARNINGS
  [KW-005]  03 KEYWORDS r122 — near-duplicate of "knee replacement jaipur" in Ortho — Knee
  ...

INFO
  ...

NO DEPLOYABLE FILES GENERATED
```

On success the header reads `RESULT: BUILD PASSED` and the footer lists the generated
files with row counts. The exact strings `BUILD FAILED`, `BUILD PASSED` and
`NO DEPLOYABLE FILES GENERATED` are asserted by tests — do not reword them.

---

## 13. Search-Term Watchdog

Weekly, post-launch. Input: a Google Ads search-terms export CSV plus the same workbook.
Output: analysis, suggested negatives, routing issues, and an actions report. It never
changes the account and never changes the workbook in place.

### 13.1 Ingest

- Accept the standard Google Ads search-terms report export. Column names vary by
  locale and by report version, so column resolution is **alias-driven** from
  `config/rules.yaml → watchdog.column_aliases` (e.g. `search term` ← `Search term`,
  `Search keyword`, `Query`).
- Required columns: search term, campaign, ad group, matched keyword, match type,
  impressions, clicks, cost, conversions.
- Missing required column → BLOCKER, exit 2, no outputs. Same fail-closed discipline as
  the compiler.
- Currency and percentage parsing reuses `util/currency.py`. Rows that fail to parse are
  collected into `parse_errors.csv` and counted in the report; they are never dropped
  silently.

### 13.2 Classification

Each search term is classified against the **existing Apex intent taxonomy** declared in
the workbook — brand terms, specialty themes, city/geo terms, intent modifiers
(`treatment`, `surgery`, `cost`, `doctor`, `near me`, `hospital`), and the negative
vocabulary. The classifier is rule-based and deterministic: normalised tokens matched
against taxonomy term lists, with a documented precedence order.

The classifier MUST NOT invent a classification. A term it cannot resolve is labelled
`CLASSIFIER_UNRESOLVED` and surfaced for human reading. An honest "I don't know" list is
more useful than a confident wrong bucket, and it is how the taxonomy gets improved.

### 13.3 Finding types

| Type | Meaning | Trigger (config-driven) |
| --- | --- | --- |
| `BRAND_LEAK` | A brand term served by a non-brand campaign, or a competitor-brand term served at all | taxonomy match + campaign mismatch |
| `SPECIALTY_LEAK` | Term belongs to specialty A but was served by specialty B's ad group | classified theme ≠ serving ad-group theme |
| `JUNK` | Irrelevant or quality-weak traffic | ≥ `junk_min_impressions` and CTR ≤ `junk_max_ctr`, or matches junk vocabulary |
| `HELD_DEMAND` | A converting or high-intent term with no matching positive keyword | ≥ `held_demand_min_conversions` and no exact/phrase positive covers it |
| `CONCENTRATION` | One term dominates spend or clicks in its ad group | spend share ≥ `concentration_spend_share` |
| `CLASSIFIER_UNRESOLVED` | Could not be classified against the taxonomy | no taxonomy match |

### 13.4 Routing analysis

For every term, compute the **expected owner** (campaign + ad group implied by its
classification) and compare with the **actual owner** (from the export). A mismatch is
leakage, reported with expected owner, actual owner, spend, clicks and conversions, so
the size of the problem is visible, not just its existence.

### 13.5 Negative suggestions

For `JUNK`, `BRAND_LEAK` (competitor) and `SPECIALTY_LEAK` findings the Watchdog proposes
negatives:

1. Choose the narrowest text that removes the problem — prefer the offending token or
   phrase over the full query.
2. Choose the lowest sufficient level: ad group before campaign before account.
3. Prefer `PHRASE` over `BROAD` for multi-token negatives; use `EXACT` when the whole
   query is the problem.
4. **Run the §9.5 collision check against every current positive keyword.** A suggestion
   that would block a positive we buy is not emitted as a suggestion — it is emitted as a
   `ROUTING_CONFLICT` row explaining the tension, for a human to resolve.
5. Every suggestion carries evidence: the terms it would have blocked last period, their
   impressions, clicks, cost and conversions.

Suggestions are **never applied automatically.** They are candidates.

### 13.6 Outputs

Written to `output/watchdog/<run_id>/`:

| File | Contents |
| --- | --- |
| `search_term_analysis.csv` | Every term with classification, expected/actual owner, metrics, finding types |
| `negatives_suggestions.csv` | Candidate negatives with level, scope, match type, evidence, collision status |
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
script. Both MUST work; the tasks file uses the module path so a fresh clone runs
without installation.

```
apex build     --workbook input/workbook.xlsx
               [--config config/rules.yaml] [--out output/build]
               [--no-network] [--verbose]

apex validate  --workbook input/workbook.xlsx [--config …] [--no-network]
               # validation only; never writes CSVs; same report

apex watchdog  --workbook input/workbook.xlsx
               --search-terms input/search_terms_weekly.csv
               [--config …] [--propose-writeback] [--dashboard]

apex drift     --workbook input/workbook.xlsx
               --live-export input/live_export [--config …]

apex version   # tool version, config hashes, git commit
```

### 15.1 Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success. Warnings may exist. |
| `2` | Validation BLOCKER (build/validate/watchdog input invalid). No deployable output. |
| `3` | Unexpected error. Traceback in `logs/<run_id>.log`. Partial output removed. |
| `4` | Drift check found CRITICAL drift. |
| `5` | Bad invocation: missing file, unreadable config, unknown argument. |

Exit codes are part of the contract — CI and any future scheduler depend on them.

---

## 16. Logging, privacy and security

1. **No PII in logs, reports or outputs.** Search-term exports can contain
   patient-identifying queries (names, phone numbers, conditions tied to an individual).
   Before any term is written to a log, the logger applies `util/redact.py`:
   phone-number-shaped and email-shaped substrings are masked. Search terms themselves
   appear in the analysis CSVs (they must, to be useful) but never in verbose logs.
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
| Network unavailable during `LP-003` | INFO finding, `URL CHECKS: SKIPPED` in the header, build continues. Never a false pass. |
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
5. Emit a Broad-match positive keyword.
6. Auto-apply Watchdog negative suggestions.
7. Silently drop a workbook field that has no Editor mapping (§11.4 point 7).
8. Delete, disable or modify existing live campaigns.
9. Overwrite, rewrite or modify the source workbook.
10. Rewrite or extend the Apex taxonomy on its own.
11. Log patient-identifying data.
12. Invent a classification for an unresolved query.
13. Report a skipped check as a passed check.
14. Continue past an unexpected exception and still write outputs.

The system MUST:

15. Always generate campaigns PAUSED, asserted twice (transform and writer).
16. Always write a timestamped, hash-stamped report for every run, pass or fail.
17. Always keep backups of outputs by run_id — never overwrite a previous run.
18. Always require human sign-off before launch, and say so in `MANUAL_STEPS.md`.
19. Block the build on any critical error.

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
| 1 | Clean workbook builds | Exit 0, all CSVs present, report says `BUILD PASSED` |
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
| 12 | Missing call number | Exit 2, `AD-006` |
| 13 | `--no-network` | Exit 0, report header says `URL CHECKS: SKIPPED`, no INFO claims pass |
| 14 | Determinism | Two runs on one workbook produce byte-identical CSVs |
| 15 | Failed build leaves no artifacts | Output dir contains only the report; no `.partial` dir remains |
| 16 | Manifest completeness | Contains workbook hash, config hash, counts, per-file hashes |
| 17 | Unmapped field | Export raises `UnmappedFieldError`; nothing is silently dropped |
| 18 | Watchdog leakage | `st_leakage.csv` produces `SPECIALTY_LEAK` rows with expected vs actual owner |
| 19 | Watchdog junk → negatives | Suggestions produced, each with evidence |
| 20 | Watchdog suggestion collides | Emitted as `ROUTING_CONFLICT`, never as a suggestion |
| 21 | Watchdog unresolved term | Labelled `CLASSIFIER_UNRESOLVED`, not force-fitted |
| 22 | Watchdog never writes the workbook | Workbook SHA-256 identical before and after every command |
| 23 | Drift: budget + match + partners | Exit 4, all three CRITICAL, approved and live values both shown |
| 24 | No bypass flag exists | Grep the CLI surface: no `--force`, `--skip-validation`, `--ignore-blockers` |
| 25 | No API client imported | Grep `src/`: no `google.ads`, no OAuth, no upload path |

Tests 24 and 25 are enforcement tests against the guardrails in §18 and are as important
as the functional ones.

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
| 1 | Ingest + models | `wb_clean.xlsx` parses into a `WorkbookBundle`; test 9 passes |
| 2 | Validator framework + budget/structure rules | Tests 7, 8, 9, 11 pass |
| 3 | Keyword + negative rules incl. collisions | Tests 3, 4, 5, 6 pass |
| 4 | Ads, landing pages, tracking, settings rules | Tests 10, 12, 13 pass |
| 5 | Transform + Editor export + report + manifest | Tests 1, 2, 14, 15, 16, 17 pass |
| 6 | Search-Term Watchdog | Tests 18–22 pass |
| 7 | Drift checker | Test 23 passes |

Each phase is one PR. A phase is not done until its tests are in the same PR and green.

---

## 21. Assumptions and open questions

Recorded honestly rather than guessed at silently. Each needs a human answer before the
phase that depends on it.

1. **Workbook shape.** The spec supports both the four-sheet operating layout (§4.1) and
   the eleven-section reference layout (§4.2) via `config/workbook_schema.yaml`. The
   section registry shipped in this repo is a *starting point* and MUST be reconciled
   against the real workbook in Phase 1, with the real file placed at `input/workbook.xlsx`.
2. **Numeric defaults.** ₹62,000 monthly, 5 campaigns, 9 ad groups, ₹329/day examples are
   taken from the current plan and are config values, not truths. Confirm before Phase 2.
3. **Modified Broad.** The workbook's match-type guidance mentions Exact / Phrase /
   Modified Broad. Modified Broad no longer exists as a Google match type. The spec
   therefore allows `EXACT` and `PHRASE` positives only, and Phase 3 MUST confirm that
   any workbook row saying "Modified Broad" is treated as `PHRASE` (with an INFO finding)
   rather than as Broad.
4. **Shared negative lists.** Whether Apex uses shared lists or per-campaign negatives
   changes the export shape (§10.2 rule 5). Confirm before Phase 5.
5. **Editor column names** must be verified against the installed Editor version by
   exporting a sample and reading its headers; `config/editor_schema.yaml` is filled from
   that export, not from memory.
6. **Taxonomy source.** The Watchdog classifier reads the taxonomy from the workbook. If
   the taxonomy lives elsewhere, Phase 6 needs its location before it starts.
7. **Live export cadence** for drift checks — weekly is assumed; confirm who produces the
   export and where it lands.

---

## 22. What "done" looks like

A marketing operator edits the workbook, runs one command, and gets either a list of
exactly what is wrong with their strategy — in workbook coordinates they can act on — or
a set of files that import cleanly into Google Ads Editor and create a paused, correct,
fully-tracked account structure that a human then reviews and enables.

After launch, two more commands tell them whether Google behaved and whether people did.

Boring, repeatable, and very hard to get wrong. That is the whole point.
