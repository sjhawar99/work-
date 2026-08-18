# Codex kickoff prompt

Paste this as the first message of a Codex (or Claude Code) session pointed at this
repository. It deliberately gives a repo map, one scoped phase, and the tests that define
"done" — rather than the entire system in one heroic prompt.

---

```
This repository contains the engineering specification for the Apex Google Ads Operating
System — a file-in / file-out toolchain that compiles an Excel workbook into validated
Google Ads Editor import files, then monitors search terms and account drift.

Read these four files first, in this order:
  1. DECISIONS.md               — seven locked decisions; do not re-infer any of them
  2. AGENTS.md                  — the hard rules you must not break
  3. docs/CODEX_BUILD_SPEC.md   — the full contract
  4. CODEX_TASKS.md             — the phased plan

Then implement PHASE 0 ONLY, exactly as CODEX_TASKS.md describes it. Do not start
Phase 1. Do not implement validators, the compiler, the watchdog or the drift checker.

Constraints that override any instinct you have to be helpful:
  - No Google Ads API. No OAuth. No upload path. Ever.
  - Every compiled campaign is PAUSED. There is no flag that changes this.
  - There are exactly four workbook sheets. Do not look for eleven.
  - UNKNOWN is never PASS. A check that could not run never yields a deployable build.
  - Negative scope (account / shared list / campaign / ad group) is never flattened.
  - No --force, --skip-validation or --ignore-blockers, and no env var equivalent.
  - No business number, character limit, threshold or column name in a .py file. Those
    live in config/*.yaml.
  - Section and column lookup is by header text, never by row index.
  - Fail closed: on any blocker or unexpected exception, write no deployable files.

When you finish Phase 0, run:
    ruff format . && ruff check . && mypy src/apex_ads && pytest -q
and report the output. Then stop and summarise:
  - what you built,
  - anything in the spec that turned out to be wrong, ambiguous or unimplementable,
  - what you would need from a human before Phase 1.

Do not guess at the remaining open items in spec §21, and do not re-open anything in
DECISIONS.md. List what you need and stop.
```

---

## For each later phase

Same shape, three substitutions: the phase number, the section references from the spec,
and the acceptance-test numbers from §19.2 that must pass. Keep one phase per session and
one phase per PR — a phase that is reviewed in isolation is a phase that gets reviewed.

## What not to do

Do not paste the whole build spec into the prompt. It is in the repo; the agent can read
it, navigate it and cite it. The prompt's job is to scope the work and name the finish
line, not to re-transmit the contract.
