# CODEX_TASKS.md — sequential implementation plan

One phase per pull request. A phase is done when its code **and** its tests are merged
and green. Acceptance-test numbers refer to §19.2 of
[`docs/CODEX_BUILD_SPEC.md`](docs/CODEX_BUILD_SPEC.md).

Read [`DECISIONS.md`](DECISIONS.md) before Phase 0. Seven previously-open questions are
answered there; none of them is yours to re-decide.

Do not start a phase before the phase above it is merged. Do not bundle phases.

---

## Phase 0 — Skeleton

**Goal:** a repo that runs, lints and tests, with nothing in it yet.

- [ ] `pyproject.toml`: package `apex_ads` under `src/`, deps from spec §6, console
      script `apex = apex_ads.cli:main`, ruff + mypy + pytest config.
- [ ] Package tree from spec §5 with `__init__.py` in every module directory.
- [ ] `src/apex_ads/util/`: `currency.py`, `text.py`, `hashing.py`, `logging.py`,
      `redact.py` — small, pure, fully unit-tested.
- [ ] `src/apex_ads/cli.py` with `argparse` subcommands `build`, `validate`, `watchdog`,
      `drift`, `version`. Only `version` does anything; the rest exit 5 with
      "not implemented".
- [ ] Exit-code constants in one module (`apex_ads/exit_codes.py`) per spec §15.1 —
      including `6` for a `DRAFT` build.
- [ ] `config/rules.yaml`, `config/workbook_schema.yaml`, `config/editor_schema.yaml`
      loaded and validated by a `Config` pydantic model. Missing key → exit 5 naming it.
- [ ] CI workflow: `ruff format --check`, `ruff check`, `mypy src/apex_ads`, `pytest -q`.

**Done when:** `apex version` prints tool version, git commit and config hashes; CI green.

---

## Phase 1 — Ingest and models

**Goal:** the workbook becomes typed Python objects, robustly.

- [ ] All models from spec §7, `pydantic` v2, `Provenance` on every record.
- [ ] `ingest/workbook.py`: header-driven section and column resolution driven by
      `config/workbook_schema.yaml` (spec §4.3). No row indices anywhere.
- [ ] Normalised column matching; missing required column → BLOCKER naming sheet +
      column; unknown columns → single INFO.
- [ ] Total, explicit type coercion: currency, percent, bool, list-of-strings. Failures
      are BLOCKERs naming the cell, never `NaN`.
- [ ] Workbook opened read-only; SHA-256 recorded into `WorkbookBundle`.
- [ ] Parse **only** the four sheets `01 ACTIONS`, `02 BUILD`, `03 KEYWORDS`, `04 DAILY`
      (Decision A1). An unexpected extra sheet is an INFO, never a search target.
- [ ] Preserve the negatives `Scope` column verbatim through parsing (Decision A4).
- [ ] Fixtures `wb_clean.xlsx` and `wb_shifted_rows.xlsx` (built by a script in
      `tests/fixtures/build_fixtures.py` so they are reproducible, not opaque binaries).
- [ ] **Reconcile the column names against the real workbook.** Sheet names are final;
      column names in `config/workbook_schema.yaml` are inferred and must be corrected
      against `input/workbook.xlsx` (spec §21 open item 1).

**Done when:** test 9 passes — shifted rows produce identical parse results.

---

## Phase 2 — Validator framework, budget and structure rules

- [ ] `validate/base.py` (protocol, `Finding`, `Severity`), `validate/registry.py`,
      `validate/runner.py` that runs **every** validator and collects all findings.
- [ ] Rules `BUD-001..004`, `STR-001..007`, `ACT-001..003` (spec §9.3, §9.9).
      `BUD-001`, `STR-001`, `STR-002` enforce the Stage-1 invariants exactly (Decision A2).
- [ ] Waiver plumbing with an **empty** waivable-rule allowlist (spec §9.9). Waivers
      record human acceptance; they never suppress a rule.
- [ ] `report/preflight.py` producing the exact format in spec §12, plus `findings.json`.
- [ ] `apex validate` wired end-to-end: validation only, never writes CSVs.

**Done when:** tests 7, 8, 9, 11 pass.

---

## Phase 3 — Keyword and negative rules

- [ ] `KW-001..008` (spec §9.4), including `KW-008` `LEGACY_MATCH_TYPE_NORMALIZED`.
      The `Modified Broad → Phrase` map is a module constant. `Broad` still blocks.
