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
| A5 | One default call asset, most-specific-wins exceptions; **every number in the workbook** (amended) | §9.6 | order only in `rules.yaml → call_assets`; numbers in `02 BUILD → CALL ASSET REGISTRY` |
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

**Amended in the fourth audit. This is the decision; the YAML below replaced an earlier
config-based version that is no longer valid anywhere in this repo.**

One default number for Stage 1, with optional exceptions. Nine ad groups do not imply
nine phone numbers — a number nobody answers is worse than a number that is merely
generic. `AD-006` requires every ad group to *resolve* to an asset, not to declare one.

Resolution is most-specific-wins — ad group, then campaign, then account — which is how
Google resolves call assets across levels.

### Every number lives in the workbook

A phone number is an approved account value, so it lives in the workbook at every level,
including the account-wide default. `rules.yaml` holds the resolution order and the
placeholder vocabulary, and nothing that could ever be a phone number:

```yaml
call_assets:
  resolution_order: [AD_GROUP, CAMPAIGN, ACCOUNT]
  placeholder_tokens: ["[REQUIRED]", "[REQUIRED BEFORE LAUNCH]", "REQUIRED", "TBD", "—"]
  placeholder_blocks_ready_build: true
```

The three levels read:

| Level | Source |
| --- | --- |
| `AD_GROUP` | `02 BUILD → CALL ASSET REGISTRY`, row with `Level: AD_GROUP` |
| `CAMPAIGN` | that registry with `Level: CAMPAIGN`, else the `CAMPAIGN SETTINGS` row |
| `ACCOUNT` | that registry with `Level: ACCOUNT` |

`CALL ASSET REGISTRY — NUMBER BY LEVEL` is an **optional** section of `02 BUILD` with
columns `Level`, `Campaign`, `Ad group`, `Call phone number`,
`Call schedule / reporting`, `Status`, `Why`. It is absent from the live workbook, and
absent means *no exceptions*: all nine ad groups resolve through their campaign row.

If a specialty later gets a properly staffed coordinator line, it becomes a row:

| Level | Campaign | Ad group | Call phone number | Call schedule / reporting | Status |
| --- | --- | --- | --- | --- | --- |
| `CAMPAIGN` | `MLN \| Search \| Nephro \| Jaipur` | | `+91…` | `Mon-Sat 08:00-20:00 IST` | `APPROVED` |

### The registry grammar is strict (`AD-014`, `AD-015`)

| Level | Campaign | Ad group |
| --- | --- | --- |
| `ACCOUNT` | must be blank | must be blank |
| `CAMPAIGN` | required | must be blank |
| `AD_GROUP` | required | required |

Plus: the named campaign and ad group must exist; a number and a staffed schedule are
required; no two rows may govern the same effective scope; and `Status` must be
`APPROVED` before the number can reach a deployable build.

The strictness is not tidiness. A cell the machine ignores is a cell a human will trust:
`Level: ACCOUNT · Campaign: Neuro` reads as *the Neuro number* and applied to all five
campaigns, and `Level: CAMPAIGN · Ad group: Neuro | Provider` read as one ad group and
covered the whole campaign. A row must never read narrower than it acts.

### Why this changed

The original A5 put `call_assets.default` and `call_assets.overrides` in `rules.yaml`,
where each could hold a real phone number. That broke the layering rule on its own — an
approved account value in the rules file — but the damage was downstream: the validator
resolved the config override while `MANUAL_STEPS.md` printed the campaign row, so with an
override in play the number **checked** and the number an operator was **told to create**
were different numbers, and nothing in the system could notice. Full history in the
fourth-audit section at the end of this file.

`callassets.resolve()` is now the only producer of a `CallAsset`, `transform()` calls it
once, and `MANUAL_STEPS.md` and the manifest render from that one object — including the
exact workbook row that supplied the number.

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

---

# CI was red for nine commits, and I was not looking

A reviewer with direct repository access pointed out that GitHub showed no corroborating
CI status for the commit they were reading, and declined to treat "274 tests, ruff clean,
mypy strict clean" as verified. That was the right call, and the truth was worse than a
missing signal: **CI had run on every commit since Phase 0 and failed every time.**

Every run died at the first step, `ruff format --check .`.

## Root cause

The dev extras declared `ruff>=0.5`. CI installs fresh, so it got whichever ruff was
newest; locally I had 0.15.8. Newer ruff formats Python code blocks inside Markdown;
0.15.8 refuses with *"Markdown formatting is experimental, enable preview mode"*.

```
local  ruff 0.15.8   70 files   docs/*.md skipped     -> clean
CI     ruff newest   80 files   docs/*.md formatted   -> would reformat the spec
```

So every "ruff clean" I reported was true of my machine and false of CI's. Not a lie, and
not an excuse: an unpinned toolchain means the check does not have a single answer, and I
reported one answer as though it did.

## What changed

* The four tools that gate a commit are pinned exactly. A check that disagrees between
  machines is not a check.
* `ruff` is scoped to Python explicitly (`include`, `extend-exclude = ["*.md"]`) rather
  than relying on a particular version's willingness to skip Markdown. The spec's code
  blocks are hand-wrapped for a human reader; reformatting them is not an improvement.
* The workflow prints its toolchain versions, so a future divergence appears in the log
  instead of as a mystery failure.

## The standing rule this establishes

Verification claims are made against **a clean environment built the way CI builds one**,
not against my working directory — and CI's own result is checked before a phase is
called complete.

One consequence worth stating plainly: in a fresh checkout the suite reports
**274 passed, 7 skipped**, not 281 passed. The seven are the real-workbook reconciliation
tests, which skip when `input/workbook.xlsx` is absent — by design, because client data is
never committed. Quoting the local number without that context overstated the evidence.

---

# Phase 5, second review — declared destination is not executed destination

Four findings from a reviewer reading the repository directly. All four reproduced before
being fixed.

## 1. `EXP-002` checked the label, not the conveyor belt

The guard asked only *"does this record type appear in `inventory`?"*. It never asked
whether the declared destination could carry it.

Reproduced exactly as predicted. Changing one line — `ads: manual_steps` → `ads: editor`,
the change somebody makes the day the schema is verified — produced:

```
outcome:            READY
files:              7, none containing an ad
EXP-002:            NONE
MANUAL_STEPS.md:    no longer lists the RSAs
```

Nine ads disappeared again, and this time the inventory declared everything accounted for.

`EXP-002` is now a route-integrity guard with three questions:

| | |
| --- | --- |
| collection has no destination | BLOCKER |
| destination is `editor`, no Editor writer exists | BLOCKER |
| destination is `manual_steps`, no manual renderer exists | BLOCKER |

Capability is declared by the modules that do the work — `EDITOR_WRITERS` beside the
writer, `MANUAL_RENDERERS` beside the renderer — so a destination cannot claim a handler
that is not there. A test asserts `EDITOR_WRITERS` matches what `write_all` actually
emits, and another asserts the two sets together cover `CompiledAccount` exactly.

`test_a_destination_without_a_handler_blocks_the_build` **inverts** when RSA export is
implemented: it asserts `"ads" not in EDITOR_WRITERS` first, with a message saying so.

## 2. `verified: true` did not require provenance

Prose asking a human to fill the four provenance fields is not enforcement. This loaded
happily and produced READY builds:

```yaml
verified: true
verified_against: {export_date: null, editor_version: null, source_sha256: null, reconciled_by: null}
```

A pydantic `model_validator` now refuses it at config load: `verified: true` requires all
four fields, and `source_sha256` must be 64 hex characters. An unverifiable claim of
verification cannot reach `apex build`.

Test fixtures use a plausible digest rather than a row of zeros. Rejecting all-zero
hashes was considered and dropped: a rule whose only purpose is to catch badly built
fixtures belongs in the fixtures.

## 3. The suite depended on somebody's network

`tests/integration/test_cli.py` ran `apex validate` without `--no-network`, so four CLI
tests fetched real Apex URLs. Fast where the network is fast, hanging where it is not,
and "the suite passes" became a statement about a connection rather than the code.

`--no-network` is now the default in the CLI test helper. Reachability behaviour is
tested in `tests/unit/test_urlcheck.py`, where the fetcher is injected and every outcome
is deterministic.

**Verified with sockets blocked** (`socket.connect`, `create_connection` and `getaddrinfo`
all raising), in a clean checkout with a fresh `pip install -e ".[dev]"`:

```
ruff format --check .   71 files already formatted
ruff check .            All checks passed!
mypy src/apex_ads       Success: no issues found in 51 source files
pytest                  282 passed, 7 skipped in 11.15s
```

## 4. A verified build announced that it was unverified

`MANUAL_STEPS.md` printed the unverified-schema warning unconditionally, so the first
genuinely READY build would have said `READY` and *"column names are unverified"* on the
same page. Not dangerous; exactly the kind of contradiction that teaches people to skim
warnings. It now prints one state or the other — the warning, or the provenance it was
verified against.

## The lesson, one layer down from the last one

Phase 5's first review established that **field-level safety is not entity-level safety**.
This one establishes the next: **a declared destination is not an executed destination.**
A guard must prove the crate has a label *and* that the belt it names exists.


---

# Phase 5, third audit — ten findings

A reviewer read the source at `8f3408c`. Four had already been fixed in `4d78a83`
(route integrity, provenance enforcement, and the network-dependent CLI tests); the rest
were live, and every one was reproduced before being touched.

## The three that could spend the account wrong

