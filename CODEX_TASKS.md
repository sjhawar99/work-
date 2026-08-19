# CODEX_TASKS.md — sequential implementation plan

One phase per pull request. A phase is done when its code **and** its tests are merged
and green. Acceptance-test numbers refer to §19.2 of
[`docs/CODEX_BUILD_SPEC.md`](docs/CODEX_BUILD_SPEC.md).

Read [`DECISIONS.md`](DECISIONS.md) before Phase 0. Seven previously-open questions are
answered there; none of them is yours to re-decide.

Do not start a phase before the phase above it is merged. Do not bundle phases.

---

## Phase 0 — Skeleton ✅ COMPLETE

**Goal:** a repo that runs, lints and tests, with nothing in it yet.

- [x] `pyproject.toml`: package `apex_ads` under `src/`, deps from spec §6, console
      script `apex = apex_ads.cli:main`, ruff + mypy + pytest config.
- [x] Package tree from spec §5 with `__init__.py` in every module directory.
- [x] `src/apex_ads/util/`: `currency.py`, `text.py`, `hashing.py`, `logging.py`,
      `redact.py` — small, pure, fully unit-tested.
- [x] `src/apex_ads/cli.py` with `argparse` subcommands `build`, `validate`, `watchdog`,
      `drift`, `version`. Only `version` does anything; the rest exit 5 with
      "not implemented".
- [x] Exit-code constants in one module (`apex_ads/exit_codes.py`) per spec §15.1 —
      including `6` for a `DRAFT` build.
- [x] `config/rules.yaml`, `config/workbook_schema.yaml`, `config/editor_schema.yaml`
      loaded and validated by a `Config` pydantic model. Missing key → exit 5 naming it.
- [x] CI workflow: `ruff format --check`, `ruff check`, `mypy src/apex_ads`, `pytest -q`.

**Done when:** `apex version` prints tool version, git commit and config hashes; CI green.

✅ Done. 102 tests, ruff clean, mypy strict clean. `Config` rejects unknown keys and
refuses to load a config that would permit Broad positives. `argparse` usage errors are
remapped from exit 2 to exit 5 so the exit-code contract holds.

---

## PRE-PHASE — Workbook Schema Reconnaissance

**Goal:** know what the workbook actually contains before writing a single line of parser.

**Do not write parsing logic in this phase.** ✅ This phase is COMPLETE — the real
workbook was inspected and `config/workbook_schema.yaml` (version 2) is written from it,
not inferred. What was found, and why it matters:

- `02 BUILD` has six real sections with banner rows like
  `CAMPAIGN SETTINGS — ONE ROW PER CAMPAIGN` and
  `LANDING PAGE BUILD BRIEFS — NINE PAGES, NO INTERPRETATION`. There is no generic
  `ACCOUNT` / `ADS` / `CONVERSION` section, as the first draft assumed.
- `RSA 1` is **wide**: one row per ad group, 12 headline columns and 4 description
  columns. It is not an asset-type/asset-text long table. Unpivot on parse.
- `03 KEYWORDS` is **one registry table**, positives and negatives separated by a `Type`
  column — not two independently headed sections.
- `Scope` is a human sentence, not an enum: `Account`, `Ad group`,
  `Campaign: MLN | Search | Generic | Jaipur`,
  `Shared list → Neuro, Generic, Ortho, Nephro`. It needs a real parser, and the
  shared-list form names campaigns by **short name**.
- `01 ACTIONS` has **two** tables with different column sets (blocking, running).
- Landing pages are stored as **paths** (`/google/apex-jaipur`), not absolute URLs.
  Join with `landing_pages.base_url` before checking them.
- `COPY / PASTE VALUE` is derived (`"text"` / `[text]`); regenerate and cross-check it.

Any future change to the workbook's shape re-opens this phase before the parser changes.

---

## Phase 1B — Ingest and models ✅ COMPLETE

**Goal:** the workbook becomes typed Python objects, robustly.

- [x] All models from spec §7, `pydantic` v2, `Provenance` on every record.
- [x] `ingest/workbook.py`: header-driven section and column resolution driven by
      `config/workbook_schema.yaml` (spec §4.3). No row indices anywhere.
