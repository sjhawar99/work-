# AGENTS.md — rules for coding agents in this repo

Read [`DECISIONS.md`](DECISIONS.md) first — seven questions the spec left open have been
answered, and you must not re-infer them. Then read
[`docs/CODEX_BUILD_SPEC.md`](docs/CODEX_BUILD_SPEC.md), which is the contract. Work through
[`CODEX_TASKS.md`](CODEX_TASKS.md) in order, one phase per PR.

## What this repo is

A file-in / file-out toolchain that turns the Apex Google Ads workbook into validated
Google Ads Editor import files, then monitors search terms and account drift after
launch. It never touches the live Google Ads account.

## Hard rules

1. **No Google Ads API.** No `google-ads` dependency, no OAuth, no upload path. v1
   deploys through Google Ads Editor, driven by a human.
2. **Every compiled campaign is `PAUSED`.** Assert it in the transform *and* in the
   export writer.
3. **No bypass.** Never add `--force`, `--skip-validation`, `--ignore-blockers`, or an
   env var with the same effect. A BLOCKER is fixed in the workbook.
4. **Fail closed.** On any BLOCKER or unhandled exception: write the report, delete any
   partial output, write no CSVs, exit non-zero.
5. **No Broad-match positive keywords, ever.** A workbook row saying `Broad` fails the
   build. A row saying `Modified Broad` compiles to `Phrase` with a `KW-008` warning —
   that mapping is hard-coded in Python, never a config key.
6. **Never write to the source workbook.** Open it read-only. Watchdog write-back emits
   new files for a human to paste.
7. **No validation thresholds, inference cutoffs or platform limits in code.** Approved
   operating values may come from the source workbook; frozen invariants and validation
   thresholds live in config; policy transformations explicitly locked in `DECISIONS.md`
   may be Python constants. The three layers:

   ```
   WORKBOOK      = approved account values      ₹20k Neuro · ₹10k Ortho
                                                Max CPC ₹60 · landing page X
   CONFIG        = rules governing whether      ₹62k total · 5 campaigns · 9 ad groups
                   those values are valid       no Broad positives · 30-char headlines
   PYTHON        = logic                        parse · normalise · compare
                                                validate · export
   DECISIONS.md  = frozen policy                Modified Broad → Phrase · shared-list
                                                scope · four-sheet workbook
                                                human-only deployment
   ```

   This separation is load-bearing. Read "budgets live in config" too literally and you
   will helpfully move campaign budget allocation out of the workbook, defeating the
   entire source-of-truth design. Budget *allocation* is the workbook's. The ₹62,000
   *ceiling it must sum to* is config's.
8. **No row-index parsing.** Find sections by header text and columns by header name.
   `df.iloc[7]` is a bug — humans insert rows. `config/workbook_schema.yaml` records
   `seen_at_row` values for human reference only; using one in code is a bug.
9. **Never silently drop a field.** A workbook field with no Editor mapping goes into
   `MANUAL_STEPS.md` or raises `UnmappedFieldError`.
10. **`UNKNOWN` is never `PASS`.** A landing-page check that could not complete makes the
    run a `DRAFT`: CSVs quarantined in `<run_id>.DRAFT/` with `DO_NOT_IMPORT.txt`, exit 6,
    `latest` untouched. There is no path from "we could not check" to a deployable build.
11. **No PII in logs.** Search-term data may contain patient-identifying text.
12. **Never flatten the negative hierarchy.** `ACCOUNT` / `SHARED_LIST` / `CAMPAIGN` /
    `AD_GROUP` scope is preserved end to end, and collision checking resolves a shared
    list's `applies_to` campaigns before deciding whether a negative can block a positive.
13. **There are exactly four sheets** — `01 ACTIONS`, `02 BUILD`, `03 KEYWORDS`,
    `04 DAILY`. The eleven-area architecture is a list of software capabilities, not tabs.
14. **No `input/` or `output/` files in commits.** Tests read `tests/fixtures/` only.

## Conventions

- Python 3.10+, `src/apex_ads/` layout, `pip install -e .`, imports are `from apex_ads…`.
- `pydantic` v2 models are the contract between layers; pandas stays inside `ingest/`.
- Every finding carries `rule_id`, `severity`, `sheet`, `row`, `entity`, `remedy`.
  Rule IDs are stable forever — retire, never renumber.
- Every output run lives under `output/<program>/<run_id>/`; runs never overwrite.
- Deterministic output: sorted rows, no timestamps inside CSVs. Two runs on one workbook
  produce byte-identical files.

## Before you open a PR

```bash
ruff format . && ruff check . && mypy src/apex_ads && pytest -q
```

Every phase ships with its tests in the same PR. Named acceptance tests are listed in
§19.2 of the spec — the phase is not done until its tests are green.

## When the spec is wrong

Say so in the PR description and stop. Do not quietly widen scope, add a dependency, or
relax a guardrail. §21 of the spec lists the open questions that still need human
answers; add to that list rather than guessing.