**Daily budget authority.** `BUD-004` is a WARNING and the transform copied the workbook's
`Avg daily budget` cell straight into Editor's `Budget` column. A ₹5,000/month campaign
with ₹9,999 in the daily cell produced **zero blockers and exported ₹9,999** — an approved
₹62,000 plan able to spend that in a day. The daily figure is arithmetic on the approved
monthly figure, so `transform()` now derives it and the workbook cell is a cross-check
only. Upgrading `BUD-004` to a blocker was the wrong fix: it would have left the
spreadsheet authoritative for derived arithmetic.

**Decision A5 was never implemented.** `CODEX_TASKS.md` marked "ad group → campaign →
account, most-specific-wins" complete and said acceptance test 35 covered it. The resolver
did exactly one thing: read the campaign row. `rules.call_assets.resolution_order` was
declared and never consulted, and test 35 did not exist. The resolver now walks the
configured order across three real levels, and test 35 exists.

**`NEG-008` counted a vanished source as agreement.** The docstring said all three routing
sources must agree; the implementation dropped empty sources before comparing, so a shared
list could disappear entirely from `02 BUILD` and the two survivors would "agree". All
three sets are now compared including empty ones, and an absent source is reported as
`ABSENT` — a disagreement, not an abstention. Campaign and ad-group sets are excluded from
the comparison, since measuring them against a shared-list `applies_to` is a category
error that manufactures false disagreements.

## The rest

| | |
| --- | --- |
| No outer exception boundary in the CLI | Unexpected failures printed a raw traceback and exited 1. Now a redacted log, a short message, exit 3. |
| Run IDs could collide, and the build deleted the collision | Second resolution plus the workbook hash. `run_build` made room with `rmtree` — the overwrite mechanism sat directly beneath the comment promising no run overwrites another. IDs now carry microseconds and a random suffix, and an existing run directory raises rather than being deleted. |
| The parser discarded unclassified columns | A populated `Audience exclusion` column in `02 BUILD` was dropped with an INFO reading "None needed", upstream of `EXP-001`. `ING-102` now blocks a populated undeclared column in a build-critical section; empty notes columns stay INFO, and sections that legitimately carry notes opt in. |
| Manifest weaker than its own spec | Now records tool version, git commit, config paths beside hashes, and hashes **every** artifact — `MANUAL_STEPS.md` and the report included, since a human acts on those too. Written last so it can hash the report. |
| CI green but not reproducible | Runtime dependencies were open-ended, so the green run installed whatever existed that day. All pinned. Python 3.10 is now tested, because the project claims it and has already shipped two accidental 3.11-only APIs. |
| Supporting asset `status` unread | The model carried it, no validator read it, and `MANUAL_STEPS.md` did not show it — so an asset marked `VERIFY FACT` could be typed into the account as approved. `AD-013` reports it and the manual table leads with the status column. Found two in the real workbook. |
| DRAFT headline always blamed URLs | It announced incomplete URL validation even when every destination passed and the unverified schema was the sole cause. It now names the reasons that actually apply. |

## Verified

Clean checkouts, fresh installs, all outbound sockets blocked, on both supported Pythons:

```
Python 3.10   ruff clean · mypy clean · 295 passed, 7 skipped in 13.33s
Python 3.11   ruff clean · mypy clean · 295 passed, 7 skipped in 12.25s
```

## The lens, stated once

Every defect in this audit had the same shape, and it is worth keeping:

> The dangerous failures are not where something is missing entirely. They are where the
> system has enough information to look complete, but one layer silently stops enforcing
> the promise made by the layer above it.

`BUD-004` warned while the transform copied. The task file claimed A5 while the resolver
ignored it. `NEG-008` promised three sources and compared two. The parser promised nothing
disappears and dropped columns before models existed. In each case the upper layer's
promise was intact and the lower layer had quietly stopped keeping it.


---

# Fourth audit — the six before Phase 6

Six blocking findings plus two non-blocking, on `0f86d89`. Each was reproduced before it
was touched. The reviewer's gate was explicit: after these, stop auditing Phase 5 and
start Phase 6.

## A5 amended — every call number lives in the workbook

**This is a change to a locked decision, and it is worth stating plainly.** A5 said the
overrides live in `rules.yaml`. They do not any more.

`call_assets.overrides.ad_groups`, `overrides.campaigns` and `account_default` could each
hold a real phone number, in the file whose own header says it must never acquire an
approved account value. That alone was a layering violation. The dangerous part was
downstream: `AD-006` and `AD-012` resolved through the config override, while
`MANUAL_STEPS.md` printed `campaign.call_phone_number` straight off the campaign row. Set
an ad-group override and the number **validated** and the number an operator was
**instructed to create** were different numbers — and no test, rule or report could
notice, because each half was internally consistent.

Reproduced first: a fixture with `+91 111 111 1111` on the campaign row and
`+91 999 999 9999` as an ad-group override resolved to the override and rendered the
campaign row.

The fix:

* those three config keys are gone, and `CallAssetRules` forbids unknown keys, so they
  cannot return by accident (`test_call_asset_rules_cannot_hold_a_phone_number`);
* exceptions live in a new **optional** `02 BUILD` section, `CALL ASSET REGISTRY — NUMBER
  BY LEVEL`. Absent — as it is today — means *no exceptions*, and every ad group resolves
  through its campaign row exactly as before;
* `AD-014` blocks a registry row naming a campaign or ad group that does not exist. A
  typo'd override is not an override; it is an override that silently did not happen;
* `callassets.resolve()` is the only producer of a `CallAsset`. `transform()` calls it
  once and stores the result on `CompiledAccount.call_assets`; `MANUAL_STEPS.md` and the
  manifest render from that object; the per-campaign block no longer prints a number at
  all, and a test asserts no number appears outside the resolved table;
* `call_assets` is a compiled record type routed to `manual_steps`, so `EXP-002` guards
  it like every other type.

Regression test, exactly as asked: workbook default and ad-group override set to different
numbers, then assert the exact number validated is the exact number rendered.

## AD-013 graded severity backwards

`severity = WARNING if status else BLOCKER` said: a blank status blocks, and any filled-in
status merely warns. That is the wrong way round. A blank cell is an unfinished workbook.
`VERIFY FACT` — which the real workbook carries on "Diagnostics Available" — is a human
saying *this claim about a hospital may not be true*, and it was the one that reached a
READY build. `AD-013` is now BLOCKER at every non-approved status and `ready_only`, so
development still runs and no deployable build carries an unapproved asset.

## Search queries are structurally unprintable, before Phase 6 exists

`redact()` masks phone- and email-shaped substrings. It is shape-based, so
`paralysis treatment cost dr sharma` passes through untouched — and that is the text the
Watchdog will read thousands of rows of.

`util/searchterm.py` holds the query in a private field. `str`, `repr`, f-strings, `%`,
`format()`, `logging` and traceback rendering all resolve to `query:q<hash>`. Getting the
words back means calling `.reveal()` by name, and a guardrail test asserts that call
appears only in modules listed in `REVEAL_ALLOWED`. `SearchTermError` carries file, row,
hashed query ID, category and error code — nothing quotable.

Building it surfaced a real bug in the design: a bare hex handle can come out all digits,
and `redact()` correctly rewrote `query:922467584280` to `query:[phone]`, so two different
queries logged identically and the handle stopped being a handle. Handles now start with
`q`.

This is in place *before* the Watchdog, because "remember not to log the query" is not a
guarantee.

## The report omitted the finding that failed the build

`EXP-001` and `EXP-002` are discovered inside `run_build`, after validation has produced
its result — and the CLI's report callback was still writing `loaded.result`. Route `ads`
to `editor` and the process exits 2 while `PRE_FLIGHT_REPORT.txt` lists nothing wrong.
"FAILED, and nothing is wrong" is the most corrosive thing a report can say.

`run_build` now hands the compile-stage findings to `write_report`, and
`runner.merge()` produces one final set in the same sort order. Two CLI regression tests:
exit 2 with `[EXP-002]` in the report, and `[CMP-101]` in a DRAFT report.

## A negative list name may belong to exactly one level

`NEG-008` asks "which level owns this list?" and answers with
`account_lists | campaign_sets | ad_group_sets` versus `shared_lists`. Nothing stopped a
name appearing in two, and the answer would then depend on which branch ran first.
`NegativeRules` now rejects overlap — and repetition within one level — at config load.

## Two identical column headings are a structural BLOCKER

`_header_index` kept the first occurrence and dropped the rest. A `Status` column pasted
back into `02 BUILD`, or `Monthly budget` beside `Monthly Budget`, left the parser reading
one position and ignoring the other, with nothing reported. Whoever was maintaining the
other one had a coin flip. `ING-007` now raises before a single row is read, naming both
positions as Excel letters, because "duplicate column Status" sends somebody hunting
through a wide sheet and "column S and column W" does not.

## READY requires source somebody can check out again

`git_commit: "abc123"` recorded from a working copy with edited validators names a commit
whose code never ran. `"unknown"` names nothing. Both satisfied a manifest test that only
asserted the key was present. `source_provenance()` now records the commit **and** whether
the tree was dirty, and an unknown or modified source withholds READY the same way an
unverified Editor schema does, with `SOURCE NOT REPRODUCIBLE` in `DO_NOT_IMPORT.txt`.

Tests state their provenance explicitly rather than inheriting the developer's git status,
so a READY test is a test of the compiler and not of whether somebody had saved a file.

## Not done

