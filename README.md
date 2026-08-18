# Apex Google Ads Operating System — Build & Guardrail Platform

This repository holds the **engineering specification** and (from Phase 1 onward) the
implementation of the software layer that sits behind the Apex Google Ads Operating
System workbook.

The workbook stays the human interface. The code is an invisible enforcement layer
around it.

```
Workbook (single source of truth)
        ↓
Build Compiler        →  validate everything  →  PRE_FLIGHT_REPORT (PASS / FAIL)
        ↓ (only on PASS)
Google Ads Editor CSVs  →  campaigns created PAUSED  →  human QA  →  Google Ads
        ↓
Search-Term Watchdog   (did Google behave?)
Account Drift Checker  (did humans behave?)
```

## Start here

| Document | What it is |
| --- | --- |
| [`docs/CODEX_BUILD_SPEC.md`](docs/CODEX_BUILD_SPEC.md) | The full engineering specification. The contract. |
| [`CODEX_TASKS.md`](CODEX_TASKS.md) | Sequential, scoped implementation tasks (Phase 0 → Phase 7). |
| [`AGENTS.md`](AGENTS.md) | Short repo-specific rules for coding agents. |
| [`docs/CODEX_KICKOFF_PROMPT.md`](docs/CODEX_KICKOFF_PROMPT.md) | The prompt to open a Codex session with. |
| [`config/rules.yaml`](config/rules.yaml) | Every business threshold. No thresholds live in code. |

## Three pillars

1. **BUILD COMPILER** (pre-launch) — turn the workbook into safe, validated Google Ads
   Editor import files. Fails closed. Every campaign is generated `PAUSED`.
2. **SEARCH-TERM WATCHDOG** (weekly, post-launch) — classify search terms, find routing
   leakage, junk and concentration, and propose negatives for human approval.
3. **ACCOUNT DRIFT CHECKER** (weekly, post-launch) — diff the approved workbook state
   against a live Google Ads Editor export and report unauthorised changes.

## Non-negotiables

The code never touches the live account. It writes files a human imports. It never
auto-enables a campaign, never bypasses a BLOCKER, never adds a Broad-match positive
keyword, never auto-applies a suggested negative, and never overwrites the source
workbook. See §18 of the build spec for the complete list.

## Status

Specification complete. Implementation not started — begin at Phase 0 in
[`CODEX_TASKS.md`](CODEX_TASKS.md).
