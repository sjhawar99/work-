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

---

# D5–D7 — locked after Phase 1B review

| ID | Decision |
| --- | --- |
| D5 | `(Campaign, Ad group)` is the canonical entity identity everywhere |
| D6 | The three negative-routing encodings are all authoritative and must agree |
| D7 | The shifted-row acceptance condition is about semantics, not object equality |

## D5 — Canonical composite identity

Ad-group names are **not** assumed globally unique. `models/identity.py` defines
`AdGroupKey(campaign, ad_group)`, and every domain object that names an ad group exposes
it: `AdGroupBuild.key`, `ResponsiveSearchAd.key`, `Keyword.key`, `Negative.key`.

Today's nine names happen to be unique. That is one hospital's accident, not a property
of the system. The moment Apex adds Mansarovar, Bikaner or Udaipur:

```
MLN | Search | Neuro | Jaipur          → Neuro | Provider
Mansarovar | Search | Neuro | Jaipur   → Neuro | Provider
```

a landing-page brief saying `Neuro | Provider` identifies nothing.

`LANDING PAGE BUILD BRIEFS` has no Campaign column, so the name is resolved through
`AD GROUP BUILD` by **`STR-LP-001`**:

```
0 matches   → BLOCKER
1 match     → valid
>1 matches  → BLOCKER, naming every campaign that claims the name
```

`resolve_landing_pages()` returns only unambiguous matches — a silent guess there would
defeat the rule that exists to catch the ambiguity.

**Preferred long-term fix: add a Campaign column to the Landing Page Build Brief
section.** Explicit beats a clever join. Recorded as the next workbook-schema improvement.

## D6 — Three encodings, one truth, no silent winner

Routing is written down in three places, and each has a distinct job:

| Where | What it is |
| --- | --- |
| `rules.yaml → shared_lists.applies_to` | **Approved routing policy** |
| `03 KEYWORDS → Scope` | **Actual negative registry assignment** |
| `02 BUILD → Negative lists / routing` | **Operator build instruction** |

All three must agree. None is silently preferred over the others. Phase 3 compares all
three; any disagreement is **`NEG-008` BLOCKER**, naming every side.

They agree today. That is reassuring once and dangerous forever — which is exactly why
the agreement gets checked rather than assumed.

**Short campaign names are resolved by an explicit alias map, never by substring
matching.** `"Neuro" in campaign_name` is not governance; it is a coincidence that holds
until the second Neuro campaign exists. `negatives.campaign_scope_aliases` maps each
short name to exact campaign names, and **`STR-008`** (shipped in Phase 2) fails when an
alias points at a campaign that does not exist, or when a campaign has no alias. Adding a
campaign therefore becomes a deliberate config decision.

## D7 — What the shifted-row test actually asserts

The Phase 1B acceptance condition was described as "identical typed objects". That cannot
be literally true, and should not be:

```
semantic payload    identical
provenance.sheet    identical
provenance.section  identical
provenance.row      shifted by the inserted offset
```

Provenance exists so the software knows where a record really came from. Normalising it
away to make two objects compare equal would defeat its whole purpose.

Two tests now express this: one compares the semantic payload with `row` excluded, the
other asserts that within each section every record moved by the same non-zero offset, a
whole number of inserted rows, with sheet and section unchanged.

---

# Phase 5 parking lot — no field disappears silently

Unknown workbook columns currently produce one `ING-100` INFO at parse time. That is
correct *during parsing*: the parser describes, it does not judge.

It is **not** sufficient at compile time. By Phase 5 every non-empty workbook field must
land in exactly one of three places:

| Field | Destination |
| --- | --- |
| Known and mapped | Google Ads Editor output |
| Known and intentionally manual | `MANUAL_STEPS.md` |
| Unknown and non-empty | `UNMAPPED SOURCE FIELD` — blocks a READY build |

Requiring explicit classification is the point. Otherwise somebody adds

```
Campaign: Audience exclusion
```

to the workbook, the parser says "INFO: unknown column", and the compiler cheerfully
produces a build without it — an elegant path to a wrong account.


---

# Phase 3 note — which source decides where a shared list reaches

`NEG-008` compares all three routing encodings and blocks on disagreement (Decision D6).
But the collision engine needs a single answer to "does this negative reach this keyword?"
*while* it runs, including on a workbook where the three disagree.

**It uses the workbook's `Scope` cell, and nothing else.** That is the executable
assignment — what this workbook would actually build. Approved policy and operator routing
answer a different question, and `NEG-008` answers it separately.

There is **no policy fallback**. When a `Scope` cell resolves to no campaign this tool can
name, the negative is *not evaluable*:

```
unresolved scope
      ↓
NEG-009 BLOCKER            (the build is invalid)
collision_status = UNKNOWN (that negative was not checked)
```

Not: "scope is broken, so borrow policy and continue." Substituting policy would report a
synthetic collision result for an assignment the workbook does not contain — the engine
repairing an invalid workbook rather than describing it. The two jobs stay separate:

```
03 KEYWORDS Scope ──→ executable reach ──→ collision engine

rules.yaml ──┐
             ├──→ NEG-008 reconciliation
02 BUILD ────┘
```