**A dependency lock file (P3).** Dev and runtime dependencies are pinned exactly in
`pyproject.toml`; their transitive dependencies are not. Deferred deliberately, and named
here so it is not mistaken for finished.

## Verified

Clean clone of `d19a1ce`, fresh installs, all outbound sockets blocked, on both supported
Pythons:

```
Python 3.10.20   ruff clean · format clean · mypy clean · 326 passed, 7 skipped in 15.52s
Python 3.11.15   ruff clean · format clean · mypy clean · 326 passed, 7 skipped in 14.49s
```

The 7 skips are the real-workbook tests; `input/workbook.xlsx` is not committed, so a
clean clone has nothing to point them at. Against the real workbook locally, `validate`
still reports the same 12 blockers and `build` still exits 2 — no regression, and no
newly-invented finding.

## The same lens, again

Every one of the six is the same shape as the last audit's three:

> The dangerous failures are not where something is missing entirely. They are where the
> system has enough information to look complete, but one layer silently stops enforcing
> the promise made by the layer above it.

The validator resolved one number and the instructions printed another. The rule graded
danger by whether a cell was filled in. The report announced a failure and listed nothing.
The header index chose silently between two columns. In each case the upper layer's
promise was intact and the lower layer had quietly stopped keeping it.


---

# Fifth audit — the fixes had defects of their own

Three defects, all inside machinery the fourth audit introduced. Two of the three exist
*because* that patch added a new registry and a new privacy primitive: new interfaces get
the least scrutiny precisely when they are load-bearing for everything built next.

Each was reproduced before being touched.

## The search-query protection was not structural

The module claimed, in its own docstring, that `json.dumps` of a `__dict__` could not
expose a query. It stored the text in a private field of an ordinary frozen dataclass, so
all of this returned the patient's search verbatim:

```
vars(term)                → {'_text': 'kidney failure last stage how long to live', ...}
term.__dict__             → same
dataclasses.asdict(term)  → same
json.dumps(term.__dict__) → same
term._text                → the query
```

The tests attacked `str`, `repr`, formatting, logging and `.reveal()` usage, and none of
those five paths. **A claim of structural safety that a one-line `vars()` defeats is worse
than no claim**, because everything built on top of it is written as though the guarantee
holds — and the Watchdog was going to be built on top of it.

The query is now stored nowhere on the object. It lives in a closure captured at
construction; the class is `__slots__`-only and is not a dataclass; `__getstate__` and
`__reduce__` refuse, so `pickle`, `copy` and `deepcopy` cannot take it out through the
serialisation protocol; and generic `json.dumps(term)` raises rather than rendering
fields. The guardrail now bans the mangled closure slot `_SearchTerm__open` as well as
`.reveal()` — checking only the documented boundary guards the front door and leaves the
window. There is also a sweep asserting that no attribute reachable via `dir()` holds the
raw text, so a field added later is covered without anybody remembering a list.

**Left open deliberately: the query ID is still an unkeyed truncated SHA-256.** The
reviewer is right that it is confirmable by dictionary guessing. It is also stable across
weeks, which is exactly what lets the Watchdog say "this junk term is back"; a keyed HMAC
makes handles comparable only within one key, so the key has to outlive every report that
quotes a handle. That trade belongs to the Phase-6 design of how weeks are compared, and
guessing at it now — during a phase being frozen, under an explicit "no further scope
expansion" — would be inventing a persistence requirement before the thing that needs it
exists. Recorded as a named Phase-6 open item, and documented in `query_id()` itself.

## A malformed optional section disappeared

`_optional_section()` caught every exception and returned "not read". So a `CALL ASSET
REGISTRY` that genuinely existed, carrying a deliberate ad-group override, with one
required heading typed `Call phone no.` instead of `Call phone number`, produced:

```
INFO: optional section 'call_asset_registry' not read
registry = []
resolver falls back to the campaign row
build continues
```

The operator's override silently did not happen — reported as an INFO reading "None
needed while the section is optional." That is the exact fail-through the registry was
invented to prevent, reproduced inside the feature that was supposed to prevent it.

Only `MissingSectionError` now returns `None`. Every other structural failure propagates
and blocks.

> **Optional means absence is permitted. It never means broken data is ignored.**
> Absent means the human made no claim; malformed means they made one the machine could
> not read, and the second is never safe to answer with a default.

## The registry was under-validated

`AD-014` checked that targets existed and a number was present, and missed three states:

**Duplicate scope.** Two `AD_GROUP` rows could target one ad group with different numbers;
`resolve()` took whichever came first and nothing said which row won.

**Scope widening.** `Level: ACCOUNT · Campaign: Neuro` reads as *the Neuro number* to a
person and applied to all five campaigns, because the resolver ignores `Campaign` at
account level. `Level: CAMPAIGN · Ad group: Neuro | Provider` read as one ad group and
covered the whole campaign. **A cell the machine ignores is a cell a human will trust**, so
a row must never read narrower than it acts.

**Unapproved status.** `Status` was on the row, optional, and read by nothing — so
`Status: VERIFY` could supply the live phone number of a hospital. The identical bug had
just been fixed for supporting assets (`AD-013`), one layer over.

`AD-014` is now a strict grammar — each level requires exactly the fields it uses and
forbids the ones it ignores, targets must exist, number and staffed schedule are required,
and no two rows may govern the same effective scope. `AD-015` is the status rule, shaped
exactly like `AD-013`: BLOCKER, `ready_only`.

`CallAsset` also carries real provenance now. It previously said `"campaign registry"`
and left somebody to work out which of nine rows that was; it now carries sheet, row and
section, and `MANUAL_STEPS.md` and the manifest print `02 BUILD row 91 · ad group
registry`. The first question anybody asks about a number in a live account is *why is
this number here*, and the answer has to be a row, not a category.

## Governance: one A5, not two

The canonical `A5` section still described the config-based model, complete with its
`call_assets.default` / `overrides` YAML, while the fourth-audit section said that model
was replaced. `DECISIONS.md` tells future agents not to re-infer locked decisions, so
leaving two incompatible A5s in it was an invitation to resurrect the bug. `A5` and the
summary table now state the workbook-only model, with the registry grammar; the
fourth-audit section stays as the explanation of why it changed.

## Verified

Clean clone of `ec26098`, fresh installs, all outbound sockets blocked, on both supported
Pythons:

```
Python 3.10.20   ruff clean · format clean · mypy clean · 368 passed, 7 skipped in 13.72s
Python 3.11.15   ruff clean · format clean · mypy clean · 368 passed, 7 skipped in 12.50s
```

Against the real workbook locally: `validate` still reports the same 12 blockers,
`build` still exits 2, and the absent `CALL ASSET REGISTRY` is reported as
`ING-101 ... is not present in this workbook` — INFO, exactly as an optional absent
section should be. No regression, no newly-invented finding.

## The lens, a third time

> The dangerous failures are not where something is missing entirely. They are where the
> system has enough information to look complete, but one layer silently stops enforcing
> the promise made by the layer above it.

This round it applies to the fixes themselves. The privacy primitive documented a
guarantee it did not implement. The optional-section handler treated "unreadable" as
"absent". The registry validated the fields it thought of and ignored the ones that
decided scope. In each case the upper layer's promise was intact and the lower layer had
quietly stopped keeping it — including when the upper layer was written last week
specifically to keep that promise.


---

# Phase 6 — the Search-Term Watchdog

Phase 5 accepted and frozen. Phase 6 built against five invariants the reviewer froze at
the start, plus task zero.

## Task zero — the keyed query identifier

The unkeyed truncated SHA-256 is gone. `query_id` is now an HMAC under **one stable local
secret** in `.apex_secrets/query_id.key`, git-ignored, created on first run, `chmod 600`,
never in a report, a manifest, a log or a dashboard. Two properties at once:

```
same normalised query next Friday  →  same ID     (recurrence is detectable)
somebody holding findings.json     →  cannot test likely medical phrases
```

Not a rotating key: rotation would break recurrence detection, which is the whole point of
comparing one Friday to the next.

**Operating dependency, stated rather than buried.** Lose the file and IDs generated
afterwards stop joining to historical ones. Back it up alongside the workbook. The manifest
records a *fingerprint* of the key — a hash of it — so a later reader can tell whether two
runs are comparable without holding the secret.

Normalisation matters as much as keying: `Knee  Replacement` and `knee replacement` must
be one handle, or recurrence detection silently misses the recurrence it exists to find.
It reuses the compiler's tokeniser, so "the same term" means one thing project-wide.

## The raw term boundary moved, and got stronger

`SearchTerm` gained two **answer-only** accessors, and this changed the design for the
better. Classification and coverage both need to ask questions about a query; neither needs
to hold it:

* `intersect(vocabulary)` — which of *the caller's own* words appeared. The classifier
  learns "the token `jaipur` occurred" and cannot learn the rest of the sentence.
* `matched_by(keyword, match_type)` — a boolean, from the compiler's own match engine.

The first draft of `run.py` reached for `reveal()` instead, and **the guardrail test caught
it** — which is the first time one of this project's guardrails has failed on code written
after it. `REVEAL_ALLOWED` is still two modules, and `analysis_csv.py` is the only one that
writes words to a file.

Also corrected, per the reviewer: the module no longer claims raw text is *physically*
impossible to extract. The claim is now what it can actually defend —

> Raw search text cannot leak through ordinary rendering, logging, serialisation, copying,
> exceptions or generic object inspection without code deliberately crossing the protected
> boundary.