- [ ] `NEG-001..007` with the collision algorithm implemented **exactly** as spec §9.5:
      scope overlap × match semantics, on normalised tokens, no close-variant expansion.
- [ ] Shared-list resolution: expand each list's `applies_to` campaigns **before**
      checking overlap (Decision A4). A list not applied to a campaign cannot collide
      with that campaign's keywords.
- [ ] `NEG-006`: a declared shared list applied to no campaign fails the build.
- [ ] `tests/unit/test_negative_collisions.py`: at least one case per match type per
      level, plus applied/not-applied shared-list cases and the different-campaign case.
- [ ] Fill `negatives.shared_lists.*.applies_to` in `config/rules.yaml` from the workbook.

**Done when:** tests 3, 4, 5, 6, 26, 27, 28, 29, 30 pass.

---

## Phase 4 — Ads, landing pages, tracking, settings

- [ ] `AD-001..012`, `LP-001..004`, `TRK-001..005`, `SET-001..004` (spec §9.6–§9.8).
- [ ] Call-asset resolution, most-specific-wins: ad group → campaign → default
      (Decision A5). `AD-006` requires every ad group to *resolve* to an asset;
      `AD-012` fails while `number`/`schedule` are still the placeholder `REQUIRED`.
- [ ] `ingest/urlcheck.py` implementing the twelve-step sequence in spec §9.6 exactly:
      https-only, allowed domain, GET, timeout, follow redirects, depth cap, final 200,
      final domain re-checked, GoogleAdsBot retry, latency and final URL recorded.
- [ ] Three result states `PASS` / `BLOCKER` / `UNKNOWN`. `UNKNOWN` never counts as
      `PASS` and never yields a `READY` build (Decision A6).
- [ ] Per-URL results table in the pre-flight report.
- [ ] URL checking is mocked in tests; no test may hit the network.

**Done when:** tests 10, 12, 13, 31, 32, 33, 34, 35 pass.

---

## Phase 5 — Transform, Editor export, manifest

- [ ] `compile_/transform.py`: normalisation, dedupe, forced `PAUSED`, derived daily
      budgets, negative expansion, deterministic sort (spec §10.2).
- [ ] `compile_/editor_export.py`: schema-driven writer per `config/editor_schema.yaml`,
      `utf-8-sig`, `\r\n`, minimal quoting; `UnmappedFieldError` on any unmapped field.
- [ ] Second, independent assertion that every emitted campaign row is `Paused`.
- [ ] `MANUAL_STEPS.md` generator including the enumerated unmapped fields and the
      standing post-import procedure (spec §11.4–§11.5).
- [ ] Three build outcomes per spec §10.5: `READY` (exit 0), `DRAFT` (exit 6, written to
      `<run_id>.DRAFT/` with `DO_NOT_IMPORT.txt`, `latest` untouched), `FAILED` (exit 2).
- [ ] Staged writes: `<run_id>.partial/` renamed on success; removed on failure.
- [ ] `manifest.json` per spec §10.6; `output/build/latest` pointer.
- [ ] `apex build` wired end-to-end.
- [ ] **Verify Editor column headers against a real Editor export** before filling
      `config/editor_schema.yaml` (spec §21 item 5).

**Done when:** tests 1, 2, 14, 15, 16, 17 pass.

---

## Phase 6 — Search-Term Watchdog

- [ ] `ingest/search_terms.py`: reads a file **or** a directory (default
      `input/search_terms/`, newest CSV wins, filename echoed — never picked silently),
      alias-driven column resolution, `parse_errors.csv`, fail-closed on a missing
      required column, WARNING when the date range is not the previous 7 days.
- [ ] `watchdog/classify.py`: deterministic taxonomy classifier with documented
      precedence; unresolved terms labelled `CLASSIFIER_UNRESOLVED`.
- [ ] `watchdog/routing.py`: expected owner vs actual owner, with money at stake.
- [ ] `watchdog/findings.py`: `JUNK`, `HELD_DEMAND`, `CONCENTRATION`, `BRAND_LEAK`,
      `SPECIALTY_LEAK`.
- [ ] `watchdog/suggest.py`: narrowest text, lowest level, phrase-over-broad, and the
      §9.5 collision check — colliding suggestions become `ROUTING_CONFLICT` rows.
- [ ] Outputs per spec §13.6; optional `dashboard.html` (self-contained, no CDN).
- [ ] `--propose-writeback` emitting new files only, never touching the workbook.

**Done when:** tests 18–22 and 36 pass, including the workbook-hash-unchanged test.

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
