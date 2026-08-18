# DECISIONS.md

Locked implementation decisions. Each was ambiguous in the specification and has now been
resolved by the account owner. Codex MUST NOT re-infer any of these.

Encoded in `config/rules.yaml`, `config/workbook_schema.yaml` and the sections of
`docs/CODEX_BUILD_SPEC.md` referenced below.

| ID | Decision | Spec | Config |
| --- | --- | --- | --- |
| A1 | The four-sheet workbook is the only workbook | §4.1–4.2 | `workbook_schema.yaml` |
| A2 | ₹62,000 / 5 campaigns / 9 ad groups / `apexhospitals.com` are Stage-1 invariants | §9.3 | `rules.yaml → account` |
| A3 | `Modified Broad` → `Phrase` + warning; `Broad` blocks the build | §9.4 | hard-coded (§8.4) |
| A4 | Hybrid negative hierarchy, scope-aware collisions | §9.5 | `rules.yaml → negatives` |
| A5 | One default call asset, most-specific-wins overrides | §9.6 | `rules.yaml → call_assets` |
| A6 | Landing-page reachability is a blocking check; `UNKNOWN` ≠ `PASS` | §9.6, §10.5 | `rules.yaml → landing_pages` |
| A7 | Weekly manual search-terms export, Fridays | §13.1 | `rules.yaml → watchdog` |

---

## A1 — There is one workbook, and it has four sheets

```
APEX_Google_Ads_Operating_System_v1.1.xlsx
  01 ACTIONS
  02 BUILD
  03 KEYWORDS
  04 DAILY
```

The eleven-area structure — Setup, Campaign Blueprint, Keyword Map, Ads, Landing Pages,
Extensions, Negative Keywords, Tracking, Budget, Search-Term Monitor, Review/Sign-off —
is the **software's conceptual architecture**. It tells the implementation what
capabilities to build. It does not say "look for eleven Excel tabs", and doing so would
mean debugging a workbook that has never existed.

Each capability lives inside one of the four real sheets; the mapping is in spec §4.2 and
`config/workbook_schema.yaml`.

## A2 — Stage-1 invariants

| Setting | Value |
| --- | --- |
| Monthly budget | ₹62,000 exactly |
| Campaigns | 5 |
| Ad groups | 9 |
| Domain | `apexhospitals.com` / `www.apexhospitals.com` |

The compiler fails if any of the first three does not match. Landing pages must resolve
under the allowed domains unless explicitly whitelisted in
`landing_pages.extra_allowed_domains`.

These are not waivable. **This overrides the earlier draft**, where an action-item row
could waive the campaign and ad-group counts. The waivable-rule list is now empty
(spec §9.9): changing an invariant is a reviewed change to `config/rules.yaml`, not a row
somebody adds to a spreadsheet on a deadline.

## A3 — Legacy match types

```
IF match_type == "Modified Broad":
    normalized_match_type = "Phrase"
    warn("LEGACY_MATCH_TYPE_NORMALIZED",
         "Modified Broad is discontinued. Converted to Phrase.")

IF match_type == "Broad":
    BLOCK BUILD
```

Broad Match Modifier was retired by Google: legacy BMM keywords behave as Phrase, and new
BMM keywords cannot be created. Normalising is therefore correct. An actual Broad positive
is a different thing and still violates Stage-1 rules.

Keeping the two paths separate means legacy nomenclature in the workbook does not break
the compiler, while a real Broad keyword cannot ride in behind a "we normalise match
types" rule.

The mapping is **hard-coded in Python, not config** (spec §8.4), so no YAML edit can ever
point it at `BROAD`. Severity is WARNING, not INFO, so it appears in the report body.