## Three bugs the first working version had

Each was visible only by running the thing end to end on a fixture and reading the output.

**It proposed negating Apex's own brand name.** Spec §13.5 says negatives come from
`JUNK`, **competitor** `BRAND_LEAK` and `SPECIALTY_LEAK`. The first implementation took all
`BRAND_LEAK`, so an own-brand term served by the wrong campaign produced
`negative: apex (broad)` — and the collision engine did not stop it, because the Neuro ad
group has no `apex` positive to collide with. Own-brand leak is a *routing* problem: the
fix is to cover the term in the brand campaign, and it belongs in `routing_issues.csv`.

**Our own name outranked the word that made a query worthless.** Precedence was
competitor → brand → junk, so `apex hospital job` classified as `BRAND` and raised no
`JUNK` finding at all. The two explicit human lists now come first: a word somebody
deliberately put on a negative list is a decision, while a brand or specialty token is
*inferred* from the keyword table.

**It proposed `negative: in (broad)`.** `neurologist in jaipur` made `in` a token
distinctive to Neuro, and no collision fired. That negative would block nearly every query
in the account. Stopwords are now config vocabulary, excluded from distinctive tokens like
geo terms and intent modifiers — plus a defence-in-depth filter in the suggester, because
the failure mode is catastrophic rather than merely wrong.

A fourth, smaller: YAML 1.1 reads bare `on` as boolean `True`, so the first stopword list
loaded as `[..., True, ...]`. The config schema rejected it at load — the strict models
doing exactly their job.

## The five invariants, and how each is enforced

| Invariant | Enforced by |
| --- | --- |
| Raw term boundary at ingest | `SearchTerm` built in `_row()`; `ParseError` carries file, row, hashed ID, category, code and nothing quotable; guardrail on `reveal()` and the mangled slot |
| Keyed identity before any report | `WD-006` blocks a run whose IDs are unkeyed; manifest records the fingerprint |
| No invented thresholds | `_verdict()` is the only threshold reader and returns `REVIEW` on `None`; a guardrail greps the package for `or 0`-shaped defaults; a test asserts the shipped config is all-`null` |
| Suggestions are not actions | every candidate through the compiler's scope-aware collision engine; conflicts become `ROUTING_CONFLICT` in the same file; guardrail forbids `apply`/`commit`/`auto_apply` |
| No workbook mutation | `--propose-writeback` writes only inside the run directory; a test compares workbook bytes before and after |

## Verified

Clean clone of `99fd9fe`, fresh installs, all outbound sockets blocked, on both supported
Pythons:

```
Python 3.10.20   ruff clean · format clean · mypy clean · 448 passed, 7 skipped in 16.87s
Python 3.11.15   ruff clean · format clean · mypy clean · 448 passed, 7 skipped in 15.96s
```

Against the real workbook locally: `validate` still reports the same 12 blockers, `build`
still exits 2, and `apex watchdog` with no export in `input/search_terms/` exits 2 with
`WD-002` rather than reporting on nothing. The generated `.apex_secrets/query_id.key` is
confirmed ignored by `git check-ignore`.

## Deferred, and named

**A statistical-junk suggester.** Impressions with no clicks is ranked for review and never
worded into a negative, because "this got no clicks" is not evidence about *which word* was
wrong. When thresholds exist, that becomes answerable.

**Ad-group-level expected owner when a specialty has several ad groups.** Routing names the
campaign and leaves the ad group blank rather than guessing which one. Enough to call it
leakage, not enough to pretend precision.


---

# Sixth audit — Phase 6's own arrows

Four blocking semantic defects and one denominator issue, all inside Phase 6. Each was
reproduced before being touched.

The meta-finding first, because it is the most important thing in this file:

> **448 green tests did not clear the phase. Two of them encoded the bugs as desired
> behaviour.** `CARRIES_WORDS` named two raw-query files one line under a docstring saying
> every other output must not contain the words. The coverage test asserted that phrase
> matching requires a literal contiguous run — because that is how the *negative* engine
> behaves. Implementation, documentation and tests all agreed with each other. They agreed
> on the wrong contract.

A test that asserts a membership list is a place to add an exception. The privacy test now
asserts a **count** over everything the run produced, so a future file that starts
revealing queries fails it without anybody remembering to update a set.

## Two raw-query files, where the contract says one

`routing_issues.csv` also carried a `search_term` column. The plain-English guide told
Siddhant that only `search_term_analysis.csv` has the actual searches; that was false, and
the surface he could forward by accident was double what he had been told.

Fixed by removing the column. The query ID joins to the one sanctioned artifact.

Writing the count-based test then caught something I had introduced in the same patch:
`triggering_keyword` in a handle-only file. A keyword is account configuration, not patient
text — **except** that for every exact-match keyword the keyword text *is* the search term.
A column of keywords is a column of queries wearing a different heading. It is now a column
of `search_term_analysis.csv` only, and `Coverage.describe()` says "triggered by a keyword
the workbook approves" without naming it.

## Competitor negatives were widened to the whole account

`ROUTE_COMPETITORS` is approved against four campaigns with **Brand deliberately
excluded**. Suggestions sent every competitor candidate to `ACCOUNT`, and a Google
account-level negative applies everywhere — materially wider than approved policy. The
writeback then hard-coded `List name = ACCOUNT_JUNK` for every account-level candidate, so
an approved competitor negative came back next Friday as junk vocabulary and the taxonomy
classified it accordingly.

**The Watchdog was rewriting the meaning of its own evidence across weeks.**

`Candidate` now carries `destination_list`, `level` and `executable_reach` from the pattern
it came from, and the writeback preserves all three. Nothing infers a destination from a
level any more.

This also changed what a suggestion *is*, for the better. Every candidate text is now a
negative that is already approved, so the finding is never "add this word". It is either
`NOT_REACHED` — the list does not reach the campaign that served the query — or
`NOT_ENFORCED` — it does reach it and the query served anyway, so the approved negative is
not live in the account. Both are true statements about reach or enforcement; neither
invents policy.

## The positive matcher was the negative matcher

`SearchTerm.matched_by()` called `validate.collisions.matches()` and its docstring said
"Google's semantics". That engine implements *negative* semantics — literal token
containment, no close variants, no meaning — because that is what Google negatives do.
Google positive phrase and exact matching consider meaning and apply close variants
automatically, so using it for coverage systematically under-reports it and every
`HELD_DEMAND` built on it was suspect.

Rebuilding Google's matcher offline would be the same mistake with more code. Google
already answers the question: a search-terms export names the keyword that actually
triggered each row. Three separate things now, never conflated:

| | what it is | how it is known |
| --- | --- | --- |
| `triggering_keyword` | the keyword Google served this on | read from the export |
| `approved` | that keyword is in the workbook | set membership |
| `own_keyword` | the workbook names this exact query | normalised identity |

`HELD_DEMAND` is now "it converted, and the workbook has no keyword of its own for it" —
an identity test, not a matching test. `UNAPPROVED_KEYWORD` is new: the account served the
query on a keyword the workbook does not contain. That is drift, not demand, and naming it
separately stops it being mistaken for either.

The method is renamed `matched_by_negative`, and a test asserts `matched_by` no longer
exists — gone by name, not merely unused. There is deliberately no offline positive
matcher to misuse.

## Multiword negatives were exploded into tokens

`_tokens_from_lists()` took every negative and split it into words; `classify()` then
treated any one word as a match. `ck birla hospital` (phrase) became
`{ck, birla, hospital}`, and:

```
99fd9fe classifies the brand core term as: COMPETITOR ('hospital',)
```

`apex hospital jaipur` — the brand's own core term — classified as a competitor query, on
the token `hospital`. The suggester would then have proposed a broad negative on
`hospital`. The collision checker might have caught some of it; it cannot restore semantics
discarded upstream.

Negatives are now kept whole as `NegativePattern(text, match_type, list, level, reach)`,
and classification uses the negative matcher on the complete pattern — the engine that is
*correct* for negatives, applied to negatives. A phrase negative matches its phrase, in
order.

`SPECIALTY_LEAK` consequently produces **no negative at all**. Its only defensible texts
were an unapproved token or the patient's own words, and the second must not leave
`search_term_analysis.csv`. The remedy for a term served by the wrong campaign is routing,
and `routing_issues.csv` says so.

## A share needs a complete denominator

`concentration()` divided each query's cost by the sum of only the *readable* rows. One
unreadable expensive row turns a genuine 25% into a printed 70%, and nothing about the
output looks wrong.

`ParseError` now carries the campaign when that cell was readable, and
`Export.incomplete_campaigns()` names the campaigns whose totals cannot be trusted — every
campaign when a parse error had no readable campaign at all. For those, the absolute cost
is still reported and the percentage is refused. Row-level evidence survives a parse error;
an aggregate does not.

## Not fixed, named instead

**`intersect()` and `matched_by_negative()` are unrestricted query oracles.** A future
module could pass a large medical vocabulary into `intersect()` and recover much of a query
without ever calling `reveal()`. Nothing does that today and the guardrail does not detect
it. Recorded in the module docstring as a limitation rather than described as a guarantee
already met; narrowing it behind a scoped classifier service is the follow-up.

## Verified

Clean clone of `95bf39c`, fresh installs, all outbound sockets blocked, on both supported
Pythons:

```
Python 3.10.20   ruff clean · format clean · mypy clean · 462 passed, 7 skipped in 19.26s
Python 3.11.15   ruff clean · format clean · mypy clean · 462 passed, 7 skipped in 18.18s
```