- [x] Normalised column matching; missing required column → BLOCKER naming sheet +
      column; unknown columns → single INFO.
- [x] Total, explicit type coercion: currency, percent, bool, list-of-strings. Failures
      are BLOCKERs naming the cell, never `NaN`.
- [x] Workbook opened read-only; SHA-256 recorded into `WorkbookBundle`.
- [x] Parse **only** the four sheets `01 ACTIONS`, `02 BUILD`, `03 KEYWORDS`, `04 DAILY`
      (Decision A1). An unexpected extra sheet is an INFO, never a search target.
- [x] Parse `Scope` into `(level, campaign|null, ad_group|null, applied_campaigns[])`
      per `workbook_schema.yaml → keyword_registry.scope_parsing`. Preserve it end to end
      (Decision A4); never flatten it.
- [x] Unpivot the wide `RSA 1` block into headline and description lists.
- [x] Split `01 ACTIONS` into its two tables; they have different columns.
- [x] Treat landing-page cells as paths and join `landing_pages.base_url`.
- [x] Regenerate `COPY / PASTE VALUE` and cross-check against the workbook (`KW-009`).
- [x] Parse the three cross-check panels (manager view, pre-flight, keyword counts) but
      **recompute every figure**; report disagreement rather than trusting the cell.
- [x] Fixtures `wb_clean.xlsx` and `wb_shifted_rows.xlsx` (built by a script in
      `tests/fixtures/build_fixtures.py` so they are reproducible, not opaque binaries).
- [x] **Reconcile the column names against the real workbook.** Sheet names are final;
      column names in `config/workbook_schema.yaml` are inferred and must be corrected
      against `input/workbook.xlsx` (spec §21 open item 1).

**Done when:** test 9 passes — shifted rows produce identical parse results.

✅ Done. 142 tests. The shifted-row fixture and the clean fixture produce identical
typed objects once row numbers are excluded. Verified against the real export: 5
campaigns, 9 ad groups, 9 landing pages, 12 assets, 10 measurement items, 9 RSAs,
112 keywords, 226 negatives, 280 daily rows, ₹62,000 declared total.

---

## Phase 2 — Validator framework, budget and structure rules ✅ COMPLETE

- [x] `validate/base.py` (protocol, `Finding`, `Severity`), `validate/registry.py`,
      `validate/runner.py` that runs **every** validator and collects all findings.
- [x] Rules `BUD-001..004`, `STR-001..007`, `ACT-001..003` (spec §9.3, §9.9).
      `BUD-001`, `STR-001`, `STR-002` enforce the Stage-1 invariants exactly (Decision A2).
- [x] Waiver plumbing with an **empty** waivable-rule allowlist (spec §9.9). Waivers
      record human acceptance; they never suppress a rule.
- [x] `report/preflight.py` producing the exact format in spec §12, plus `findings.json`.
- [x] `apex validate` wired end-to-end: validation only, never writes CSVs.

**Done when:** tests 7, 8, 9, 11 pass.

