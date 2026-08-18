# Human checklist — what a person must do before code can start

The specification is complete. It cannot be implemented correctly until the items below
are answered by someone who knows the Apex account. Nothing here needs a developer.

Work top to bottom. Items in Part A block Phase 1; items in Part B block Phase 5.

---

## Part A — Decisions needed before Phase 1

Answer each one. "Not sure" is a valid answer — it becomes a task, not a guess.

### A1. Which workbook is real?

The design brief describes four working sheets:

    01 ACTIONS | 02 BUILD | 03 KEYWORDS | 04 DAILY

The architecture diagram describes eleven sections:

    00 SETUP ... 10 REVIEW & SIGN OFF

**Question:** which one is the file the team actually edits today? If both exist, which
is the master?

**Why it matters:** it decides `config/workbook_schema.yaml`. The parser supports both,
but it has to be pointed at the right sheet names, and guessing wrong means every run
fails with "required column missing" until someone fixes it.

**Answer:**

---

### A2. Confirm the numbers

Currently in `config/rules.yaml`, taken from the plan:

| Setting | Value in config | Correct? |
| --- | --- | --- |
| Monthly budget | ₹62,000 | |
| Campaign count | 5 | |
| Ad group count | 9 | |
| Currency | INR | |
| Timezone | Asia/Kolkata | |
| Primary domain | *(blank — needs filling)* | |

**Why it matters:** `BUD-001` fails the build when campaign budgets do not sum to the
monthly figure. A wrong figure here means the compiler blocks a build that is actually
fine.

**Answer:**

---

### A3. Match types

The diagram permits "Exact, Phrase, Modified Broad". Modified Broad was retired by
Google — it no longer exists as a match type. The spec currently treats any workbook row
saying "Modified Broad" as **Phrase**, and records it in the report.

**Question:** is that the right call, or should those keywords be reviewed one by one
before the first build?

**Answer:**

---

### A4. Negative keyword structure

**Question:** does the account use shared negative keyword lists applied across
campaigns, or are negatives set per campaign / per ad group individually?

**Why it matters:** it changes what the compiler writes into `negatives.csv`, and shared
lists must be created by hand in the Google Ads UI first (they land in
`MANUAL_STEPS.md`).

**Answer:**

---

### A5. Call numbers

Rule `AD-006` blocks the build if an ad group has no phone number reachable — either in
the ad copy or via a call extension covering it.

**Question:** is a call extension at account level sufficient, or does every ad group
need its own number (e.g. per city or per specialty)?

**Answer:**

---

### A6. Landing page checking

Rule `LP-003` requests every landing page URL and fails the build on anything that is not
a `200`. It requires internet access and it will hit the Apex website.

**Question:** is that acceptable, or should URL checking be off by default and run only
when someone asks for it?

**Answer:**

---

### A7. Who owns the weekly runs

**Question:** after launch, who exports the search terms report each week, who exports
the Google Ads Editor file for drift checking, and where do those files get saved?

**Why it matters:** the Watchdog and the Drift Checker are worthless if nobody feeds
them. This is a named person and a day of the week, not a system design problem.

**Answer:**

---

## Part B — Files to collect

Both are needed. Neither gets committed to this repository — `.gitignore` already blocks
them, and the workbook contains client data.

### B1. The workbook

Save the real, current workbook to `input/workbook.xlsx`.

Until this exists, Phase 1 cannot be finished: the section registry in
`config/workbook_schema.yaml` is a starting guess and must be reconciled against the
actual sheet and column names.

### B2. A Google Ads Editor export

In Google Ads Editor: get the latest changes for the account, then export the account to
CSV. Save it under `input/live_export/`.

Two separate things depend on this:

1. **Phase 5** — the exact English column headers Editor expects. These are copied from a
   real export, never from memory. A wrong header means a failed import.
2. **Phase 7** — the drift checker compares this export against the workbook.

If the account does not exist yet, an export of *any* Google Ads account will do for the
column names in Phase 5. Drift checking simply waits until there is an account to check.

---

## Part C — Before the first real build

Do not skip these. They are the difference between a tool that is trusted and a tool that
gets switched off after one bad import.

- [ ] Every Part A question answered, and `config/rules.yaml` updated to match.
- [ ] Real workbook at `input/workbook.xlsx`.
- [ ] `apex validate` run against it, and every BLOCKER either fixed in the workbook or
      consciously waived in `01 ACTIONS` with an owner and a reason.
- [ ] First `apex build` output imported into Google Ads Editor **into a draft or a test
      account first**, not straight into the live account.
- [ ] "Check changes" run in Editor, with zero errors, before anything is posted.
- [ ] Every campaign confirmed `Paused` after posting.
- [ ] Sign-off recorded in the workbook by a named person before anything is enabled.