The new regression tests were run against `99fd9fe` and fail there, which is the point:

```
E  AssertionError: exactly one artifact may hold raw queries; these do:
   ['routing_issues.csv', 'search_term_analysis.csv']

99fd9fe classifies the brand core term as: COMPETITOR ('hospital',)
```

Real workbook unchanged: `validate` reports the same 12 blockers, `build` exits 2.

## The lens, a fourth time

> The dangerous failures are not where something is missing entirely. They are where the
> system has enough information to look complete, but one layer silently stops enforcing
> the promise made by the layer above it.

This round the layer that stopped enforcing was **the test suite**. A guide promised one
raw-query file and a constant named two. A matcher was labelled "Google's semantics" and
implemented the opposite. A list carried an approved reach and a suggestion replaced it
with a wider one. Everything was green.


---

# Seventh audit — the verb escaped

Four blocking findings and three more, all inside Phase 6. The reviewer's summary is the
right way in:

> The latest patch fixed the *text* and *scope type* of a suggestion, but nobody asked
> whether **changing the reach was itself a strategy decision**. The nouns survived review.
> The verb escaped.

## The decision, taken rather than discovered

**Stage 1's Watchdog does not author negative policy. It observes and reports.**

Spec §13.5 is amended to say so, with the original text preserved underneath rather than
quietly replaced. This is Option A of the reviewer's two, chosen deliberately:

* **no new negatives** — the narrowest defensible text for a novel exclusion is either an
  unapproved token or the patient's own query, and the second may not leave
  `search_term_analysis.csv`. A human-review path for candidate text would fix that; it
  does not exist yet;
* **no reach changes** — see below.

What it costs is real and named in the spec: a genuinely new junk term is ranked,
classified and surfaced, and a person writes the negative. The product is a
**negative-policy watchdog**, not a negative-discovery engine, and it now says so.

## `NOT_REACHED` was proposing to rewrite frozen policy

`ROUTE_COMPETITORS` is approved against four campaigns with Brand deliberately excluded. A
competitor term served in Brand produced `NOT_REACHED`, and `_scope()` wrote
`executable_reach + incident_campaign` into a paste-ready row — a proposal to add Brand to
the list.

The previous round's test asserted "a candidate never widens to the account". That was
true and beside the point. It widened **the list**.

A shared negative list only affects the campaigns it is applied to, so extending it is a
change to exclusion policy. It is now `POLICY_SCOPE_REVIEW`: handle-only, no writeback row,
and the reach it prints is the approved one with Brand still absent.

## Neither observation had a valid writeback action

`NOT_ENFORCED`'s candidate text was, by construction, already in the workbook. So its
writeback row said:

```
Keyword text: job    List name: ACCOUNT_JUNK    Status: PROPOSED
```

when `job` was already on `ACCOUNT_JUNK`. Pasted, that is a duplicate. It cannot repair
enforcement.

And the reach change could not have survived the next stage anyway: `NEG-008` requires
`rules.yaml`, the `03 KEYWORDS` Scope cell and the `02 BUILD` routing column to agree, and
the writeback emitted one of the three. The compiler would have blocked the Watchdog's own
fix — the cross-layer failure this project keeps finding, this time between two of its own
phases.

Separately, the shared-list scope was written with full campaign names where the workbook
uses short aliases (`Shared list → MLN | Search | Neuro | Jaipur` rather than
`Shared list → Neuro`), so the row would not have round-tripped through this project's own
`ScopeParser` either.

All three problems disappear at once, because `03_KEYWORDS_append.csv` is gone. The
writeback emits actions only, and the guardrail checks the module's namespace rather than
its prose — the docstring names the file it no longer writes, in order to explain why.

## `NOT_ENFORCED` also claimed more than it knew

"The negative is not live in the account" is stronger than the available evidence. There is
no live account state and no change history here. The term may have served before the
negative was added; the list may not be applied; the workbook may be ahead of the account.
Renamed `OBSERVED_DESPITE_NEGATIVE`, and the remedy names those checks in order and hands
the live-account half to Phase 7.

## `HELD_DEMAND` was my own semantic substitution

The spec says "a converting or high-intent term with **no positive keyword covering it**".
The previous patch replaced that with "the workbook contains no keyword whose text is
literally this query" — a different metric — and kept the name. A green test then proved
the wrong business meaning, which is exactly the failure the sixth audit was about. I did
it while fixing it.

The fixture makes it obvious: `paralysis treatment cost jaipur` was served by the approved
keyword `neurologist jaipur` and converted twice. Google served it. It was not held.

`HELD_DEMAND` now means what it says, with coverage read from the export's triggering
keyword. The metric I had substituted exists under its own name, `EXPLICIT_KEYWORD_GAP`:
covered, converting, and with no keyword of its own — an opportunity to bid and write for
it deliberately.

## Approval was text-only, so drift read as green

`coverage_for()` asked "does any workbook keyword have this text?", so a keyword running in
the wrong ad group was `APPROVED`. The export gives campaign, ad group *and* keyword, and
`AdGroupKey(campaign, ad_group)` is the identity this project spent three phases
establishing. Coverage now distinguishes `APPROVED_HERE` from `APPROVED_ELSEWHERE`; the
demand is covered either way, and the placement is a separate `UNAPPROVED_KEYWORD` finding.

## Row numbers were wrong, and an unverifiable week passed silently

`enumerate(reader, start=2)` carried a comment claiming the numbers matched the
spreadsheet. They did not: a real export has a title line, a date line and a blank before
the header, so the first data row is line 5 and was reported as 2. Every reference the
operator was given — `parse_errors.csv`, `source_row` — was three lines short. The reader
now returns the header's real line number and counts from there.

The preamble was also being discarded, and with no `Day` column `observed_dates` stayed
unknown and `WD-003` never fired — so a thirty-day export could pass as "the previous 7
days". The date line above the table is now parsed, and a range that cannot be established
either way is itself a `WD-003` warning.

## "Exactly one raw-query file" was true because of the fixture

The invariant held because no query happened to equal a string the system prints for
legitimate reasons. Change the query to exactly `job` — an approved negative on
`ACCOUNT_JUNK` — and it appeared in `actions_report.txt` and `dashboard.html`, with only
one module calling `reveal()` the whole time.

**The leak was never through `SearchTerm`. It was through equality with account
configuration.** Guarding `reveal()` cannot close that.

Two changes close it structurally. Findings name the negative's **list**, never its text —
a list name cannot realistically be a search term. And `labels.safe_label()` withholds any
configuration string about to be printed into a handle-only artifact when it matches a
query in this run, pointing at the one file allowed to hold it. `safe_label` never reads a
query; it asks `SearchTerm.has_text()`, so the allow-list stays at two modules.

Both equality cases are now fixtures: query = approved negative, and query = approved exact
keyword.

## Verified

Clean clone of `d980145`, fresh installs, all outbound sockets blocked, on both supported
Pythons:

```
Python 3.10.20   ruff clean · format clean · mypy clean · 462 passed, 7 skipped in 19.13s
Python 3.11.15   ruff clean · format clean · mypy clean · 462 passed, 7 skipped in 17.29s
```

The new fixtures were run against `65dd89d`, which is the point of them:

```
65dd89d, query == approved negative -> files containing the raw query:
    actions_report.txt
    dashboard.html
    negatives_suggestions.csv
    search_term_analysis.csv
    writeback/03_KEYWORDS_append.csv

65dd89d first data row reported as line: 2 (the real line is 5)
```

Five artifacts, with `reveal()` called by one module the whole time.

Real workbook unchanged: `validate` reports the same 12 blockers, `build` exits 2.

## The lens, a fifth time

> The dangerous failures are not where something is missing entirely. They are where the
> system has enough information to look complete, but one layer silently stops enforcing
> the promise made by the layer above it.

This round the promise was *"I never invent policy"*, made by a module that then proposed
rewriting a frozen routing decision. Every noun in that proposal had been checked. The verb
had not.

---

# Eighth audit — a finding that named a thing the data cannot show

Target commit `09c1f14`. Four blocking changes and two cleanups. Each was reproduced
against that commit before anything was edited.

## `HELD_DEMAND` measured served traffic and called it unserved

The reviewer's sentence is the whole argument: *a search-terms report contains searches
Google **served**; it cannot directly observe searches Google never served.* Held demand —
the thing the name promises — leaves no row in this file. There is nothing to count.

Reproduced first. Every row the finding fired on:

```
=== what does HELD_DEMAND currently fire on? ===
   coverage=NOT_IN_WORKBOOK      conv=1  -> HELD_DEMAND
   coverage=NOT_IN_WORKBOOK      conv=2  -> HELD_DEMAND
   coverage=NOT_IN_WORKBOOK      conv=6  -> HELD_DEMAND
```

Every one of them was **served**. `NOT_IN_WORKBOOK` means Google ran a keyword the
workbook does not contain — that is account drift, and `UNAPPROVED_KEYWORD` already says
so. The finding was reporting drift under a name that told the reader "we are losing
business we never bid for". Two different remedies, one label.

`HELD_DEMAND` is removed from `FindingType`. The two questions this dataset can actually
answer keep their own names:

* `EXPLICIT_KEYWORD_GAP` — served, converted, and the workbook has no keyword of its own
  for it. Bid for it deliberately, or decide not to.
* `UNAPPROVED_KEYWORD` — served by a keyword the workbook does not contain. Drift.