`CollisionScan.status` is `UNKNOWN` whenever anything went unevaluated, `NEG-001` reports
each one as a BLOCKER in its own right, and the report prints `UNKNOWN` rather than a
count — because a scan that found nothing while checking only some of the negatives has
not established that there is nothing to find (guardrail §18.13).

**Two earlier implementations were wrong, in opposite directions.** The first took the
union of policy and scope, on the reasoning that being conservative could only help — a
fixture caught it inventing collisions in campaigns a list never reaches. The second kept
policy as a fallback for an unresolvable scope, which quietly answered a question it had
no basis to answer. False blockers are how a report becomes something people skim; a
confident answer derived from the wrong source is worse.


---

# Phase 4 note — ready-only rules

`AD-012` (the call number is still `[REQUIRED BEFORE LAUNCH]`) must not stop development,
and must stop a deployable build. Rather than write the rule twice, `Rule.ready_only`
marks it and the runner takes a `mode`:

| Mode | Used by | `ready_only` findings |
| --- | --- | --- |
| `validate` | `apex validate` | downgraded to WARNING, suffixed "(blocks a deployable build)" |
| `build` | `apex build` (Phase 5) | full severity |

One rule, one message, two contexts. The alternative — a config flag that turns the rule
off — is exactly the kind of switch that gets left on.

`LP-003` and `LP-004` take their URL results by constructor, because reachability is I/O
and validators are pure. `validators_for(None)` still includes them, and `LP-003` then
reports *"landing-page reachability was not checked in this run"*. Omitting the validator
entirely would have been a silent skip, which §18.13 forbids.


---

# Phase 5 note — two things worth knowing

## The Editor column names are still unverified

`config/editor_schema.yaml` was written from knowledge of Google Ads Editor, not copied
from an export of this account. Editor matches on exact English column names, so a wrong
header means a failed import.

Rather than let that sit quietly in a spec appendix, **every build prints the warning at
the top of `MANUAL_STEPS.md`**, and the standing procedure tells the operator to treat a
clean "Check changes" in Editor as the real test. It stops being a footnote nobody reads
and becomes a line the person doing the import has to look at.

Closing it needs one thing from a human: an Editor export of any Google Ads account.

## Scope targets are materialised in the transform

The workbook keeps a campaign- or ad-group-scoped negative's target inside the `Scope`
sentence — `Campaign: MLN | Search | Generic | Jaipur` — and leaves the Campaign column as
an em dash. Export needs it in a column.

That translation happens in the **transform**, where turning human phrasing into machine
fields belongs, and the raw scope is left untouched. A test caught this: the first export
attempt raised `required column 'Campaign' is empty` on exactly those rows, which is the
writer refusing to emit a negative whose target it could not name — the right failure, in
the right place.


---

# Phase 5 corrections — what READY is allowed to mean

Two blocking corrections, both from the same principle:

> `READY` must mean **import-ready**, not "the compiler's own logic passed".
> One unverified external contract is enough to withhold it.

## 1. An unverified Editor schema withholds READY

`config/editor_schema.yaml` now carries its own verification state:

```yaml
verified: false
verified_against:
  export_date: null
  editor_version: null
  source_sha256: null
  reconciled_by: null
```

While `verified: false`, `decide()` returns `DRAFT` no matter how clean everything else
is — quarantined directory, `DO_NOT_IMPORT.txt`, `latest` untouched, exit 6. The notice
names every open contract, and the manifest records `editor_schema_verified` plus the
provenance of whatever it was reconciled against.

The previous behaviour let a build call itself READY while the column names were guesses.
That is "everything is safe except the part that determines whether Google understands
the files".

**To clear it:** export the account from Google Ads Editor, reconcile every `editor_column`
against that export, set `verified: true`, and fill `verified_against`. Only a human who
has actually done the reconciliation may flip it.

## 2. `EXP-002` — no record *type* disappears either

`EXP-001` is field-level: it catches a column nobody mapped **inside a record type the
exporter already knows about**. It cannot see a record type that never reaches the
exporter at all.

Which is exactly what happened. `transform()` never carried responsive search ads or
supporting assets into `CompiledAccount`, `write_all()` never looked for them, and
`MANUAL_STEPS.md` never mentioned them. Nine RSAs — 108 headlines and 36 descriptions —
and twelve supporting assets vanished from a build that reported itself READY, and the
guardrail written to prevent silent disappearance could not see them, because it only
looks inside the box it is handed.

Now:

* `CompiledAccount.collections()` exposes every record type the compiler produces;
* `config/editor_schema.yaml → inventory` gives each one a destination, `editor` or
  `manual_steps`;
* `EXP-002` blocks the build when a non-empty record type has no declared destination;
* a test asserts the inventory covers `CompiledAccount` in full, so adding a record type
  without classifying it fails the suite.

RSAs and supporting assets are routed to `manual_steps` while the schema is unverified —
Editor does support importing responsive search ads, but ad copy is the worst place to
guess at column names. `MANUAL_STEPS.md` writes out **every headline and description in
full, with character counts**, and every asset in a table. A count is not a
specification: a person retyping ad copy needs the copy.