Reference: [About changes to phrase match and broad match modifier](https://support.google.com/google-ads/answer/10286719)

## A4 — Hybrid negative architecture

Preserve the `Scope` field. Do not flatten everything to campaign negatives.

```
ACCOUNT
├── ACCOUNT_JUNK
└── OUTSIDE_GEO

SHARED CAMPAIGN LISTS
├── ROUTE_BRAND
├── ROUTE_COMPETITORS
├── STAGE1_HOLD_COMPARISON
├── STAGE1_HOLD_ACTION
└── STAGE1_HOLD_URGENCY

CAMPAIGN-SPECIFIC
└── GENERIC_EXCLUDE_SPECIALTY

AD-GROUP-SPECIFIC
└── ORTHO_PROVIDER_TO_KNEE
```

Better than duplicating a hundred negatives five times — not least because one of the five
copies always goes stale.

**Consequence for the collision engine:** a negative is not dangerous because it could
block some positive somewhere in the account. It is dangerous when it blocks a positive
**in a place where that negative actually applies**. For a shared list, that means
resolving the list's `applies_to` campaigns *first*, then checking overlap. Scope-blind
checking produces a wall of false BLOCKERs, and a wall of false BLOCKERs teaches everyone
to stop reading the report. Full algorithm in spec §9.5.

References: [account-level negative keywords](https://support.google.com/google-ads/answer/11396330),
[negative keyword lists](https://support.google.com/google-ads/answer/2453987)

## A5 — Call assets

One default number for Stage 1, with optional overrides:

```yaml
call_assets:
  default:
    country: IN
    number: REQUIRED
    schedule: REQUIRED
  overrides:
    campaigns: {}
    ad_groups: {}
```

Nine ad groups do not imply nine phone numbers. If a specialty later gets a properly
staffed coordinator line, it becomes a campaign override:

```yaml
overrides:
  campaigns:
    "MLN | Search | Nephro | Jaipur":
      number: "+91…"
      schedule: "…"
```

Resolution is most-specific-wins — ad group, then campaign, then default — which is how
Google resolves call assets across levels. `AD-006` requires every ad group to *resolve*
to an asset, not to declare one.

Reference: [About call assets](https://support.google.com/google-ads/answer/2453991)

## A6 — Landing-page checking is blocking

Per destination URL:

```
 1. Parse URL                    7. Cap redirect depth
 2. HTTPS required               8. Final status must be 200
 3. Domain must be allowed       9. Final URL still on an allowed domain
 4. GET request                 10. Retry with GoogleAdsBot user agent
 5. Timeout ~10s                11. Record latency
 6. Follow redirects            12. Record final URL
```

Three outcomes:

```
PASS      /google/neurologist-jaipur         200   1.23s
BLOCKER   /google/knee-replacement-jaipur    404
BLOCKER   /google/dialysis-jaipur            redirected to unrelated domain
UNKNOWN   /google/apex-jaipur                network validation could not complete
```

**`UNKNOWN` does not equal `PASS`.** If URL validation cannot complete, no `READY`
deployment build is produced — the run ends as `DRAFT`, quarantined and marked
`DO_NOT_IMPORT`, exit code 6 (spec §10.5).

**This overrides the earlier draft**, which let `--no-network` produce a normal passing
build with a "URL checks skipped" note. Fail-closed here is annoying for about twelve
seconds and then saves us from uploading ads to a page the web team renamed on Wednesday
afternoon.

Reference: [Destination not accessible](https://support.google.com/adspolicy/answer/16428223)

## A7 — Weekly operating rhythm

```
MONDAY    Siddhant + Gaurav — efficiency review
          Qualified / Appointment / OPD
          budget and bidding decisions if warranted

FRIDAY    Gaurav — Google Ads search-terms export, previous 7 days
          → input/search_terms/
          → run Watchdog
          → review routing / junk / concentration
          → approved changes into 03 KEYWORDS and 01 ACTIONS
```

v1 is a manual export. Google Ads API ingestion is a later phase and **must not block
v1**. Reliable software a human triggers on Friday comes before an autonomous process
poking Google's API at 3 a.m. — which is simply a new category of surprise.

---

# Corrections — applied before Phase 0

Seven contradictions between `rules.yaml` and decisions A1–A7, caught in review. All are
now fixed. Recorded because each is the kind of thing that quietly reappears.

| # | Was | Now | Why |
| --- | --- | --- | --- |
| C1 | `shared_lists.*.applies_to: []`, "fill in Phase 3" | Filled with the four non-brand campaigns | Approved routing policy, not something a parser should discover |
| C2 | `budget_tolerance_pct: 2` | `monthly_budget_tolerance: 0` + `daily_budget_rounding_decimals: 2` | 2% quietly made ₹60,760–₹63,240 acceptable. A2 said *exact* |
| C3 | Four invented Watchdog thresholds | All `null`, `concentration_mode: rank_and_review` | We have no Apex data. A number invented today becomes policy by accident |
| C4 | `require_utm_params`, `require_lpurl_in_template: true` | Auto-tagging + GCLID required; UTMs recommended; template validated only if present | Would have blocked a valid campaign because nobody added an unnecessary tracking template |
| C5 | `require_call_number_in_ad` | `require_resolved_call_asset` + `require_call_asset_schedule` | The number is not meant to be stuffed into RSA text; what matters is that the entity resolves |
| C6 | One flat `negatives.csv` | Four artifacts: account / shared list / campaign / ad group | Export is where the scope architecture is most easily destroyed for convenience |
| C7 | "No PII in logs" | Also: exceptions, console, dashboard HTML, findings.json, actions report, diagnostic previews | Reports persist. A traceback should not print somebody's mobile number |

Plus the `AGENTS.md` layering rule, which now distinguishes workbook (approved values),
config (rules governing them), Python (logic) and `DECISIONS.md` (frozen policy) — so
nobody "helpfully" moves budget allocation out of the workbook and defeats the
source-of-truth design.

---

# PRE-PHASE findings — Workbook Schema Reconnaissance

`config/workbook_schema.yaml` v1 was inferred and wrong. v2 is written from the actual
file. What was actually found:

| Finding | Consequence |
| --- | --- |
| `02 BUILD` has six banner-headed sections (`CAMPAIGN SETTINGS — ONE ROW PER CAMPAIGN`, `AD GROUP BUILD`, `LANDING PAGE BUILD BRIEFS`, `SUPPORTING ASSETS`, `MEASUREMENT CONTRACT`, `RSA 1`) | No generic `ACCOUNT`/`ADS`/`CONVERSION` sections exist. Schema rewritten. |
| `RSA 1` is **wide** — one row per ad group, `H1…H12`, `D1…D4` | Unpivot on parse. 12 headlines, 4 descriptions — within the 3–15 / 2–4 limits. |
| `03 KEYWORDS` is **one registry**, split by a `Type` column (Keyword / Negative) | Not two sections. 112 positives, 226 negatives, all `APPROVED`. |
| `Scope` is a human sentence: `Account`, `Ad group`, `Campaign: MLN \| Search \| Generic \| Jaipur`, `Shared list → Neuro, Generic, Ortho, Nephro` | Needs a real parser. The shared-list form names campaigns by **short name**. |
| The shared-list scope already encodes `applies_to` — and it matches C1 exactly | Both sources kept; `NEG-008` asserts they agree rather than picking one |
| `01 ACTIONS` has **two** tables with different columns | Two sections, not one |
| Landing pages are **paths** (`/google/apex-jaipur`), not URLs | Join `landing_pages.base_url` before checking. New config key. |
| The call number lives in `02 BUILD` campaign columns as `[REQUIRED BEFORE LAUNCH]` | **The number belongs to the workbook, not config.** Config now holds only the resolution rule and the placeholder vocabulary |
| `COPY / PASTE VALUE` is derived (`"text"` / `[text]`) | `KW-009` regenerates and cross-checks it |
| Three dashboard panels state figures the compiler also computes | Parsed, recomputed, disagreement reported — never trusted |
| Budgets: 5,000 + 20,000 + 17,000 + 10,000 + 10,000 | = ₹62,000 exactly. Zero tolerance is achievable today. |
| 95 negatives use Broad match; 0 positives do | Correct. `allowed_positive_match_types` and `allowed_negative_match_types` are now separate keys |

---

# A8 — Google Sheets (recommendation, awaiting confirmation)

**Question:** can the workbook live in Google Sheets instead of Excel?

**Recommendation: yes, edit in Sheets — export to `.xlsx` for each build.**
`File → Download → Microsoft Excel` into `input/workbook.xlsx`. Every rule in the spec
applies unchanged, and the tool still holds no credentials of any kind.

Direct Sheets API reading is **not** in v1: it needs a Google Cloud project, a service
account and a stored key — the exact thing spec §16.2 forbids — to save one menu click.
It can be a self-contained later phase with its own review.

**Source-of-edits rule (approved):**

> All human edits happen in the canonical Google Sheet. `input/workbook.xlsx` is an export
> artifact and must never be edited directly.

An edit made in the export is invisible to the team, missing from the Sheet's revision
history, and destroyed by the next export.

**`WB-001` is advisory only.** It warns when the local export file is older than
`workbook.export_staleness_warning_days`. It measures **file age, nothing else**, and is
**not** evidence that the export matches the current Sheet — a fresh export of a Sheet
edited one minute later passes it and is already wrong. Without reading the Sheet (which
v1 cannot do without stored credentials), no local check can establish agreement. Report
wording stays modest: "this file is N days old, confirm it is the export you meant".
`WB-002` prints the export's modification time beside its hash in every report.

---

# D1–D4 — locked after Phase 0 review

| ID | Decision | Where enforced |
| --- | --- | --- |
| D1 | Frozen-policy enforcement stays at **config-load time** | `models/config.py` field validators |
| D2 | `extra="forbid"` stays on **every** config model | `Strict` base class |
| D3 | `xlsx_native` is **removed** as a legal production source mode | `WorkbookRules.source` literal |
| D4 | `input/live_export/` is **not** created yet — it arrives with Phase 7 | — |

## D1 — Frozen policy fails at load, not at build

A configuration that permits Broad positive keywords **must fail to load**. This is a
frozen Stage-1 invariant, not a runtime business threshold, and the difference matters:
a runtime threshold is a number someone may legitimately tune, whereas an invariant is a
promise. The contradiction should not be able to exist in a developer's working copy, let
alone reach a build.

Enforced by `KeywordRules._no_broad_positives`. Test:
`test_config_that_permits_broad_positives_will_not_load`.

## D2 — Unknown config keys fail loudly

`extra="forbid"` on every model. A mistyped key (`monthly_budgett`) must not silently
disable the rule it was meant to set — the failure mode where a safety check appears to
be configured and simply is not.

The cost is deliberate friction: adding a config key requires adding it to the model.
Accepted. Test: `test_unknown_key_is_rejected`.

## D3 — One production source mode

`workbook.source` accepts **only** `google_sheet_export`. The canonical human source is
the Google Sheet; the compiler input is its `.xlsx` export. A second legal mode would
have been a standing invitation to point the compiler at a hand-edited file and call it
canonical.

Synthetic `.xlsx` fixtures are built by `tests/fixtures/build_fixtures.py` and read
through the same path as a real export — they need no production mode of their own.
Test: `test_xlsx_native_is_rejected`.

## D4 — `input/live_export/` deferred

Not created, not referenced by any code path. It arrives with the drift checker in
Phase 7. An empty directory that exists for three months teaches everyone to ignore it.

`mypy --strict` remains on the whole package (Phase 0 deviation b, accepted).