Genuinely unserved demand needs keyword-planner or impression-share data. Stage 1 does not
have that input, and building a proxy for it out of the rows we do have is how a dashboard
comes to report a quantity it cannot see. Recorded in spec §13.3 with the row struck
through, because the name is more attractive than the evidence and somebody will want it
back.

Third time this exact shape has appeared: the sixth audit caught me substituting
`HELD_DEMAND`'s meaning and proving the substitute with a green test. Renaming the concept
did not fix it. Deleting it did.

## `POLICY_SCOPE_REVIEW` generated an action for policy working correctly

Reproduced:

```
=== policy behaving exactly as approved ===
   POLICY_SCOPE_REVIEW: list=ROUTE_COMPETITORS approved_reach=('TST | Search | Neuro | Jaipur',)
                        served_in=TST | Search | Brand | Jaipur
   AMBER actions written for Gaurav:  AMBER | POLICY_SCOPE_REVIEW: 1 case(s) from run r
```

A negative list deliberately does not cover the Brand campaign. Traffic appeared in the
Brand campaign. The tool wrote an amber action asking somebody to review the decision that
had already been taken, on purpose, and frozen. Every week. Forever.

The reviewer: *that is how dashboards become wallpaper.* An operator who is asked to
re-approve a working decision fifty times stops reading the file, and the fifty-first row
is a real one.

The observation is now `INTENTIONAL_NON_REACH`, severity **INFO**, and its remedy line
starts `"None. Approved policy deliberately excludes this campaign..."`. It is shown so the
cost is visible, under a section headed **EXCLUDED BY DESIGN**. It writes **no** action.
The rule that replaced it:

> A weekly incident becomes an action when it **contradicts** the decision, not when it
> follows it.

`OBSERVED_DESPITE_NEGATIVE` — an approved negative that did not prevent a term — still
writes an action, because that one does contradict the decision.

## The declared date range, not the Day column, decides the window

Reproduced:

```
=== declared vs observed range ===
   declared: (2026-08-11, 2026-08-17)  observed: (2026-08-11, 2026-08-16)
   WD-003 raised: ['the export covers 2026-08-11 to 2026-08-16 (6 day(s)) per the Day colu…']
```

A correct 7-day export, warned about, because Sunday had no traffic. The Day column shows
**when activity happened**, which is not the same fact as **what window was selected**, and
a quiet last day is normal. Treating observed activity as the selected window makes the
warning fire on healthy exports, and a warning that fires on healthy exports gets ignored
when it fires on a broken one.

Now: the declared range in the preamble is the authority on the window. The Day column is a
consistency check against it, and a disagreement between the two is reported as its own
observation rather than as a short export. When neither is present the range is
unverifiable, which is still `WD-003` — that case was the point of the seventh audit and
has not been weakened.

After the fix: `WD-003: none — a correct 7-day export is no longer warned about`, and a
regression test holds it there.

## Spec, tasks and pipeline now say what the code does

The Stage-1 decision — *the Watchdog does not author negative policy* — was taken in the
seventh audit and implemented in the code, but three documents still described the old
behaviour. That gap is its own defect: the next reader trusts the spec.

* §13.5 purpose table now reads "negative-policy observations, not suggestions";
* a seventh non-goal: *author negative policy at all (Stage 1)*;
* `CODEX_TASKS.md` Phase 6 strikes `watchdog/suggest.py` through and marks it
  **Superseded — do not build this**;
* `run.py`'s pipeline step 6 is now `OBSERVE what approved negative policy did and did not
  prevent`.

## Two cleanups

The summary block still printed a line labelled `Held demand`, counting rows that no longer
had that finding. It reads `No explicit keyword N (the EXPLICIT_KEYWORD_GAP test)`, and a
`Coverage unknown` line was added beside it.

Total spend was understated whenever rows failed to parse: the report printed a confident
figure computed from readable rows only. It now prints
`Spend: X across readable rows — TOTAL UNKNOWN, N row(s) could not be read` when
`Export.spend_is_complete` is false. A number that is quietly partial is worse than an
admitted unknown, because it gets compared to last week's.

## The privacy claim was stronger than the code

Accepted, and corrected in the docstrings rather than argued with. The seventh audit's
guard is real, but the wording around it — *structural instead of lucky* — implied a proof
about every possible account-configuration string. There is no such proof: account
configuration is written by people and any of it could coincide with somebody's search.

The claim now reads, in `labels.py`, `analysis_csv.py`, `searchterm.py` and the privacy
test:

> Raw query text has one intentional output path. Known configuration-equality leak paths
> for negative text and keyword text are guarded.

A guarded path, not a theorem. A future output that prints some other piece of account
configuration verbatim would need the same guard, and stating it this way is what makes
that obvious to whoever writes it.

## Verified

Clean clone of `75c4972`, fresh installs, all outbound sockets blocked, on both supported
Pythons:

```
Python 3.10.20   ruff clean · format clean · mypy clean · 468 passed, 7 skipped in 17.50s
Python 3.11.15   ruff clean · format clean · mypy clean · 468 passed, 7 skipped in 16.62s
```

(The seven skips are the real-workbook tests. `input/` is git-ignored, so a clean clone has
no workbook to read — that is the intended behaviour, not a gap.)

Seven new regression tests, run against `09c1f14`, which is the point of them:

```
09c1f14  FAILED test_held_demand_is_gone_because_the_dataset_cannot_support_it
09c1f14  FAILED test_an_unapproved_keyword_is_drift_and_not_a_coverage_gap
09c1f14  FAILED test_an_intentional_exclusion_is_information_not_an_action
09c1f14  FAILED test_a_declared_seven_day_window_is_not_warned_about_for_a_quiet_last_day
09c1f14  FAILED test_rows_outside_the_declared_window_are_reported
09c1f14  FAILED test_spend_is_not_stated_as_a_total_when_rows_could_not_be_read
09c1f14  FAILED test_the_summary_no_longer_names_a_finding_that_does_not_exist
```

Real workbook unchanged: `validate` reports the same 12 blockers, `build` exits 2.

## The lens, a sixth time

> The dangerous failures are not where something is missing entirely. They are where the
> system has enough information to look complete, but one layer silently stops enforcing
> the promise made by the layer above it.

This round the layer was the **name**. `HELD_DEMAND` had a definition, a threshold, a
config key, a report section and passing tests — everything a finding is supposed to have
except a dataset that could produce it. The scaffolding was complete. The measurement was
not, and nothing in the stack was positioned to notice, because every layer was enforcing
the promise made by the label rather than checking whether the label was true.

---

# Ninth audit — the engine knew; its reports did not

Target commit `af99c91`. Four blocking changes and two cleanups, each reproduced first.

The reviewer's summary of the shape is exact: *the patch fixed the producer logic more
completely than the things that consume it.* Every defect below is a consumer that
reinterpreted a fact ingest had already settled.

## Three artifacts each answered "what week is this?" differently

The eighth audit taught ingest that the **declared** window and the **days that served** are
different facts. It did not tell the report, the dashboard or the manifest, and all three
reached for the activity range independently:

```
declared: (2026-08-11, 2026-08-17)  observed: (2026-08-11, 2026-08-16)
   report : Covering:   2026-08-11 to 2026-08-16
   dash   : 2026-08-11 to 2026-08-16
   manifest: {'first': '2026-08-11', 'last': '2026-08-16'}
```

So `WD-003` correctly declined to warn about a 7-day export while every artifact that
export produced described a 6-day one. Worse for the common shape: an export with no `Day`
column but a perfectly good declared range passed validation while the header said
`Covering: UNKNOWN — the export has no day column`.

Fixed by making it a property rather than a convention. `Export.activity_range` (renamed
from `observed_dates`, whose name invited the mistake), `Export.declared_range`, and
`Export.selected_range` — the one every consumer must use — with `range_source` travelling
beside it so the claim carries its own strength. The manifest keeps all three, because
auditing a past run means seeing both what was selected and what had traffic in it.

## The same event was "approved policy" and "leakage" at once

`ROUTE_COMPETITORS` deliberately excludes Brand. A competitor term served in Brand produced,
on the same row, in the same file:

```
NEGATIVE POLICY  INTENTIONAL_NON_REACH   "None. Approved policy deliberately excludes…"
FINDINGS         BRAND_LEAK              "competitor-brand vocabulary served at all"
```

A reader cannot reconcile those, and the one that looks like a defect is the one they act
on. The eighth audit stopped it becoming a *task*; it did not stop it being reported as a
fault.

`BRAND_LEAK` now fires for competitor vocabulary only when an approved exclusion actually
**reaches** the incident campaign and the term served there anyway — the case that
contradicts the decision. Where the list deliberately does not reach, `INTENTIONAL_NON_REACH`
alone is the whole truth.

Two consequences worth recording, because both are places the fix could have gone wrong.

`observations.build()` keyed off `FindingType.BRAND_LEAK` existing, which made the
explanation a *consequence* of the thing it explains. Removing the false finding would have
silently removed the observation saying why the campaign was excluded — the one a reader
most needs. Observations are now derived from `Category.COMPETITOR` plus the negatives that
matched, with no reference to findings at all.

And `JUNK` had the same contradiction in a quieter form: "matches junk vocabulary already on
`X`" reads as an enforcement failure even when `X` deliberately does not cover the campaign.
Junk vocabulary is a claim about traffic quality rather than a claim of defect, so the
finding stands — but the wording now says which case it is. This one was not named in the
audit; leaving the same contradiction half-fixed in the adjacent branch was not defensible.

## The screenshot was still confident

The report was made honest about partial spend. The dashboard was not:

```
   card: spend = 5,771.25          (with 2 unreadable rows)