✅ Done. 181 tests. 18 validators: BUD-001..005, STR-001..008, STR-LP-001,
ACT-001..003, XCHK-001. `apex validate` writes PRE_FLIGHT_REPORT.txt and
findings.json and never writes CSVs. Against the real workbook: 12 BLOCKERs (all
ACT-001 open RED items, matching the workbook's own panel figure of 12), 10 WARNINGs,
and every panel figure agreeing with the recomputed value.

---

## Phase 3 — Keyword and negative rules ✅ COMPLETE

- [x] `KW-001..008` (spec §9.4), including `KW-008` `LEGACY_MATCH_TYPE_NORMALIZED`.
      The `Modified Broad → Phrase` map is a module constant. `Broad` still blocks.
- [x] `NEG-001..007` with the collision algorithm implemented **exactly** as spec §9.5:
      scope overlap × match semantics, on normalised tokens, no close-variant expansion.
- [x] Shared-list resolution: expand each list's `applies_to` campaigns **before**
      checking overlap (Decision A4). A list not applied to a campaign cannot collide
      with that campaign's keywords.
- [x] `NEG-006`: a declared shared list applied to no campaign fails the build.
- [x] `tests/unit/test_negative_collisions.py`: at least one case per match type per
      level, plus applied/not-applied shared-list cases and the different-campaign case.
- [x] `NEG-008`: assert the workbook's shared-list `Scope` agrees with
      `rules.yaml → shared_lists.*.applies_to`. Both sources are authoritative; a
      disagreement is a BLOCKER naming both, never a silent preference.

**Done when:** tests 3, 4, 5, 6, 26, 27, 28, 29, 30, 39, 43 pass.

✅ Done. 217 tests, 36 validators. Collision engine matches per Google's negative
semantics on normalised tokens with no close-variant expansion, and resolves scope
before matching. NEG-008 reconciles all three routing sources; NEG-009 blocks an
unmapped short campaign name rather than silently narrowing scope. Against the real
workbook: **zero collisions** across 112 keywords x 226 negatives, independently
confirming the workbook's own claim.

---

## Phase 4 — Ads, landing pages, tracking, settings ✅ COMPLETE

- [x] `AD-001..012`, `LP-001..004`, `TRK-001..005`, `SET-001..004` (spec §9.6–§9.8).
- [x] Call-asset resolution, most-specific-wins: ad group → campaign → account
      (Decision A5). Implemented for real in the second Phase-5 audit — the earlier
      resolver only ever read the campaign row and `resolution_order` was never consulted,
      while this file claimed acceptance test 35 passed. That test now exists. The number and schedule come from the **workbook**
      (`02 BUILD` campaign columns), not from config. `AD-006` requires every ad group to
      *resolve* to an asset. `AD-012` fires **only for a READY build**, so development
      and fixture builds proceed with `[REQUIRED BEFORE LAUNCH]` in place.
- [x] `ingest/urlcheck.py` implementing the twelve-step sequence in spec §9.6 exactly:
      https-only, allowed domain, GET, timeout, follow redirects, depth cap, final 200,
      final domain re-checked, GoogleAdsBot retry, latency and final URL recorded.
- [x] Three result states `PASS` / `BLOCKER` / `UNKNOWN`. `UNKNOWN` never counts as
      `PASS` and never yields a `READY` build (Decision A6).
- [x] Per-URL results table in the pre-flight report.
- [x] URL checking is mocked in tests; no test may hit the network.

**Done when:** tests 10, 12, 13, 31, 32, 33, 34, 35, 37, 38, 42 pass.

✅ Done. 257 tests, 62 validators. URL checking runs the twelve-step sequence with the
fetcher injected, so every state is tested without touching the network. `apex validate`
exits 6 when destinations went unverified and there are no blockers. AD-012 is the first
`ready_only` rule: a warning when validating, a blocker when building.

---

## Phase 5 — Transform, Editor export, manifest ✅ COMPLETE

- [x] `compile_/transform.py`: normalisation, dedupe, forced `PAUSED`, derived daily
      budgets, negative expansion, deterministic sort (spec §10.2).
- [x] `compile_/editor_export.py`: schema-driven writer per `config/editor_schema.yaml`,
      `utf-8-sig`, `\r\n`, minimal quoting; `UnmappedFieldError` on any unmapped field.
- [x] **Four** negative artifacts — account / shared list / campaign / ad group. Never
      one flat file, never a shared list expanded across its campaigns. If Editor cannot
      import shared-list creation, route it to `MANUAL_STEPS.md` instead.
- [x] Second, independent assertion that every emitted campaign row is `Paused`.
- [x] `MANUAL_STEPS.md` generator including the enumerated unmapped fields and the
      standing post-import procedure (spec §11.4–§11.5).
- [x] Three build outcomes per spec §10.5: `READY` (exit 0), `DRAFT` (exit 6, written to
      `<run_id>.DRAFT/` with `DO_NOT_IMPORT.txt`, `latest` untouched), `FAILED` (exit 2).
- [x] Staged writes: `<run_id>.partial/` renamed on success; removed on failure.
- [x] `manifest.json` per spec §10.6; `output/build/latest` pointer.
- [x] `apex build` wired end-to-end.
- [ ] **Verify Editor column headers against a real Editor export** (spec §21 item 5).
      ⚠️ STILL OPEN — no Editor export has been supplied. `config/editor_schema.yaml`
      ships `verified: false`, and while it does **no build can be READY**: the best
      possible outcome is a quarantined DRAFT, exit 6. Needs one Editor export from a
      human, then reconcile every header and record the provenance in `verified_against`.
- [x] `editor_schema.verified=false` withholds READY (blocking correction 1).
- [x] Every compiled record type has a declared destination; `EXP-002` blocks otherwise,
      and RSAs and supporting assets are enumerated in full in `MANUAL_STEPS.md`
      (blocking correction 2).

**Done when:** tests 1, 2, 14, 15, 16, 17, 40 pass.

✅ Done. 274 tests. `apex build` produces READY (exit 0), DRAFT (exit 6, quarantined in
`<run_id>.DRAFT/` with DO_NOT_IMPORT.txt, `latest` untouched) or FAILED (exit 2, report
only). Seven Editor files, four of them negatives, never flattened. PAUSED is asserted
in the transform and again at the writer. An unclassified workbook field blocks the
build as `EXP-001 UNMAPPED SOURCE FIELD`.

---

## Phase 6 — Search-Term Watchdog

- [ ] `ingest/search_terms.py`: reads a file **or** a directory (default
      `input/search_terms/`, newest CSV wins, filename echoed — never picked silently),
      alias-driven column resolution, `parse_errors.csv`, fail-closed on a missing
      required column, WARNING when the date range is not the previous 7 days.
- [x] `watchdog/taxonomy.py`: deterministic taxonomy classifier with documented
      precedence; unresolved terms labelled `CLASSIFIER_UNRESOLVED`.
- [x] `watchdog/routing.py`: expected owner vs actual owner, with money at stake.
      Coverage is read from the export's triggering keyword — Google's own answer — and is
      location-aware (`APPROVED_HERE` vs `APPROVED_ELSEWHERE`). There is deliberately no
      offline positive matcher.
- [x] `watchdog/findings.py`: `JUNK`, `CONCENTRATION`, `BRAND_LEAK`, `SPECIALTY_LEAK`,
      `EXPLICIT_KEYWORD_GAP`, `UNAPPROVED_KEYWORD`, `COVERAGE_UNKNOWN`,
      `CLASSIFIER_UNRESOLVED`. Every `watchdog.thresholds` value is `null` in Stage 1 —
      emit rank-and-review findings with the observed figure and no verdict. **Never
      invent a default for a null threshold.**
      **`HELD_DEMAND` is deliberately absent.** A search-terms export contains only demand
      that served, so "converted despite nothing covering it" is not a claim this dataset
      can support. See `findings.py`.
- [x] ~~`watchdog/suggest.py`: narrowest text, lowest level, phrase-over-broad, and the
      §9.5 collision check.~~ **Superseded — do not build this.** Stage 1 does not author
      negative policy (§13.5, amended). `watchdog/observations.py` replaces it: no novel
      negative text, no list-reach proposal, actions-only writeback. A future agent
      reading this line should treat the strikethrough as normative, not as a to-do.
- [x] Outputs per spec §13.6; optional `dashboard.html` (self-contained, no CDN).
- [x] `--propose-writeback` emitting new files only, never touching the workbook, and
      **no keyword block** — actions only.

**Done when:** tests 18–22, 36, 41 and 44 pass, including the workbook-hash-unchanged test.

---

## Phase 7 — Account Drift Checker

- [ ] `drift/live_export.py`: parse a Google Ads Editor account export.
- [ ] `drift/compare.py`: entity-keyed diff across the classes in spec §14.1.
- [ ] `report/drift.py` in the format of spec §14.2; exit 4 on CRITICAL drift.
- [ ] Never propose an automatic revert; never edit the workbook to match reality.

**Done when:** test 23 passes.

---

## Standing tasks (every phase)

- [ ] Guardrail tests 24 and 25 stay green: no bypass flags, no API client.
- [ ] No decision in `DECISIONS.md` gets re-litigated in code. If one looks wrong, say so
      in the PR and stop.
- [ ] `ruff format`, `ruff check`, `mypy src/apex_ads`, `pytest -q` all clean.
- [ ] New thresholds go to `config/`, never into `.py`.
- [ ] Anything the spec did not anticipate goes into spec §21 with a question, not a
      guess.