```

The prettier artifact was the more confidently wrong one, and it is the one that travels as
a picture. Both surfaces now render from `present.spend()`; the card reads
`readable-row spend` with `TOTAL UNKNOWN · 2 row(s) unreadable` beneath it.

## Governance told the next agent to rebuild what we removed

`AGENTS.md` instructs a coding agent to trust the spec and the task list. They said:

* spec non-goal #3: *"The Watchdog **suggests**. A human approves."* — the model Stage 1
  deliberately abandoned;
* `CODEX_TASKS.md` Phase 6: `- [ ] ingest/search_terms.py`, unticked, under a path never
  built, while `watchdog/ingest.py` sits there with hundreds of tests around it.

Four rounds of audit went into stopping the software inventing policy, and the instructions
left behind asked another agent to build a duplicate ingest module and reintroduce
suggestions. Both rewritten, the never-list renumbered, and a guardrail test now asserts the
abandoned clause is absent and that Phase 6 carries no open box.

## Two cleanups

`No explicit keyword N (the EXPLICIT_KEYWORD_GAP test)` counted every query with no exact
keyword — 8 — while the finding fired 1 time, because the finding also requires coverage and
a conversion. Two denominators, one label. Now rendered as two lines, the second computed
from the findings themselves.

The Watchdog manifest walked with `iterdir()`, so `writeback/01_ACTIONS_append.csv` and
`writeback/HOW_TO_PASTE.txt` — the only outputs a human is told to paste into the operating
system — were the only ones outside the audit fingerprint. Both manifests now use one shared
`hash_tree()` keyed by relative path. The build manifest is flat today; it was changed too
so the two cannot drift apart the moment either grows a subdirectory.

## The principle this patch is named after

The reviewer's phrasing, adopted:

> **Derive truth once. Render it everywhere.**

`watchdog/present.py` exists for that. The window and the spend figure are decided in one
place, and the report, the dashboard and the manifest choose a shape for the answer without
being allowed to recompute it. Every defect in this round was a surface re-deriving
something ingest already knew.

## Verified

Clean clone of `7c79eb8`, fresh installs, all outbound sockets blocked, on both supported
Pythons:

```
Python 3.10.20   ruff clean · format clean · mypy clean · 477 passed, 7 skipped in 16.89s
Python 3.11.15   ruff clean · format clean · mypy clean · 477 passed, 7 skipped in 15.80s
```

Nine new regression tests, run against `af99c91`:

```
af99c91  FAILED test_every_output_surface_reports_the_same_selected_window
af99c91  FAILED test_a_declared_range_with_no_day_column_is_not_reported_as_unknown
af99c91  FAILED test_the_dashboard_does_not_present_a_partial_subtotal_as_spend
af99c91  FAILED test_the_manifest_hashes_nested_writeback_artifacts
af99c91  FAILED test_the_summary_separates_no_exact_keyword_from_the_gap_finding
af99c91  FAILED test_an_intentional_exclusion_is_not_also_reported_as_a_leak
af99c91  FAILED test_the_observation_does_not_depend_on_the_finding_it_explains
af99c91  FAILED test_the_normative_documents_agree_with_the_no_authoring_decision
af99c91  passed test_an_exclusion_that_does_reach_the_campaign_is_still_a_leak
```

The ninth passes on both commits **on purpose**: it holds the direction the fix must not
disable. A reach-aware `BRAND_LEAK` that stopped firing everywhere would satisfy the other
eight, and this is the test that would catch it.

Real workbook unchanged: `validate` reports the same 12 blockers, `build` exits 2.

## The lens, a seventh time

> The dangerous failures are not where something is missing entirely. They are where the
> system has enough information to look complete, but one layer silently stops enforcing
> the promise made by the layer above it.

This round it was the last layer — rendering — and the promise was *"this is what we
analysed"*. Ingest knew the window, knew the spend was partial, knew the exclusion was
intentional. Three surfaces each restated those facts in their own words, and the artifact
with the nicest typography was the one that got them wrong.

---

# Tenth audit — a fallback that promoted itself into evidence

Target commit `3d233e7`. Two blocking changes and two cleanups, each reproduced first.

The reviewer named the shared shape before naming the defects, and it is the right frame:

> **A weaker layer is still being allowed to override the stronger contract above it.**

Both blockers are the same sentence written twice. The code said activity is not the
selected period, then let activity verify the selected period. The spec said the Watchdog
does not author negative policy, then required negative suggestions in its acceptance tests.

## The window check cleared itself on the wrong evidence

The ninth audit made the declared range the authority for *describing* a run. It did not
stop the activity span from *verifying* one. Reproduced:

```
=== no declared range, exactly 7 active days ===
   WD-003 raised: NONE
   selected_range: (2026-08-11, 2026-08-17)  source: activity
```

That is the original defect in the one shape nobody writes a test for, because the numbers
look right. A `July 19 – August 17` selection whose traffic all fell in the last week
produces exactly seven active days. The Day column is tidy. The check passes. Nobody
learns that a month of data is being read as a week.

The rule now:

> A fallback may describe uncertainty. It may not promote itself into evidence.

So the window check runs **only** against a declared range. With none present the finding is
`WD-003 SELECTED WINDOW UNVERIFIED`, however neat the Day column looks, and the message says
explicitly that seven active days is what the rows show rather than what was selected. The
activity span is still printed as context and still drives the staleness check — "your most
recent row is three weeks old" is an observation the rows genuinely support.

Both directions are held by tests. A declared seven-day range with a quiet last day still
passes silently; that separation is the entire point and tightening one half must not undo
the other.

## The specification was still commissioning the removed architecture

Four audits went into stopping the software authoring negative policy. Meanwhile:

```
Non-goal:            DO NOT AUTHOR NEGATIVE POLICY
§13 intro:           Output: analysis, suggested negatives, …
Acceptance test 19:  Suggestions produced, each with evidence
Acceptance test 20:  Emitted as ROUTING_CONFLICT, never as a suggestion
Phase 6:             COMPLETE
```

Not history inside a `<details>` block — live acceptance criteria, which are the definition
of "done". The ninth audit's guardrail did not catch them: it checked one exact abandoned
sentence and whether Phase 6 had an open checkbox.

§13's output line now reads *negative-policy observations*. Tests 19 and 20 are replaced
with the current contracts — `INTENTIONAL_NON_REACH` with no action and no `BRAND_LEAK` for
the same event; no new negative text, no list-reach proposal, no `03_KEYWORDS_append.csv`,
and `OBSERVED_DESPITE_NEGATIVE` where the reach does cover the campaign. §13.1's range
clause is amended to the declared-range rule above.

### The guardrail had to get stronger than a word list

The first attempt scanned live prose for the abandoned vocabulary and required any line
using it to also be describing its removal. That is a real rule rather than an exact-phrase
match, and it is still not enough. Tested against a paraphrase:

```
| 20b | Watchdog offers candidate exclusions | Each candidate is emitted with its evidence |
   → PASSED
```

The whole architecture, reintroduced, without one banned word. So the Watchdog's acceptance
criteria are now **pinned**: rows 18–22 are held verbatim in the test, and any edit fails
with a message saying the change belongs in the same commit. Re-tested against the same
paraphrase:

```
   → FAILED  Watchdog acceptance criteria changed. If that is intended, update
             _WATCHDOG_ACCEPTANCE in this test in the same commit
```

A word list cannot stop a paraphrase. Pinning the contract can, because it stops caring what
the words are.

## Two cleanups

`No exact keyword N (queries served by a broader keyword)` — the noun was factual and the
parenthesis smuggled in a claim. That count includes rows whose triggering keyword is
`NOT_IN_WORKBOOK` (unapproved) or `UNKNOWN` (the export named none), for which nothing about
the serving keyword is established. Now `Workbook has no exact keyword N`, stated flatly.
Same disease as every other defect in this dig, in its smallest form.

`WatchdogResult.files` built `final / item.name`, which flattened
`writeback/01_ACTIONS_append.csv` to `01_ACTIONS_append.csv`. Reproduced:

```
   01_ACTIONS_append.csv exists: False
   HOW_TO_PASTE.txt      exists: False
```

The files were on disk and in the manifest; the result object pointed at paths that do not
exist, for exactly the two artifacts a person is told to paste. Nothing consumes that
property today, which is why it was worth fixing before Phase 7 starts consuming it — a
knowingly false artifact list is a bug waiting for its first caller.

## Verified

Clean clone of `f49fc16`, fresh installs, all outbound sockets blocked, on both supported
Pythons:

```
Python 3.10.20   ruff clean · format clean · mypy clean · 480 passed, 7 skipped in 17.26s
Python 3.11.15   ruff clean · format clean · mypy clean · 480 passed, 7 skipped in 16.58s
```

Five new regression tests, run against `3d233e7`:

```
3d233e7  FAILED test_a_seven_day_activity_span_does_not_verify_the_selected_window
3d233e7  FAILED test_the_normative_documents_agree_with_the_no_authoring_decision
3d233e7  FAILED test_the_summary_separates_no_exact_keyword_from_the_gap_finding
3d233e7  FAILED test_the_result_points_at_the_files_it_says_it_wrote
3d233e7  passed test_a_declared_window_is_still_the_thing_that_gets_verified
```

The fifth passes on both commits **on purpose**. Making the window check declared-only could
have been "fixed" by warning about every export, which would satisfy the other four; this is
the test that holds the quiet-last-day case silent.

Real workbook unchanged: `validate` reports the same 12 blockers, `build` exits 2.

## The lens, an eighth time

> The dangerous failures are not where something is missing entirely. They are where the
> system has enough information to look complete, but one layer silently stops enforcing
> the promise made by the layer above it.

This round both instances were **fallbacks**. A fallback is the politest form of this
failure: it exists precisely for the case where the strong evidence is missing, so it is
always sitting next to the check it is about to satisfy. The activity range was designed as
"what we can say when nothing better is available" and quietly became "good enough to pass".
The word "suggests" survived in the acceptance table because the table was the fallback
place nobody re-read.

---

# Eleventh audit — the report implied Google gave it everything

Target commit `58e96a6`. Four blocking changes and one cleanup, each reproduced first.

The reviewer's closing sentence is the finding underneath all the others:

> The Watchdog is now very good at preserving the data Google gives it. It still needs to
> stop implying that Google gave it all the data.

## Google withholds queries, and every percentage was quoted against the wrong denominator

Google omits low-volume search terms from the search-terms report for privacy. Those
searches happened and cost money; they are simply not listed. So the sum of the rows in an
export is **reported search-term spend** — a real quantity, and a smaller one than the
campaign's budget.

The code had become meticulous about one unreadable CSV row (`spend_is_complete`, the
concentration denominator withholding) while missing that Google may intentionally not give
it all the rows. `Spend: ₹X` was printed as a fact, and concentration said
`34.0% of Neuro campaign spend` when the honest claim is 34% of what the report disclosed.
On a campaign where visible queries are ₹6,000 of ₹10,000, a query at a true 30% prints as
50%. Concentration is exactly the metric where that changes a decision.

Nothing about the arithmetic was wrong. The label was.

* The figure is named `reported search-term spend` everywhere — report header, dashboard
  card, and the shared `present.SPEND_LABEL` so the two cannot drift.
* Concentration reads `34.0% of reported search-term spend in TST | Search | Neuro | Jaipur`.
* A new `WHAT THIS FILE DOES NOT CONTAIN` block states the omission on every run, and
  `WD-007` (INFO) carries it into `findings.json` and the manifest.
* `Export.spend_is_complete` (did every row parse — our problem, fixable) and
  `Export.demand_is_fully_visible` (did Google show us everything — never) are separate
  properties. The second returns a constant `False`, because the honest answer does not
  vary with the file.

### The aggregate rows were being read as patient searches

Chasing this turned up something worse than a label. A downloaded Google export ends with
summary rows, and nothing in the reader told them apart from queries. Reproduced:

```
   rows parsed: 3
      apex hospital jaipur          450.00
      Total: Other search terms    4000.00
      Total: Search terms          4450.00
   total_cost: 8900.00   spend_is_complete: True
```

A file whose real disclosed spend is ₹450 reported ₹8,900 — Google's own arithmetic counted
as traffic, twice, with two column footers minted as query IDs and run through the taxonomy.
And `spend_is_complete` said `True` the whole time.

Summary rows are now diverted before a `SearchTerm` is ever constructed. `Total: Other
search terms` is kept as `Export.undisclosed_cost` rather than dropped, because it is the
only statement the file ever makes about the demand it is hiding. Its absence is the normal
case and means **not stated**, never zero — the visibility note fires either way. The match
is deliberately narrow (`Total:` prefix, or exactly `other search terms`): mistaking a real
query for a footer would silently delete traffic, which is worse than the bug being fixed.

## "Seven days" is not "the previous seven days"

The tenth audit stopped the Day column verifying the window. The check it left behind was
span-is-7 plus end-date-not-too-old, and that is not the procedure. Reproduced on the
project's own test date:

```
=== 7-day range from the wrong week ===
   run date 2026-08-18, declared 2026-08-08 to 2026-08-14
   WD-003: NONE
```

Seven consecutive days. Four days old. Entirely the wrong week — and nothing about it looks
unusual, which is why it would be acted on. Google's own *Last 7 days* ends yesterday, so
the invariant is an exact pair:

```
expected_last  = today - 1 day
expected_first = today - lookback_days
```

A mismatch now prints both ranges. The staleness check runs only where no declared range
exists; with one, the exact-window finding already says which week this is and which week it
should be, and two warnings about one problem teach a reader to skim.

`today` now comes from `account.timezone` (`Asia/Kolkata`) rather than UTC. A Google Ads day
begins in the account's timezone, and comparing against a UTC date is wrong for several
hours every day — enough to call a correct Friday export stale. If the zone cannot be
loaded the run says so in a WARNING instead of silently comparing in UTC.

## §13.7 was still commissioning the removed architecture, in sheets that do not exist

```
CODE:        never create keyword writeback
§13.5:       never create keyword writeback
Acceptance:  never create keyword writeback
§13.7:       "appendable blocks for 06 NEGATIVE KEYWORDS / 03 KEYWORDS
              and rows for 01 ACTIONS / 09 SEARCH TERM MONITOR"
```

Two faults in one sentence. The keyword blocks are the architecture four audits removed, and
`06 NEGATIVE KEYWORDS` and `09 SEARCH TERM MONITOR` are ghosts of the eleven-area design —
**the workbook has four sheets** (decision C1). A spec naming sheets that do not exist sends
the next implementer looking for them.

§13.7 now describes exactly what the code emits: `writeback/01_ACTIONS_append.csv` and
`writeback/HOW_TO_PASTE.txt`, and no keyword file. The governance guardrail was extended to
the writeback contract specifically — the pinned acceptance rows did not cover it. The ghost
check reads the contract *before* its amendment note, because the note names the ghosts in
order to bury them and wraps across lines: the paragraph is the unit of meaning, not the
line, and a line-by-line rule got that wrong on the first attempt.

## The false action was deleted from the CSV and rewritten in the prose

`INTENTIONAL_NON_REACH` correctly says "nothing to do" and writes no action row. Then the
final instructions said:

> `negative_observations.csv` lists approved negatives that did not prevent a term. Check
> the export's date range first, then whether the list is actually applied in the account.

That file holds **both** observation kinds. So for the Brand competitor case the report said
"nothing to do" in one section and "check whether `ROUTE_COMPETITORS` is applied" in another
— and a hurried operator applies it, reversing a frozen decision. Exactly the outcome the
eighth audit removed, restored in prose.

The instructions now split by observation kind: intentional non-reach is information only,
with *do not investigate, do not change which campaigns the list applies to*; observed
despite negative gets the investigation sequence.

## Cleanup: "Every row says REVIEW" was false in the shipped fixture

Junk vocabulary already on an approved negative list is `FLAGGED` without consulting a
threshold — correctly, since it is a deterministic hit on a decision a person already took.
The standard fixture contains `apex hospital job` precisely to exercise that branch, so an
ordinary run printed the claim and then contradicted it a page later. Both surfaces now say
*threshold-based findings say REVIEW*, and `FLAGGED`'s docstring names its second source.

## Verified

Clean clone of `1e458bf`, fresh installs, all outbound sockets blocked, on both supported
Pythons:

```
Python 3.10.20   ruff clean · format clean · mypy clean · 488 passed, 7 skipped in 18.41s
Python 3.11.15   ruff clean · format clean · mypy clean · 488 passed, 7 skipped in 17.09s
```

Nine new regression tests, all run against `58e96a6`:

```
58e96a6  FAILED test_googles_own_total_rows_are_never_read_as_searches
58e96a6  FAILED test_the_withheld_query_total_is_kept_as_evidence_not_dropped
58e96a6  FAILED test_an_export_with_no_aggregate_row_still_admits_the_gap
58e96a6  FAILED test_no_output_calls_the_disclosed_total_campaign_spend
58e96a6  FAILED test_a_seven_day_range_from_the_wrong_week_is_warned_about
58e96a6  FAILED test_the_normative_documents_agree_with_the_no_authoring_decision
58e96a6  FAILED test_the_operator_is_not_told_to_investigate_an_intentional_exclusion
58e96a6  FAILED test_the_report_does_not_claim_every_row_says_review
58e96a6  FAILED test_the_dashboard_does_not_present_a_partial_subtotal_as_spend
```

`test_the_correct_previous_seven_days_still_passes` passes on both commits, deliberately:
tightening the window check could have been "satisfied" by warning about every export, and
that is the test which would catch it.

The reviewer's cheapest disconfirming test — comparing a real seven-day download's parsed
rows against Google's own totals — is **not** run here, because this repository holds no
real export and `input/` is git-ignored. It is worth doing once against a live download
before the first real Friday, and it is named in `CODEX_TASKS.md` rather than quietly
skipped.

Real workbook unchanged: `validate` reports the same 12 blockers, `build` exits 2.

## The lens, a ninth time

> The dangerous failures are not where something is missing entirely. They are where the
> system has enough information to look complete, but one layer silently stops enforcing
> the promise made by the layer above it.

This round the layer was **the input**, and the promise was one nobody had written down:
*this file contains the searches*. Every layer above it was scrupulous — the raw-term
boundary, the parse-error withholding, the campaign-level denominators, the naming of
uncertainty everywhere else. All of that care was spent on a dataset that arrives with a
hole in it by design, and the report's vocabulary quietly asserted otherwise.

The pattern is worth naming for Phase 7, which reads a different Google export: **ask what
the source does not contain before trusting what it does.**
