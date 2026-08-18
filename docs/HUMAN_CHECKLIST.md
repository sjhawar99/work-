# Human checklist — what a person must do before code can start

The specification is complete. It cannot be implemented correctly until the items below
are answered by someone who knows the Apex account. Nothing here needs a developer.

Work top to bottom. Items in Part A block Phase 1; items in Part B block Phase 5.

---

## Part A — Decisions ✅ ANSWERED

All seven are locked and encoded. Full reasoning in [`DECISIONS.md`](../DECISIONS.md).

| ID | Decision |
| --- | --- |
| A1 | Four-sheet workbook is the only workbook; the eleven "sections" are software capabilities |
| A2 | ₹62,000 / 5 campaigns / 9 ad groups / `apexhospitals.com` — Stage-1 invariants, not waivable |
| A3 | `Modified Broad` → `Phrase` + warning; `Broad` blocks the build |
| A4 | Hybrid negatives: account / shared list / campaign / ad group, scope preserved |
| A5 | One default call number, optional overrides — not nine numbers |
| A6 | Landing-page checks block the build; `UNKNOWN` ≠ `PASS` |
| A7 | Gaurav exports search terms every Friday to `input/search_terms/` |

Nothing here needs revisiting unless the strategy itself changes.

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

### B3. Two values that are still placeholders

Both live in `config/rules.yaml` and both fail the build until filled — deliberately, so
they cannot be forgotten.

**The call number** (`call_assets.default`):

```yaml
call_assets:
  default:
    country: IN
    number: REQUIRED       # ← the Apex number that answers Google Ads calls
    schedule: REQUIRED     # ← e.g. "Mon-Sat 08:00-20:00 Asia/Kolkata"
```

Rule `AD-012` fails while these say `REQUIRED`. If one specialty gets its own coordinator
line later, it becomes a campaign override — the architecture already allows it.

**Which campaigns each shared negative list applies to**
(`negatives.shared_lists.*.applies_to`):

```yaml
shared_lists:
  ROUTE_BRAND:            {applies_to: []}    # ← which of the 5 campaigns?
  ROUTE_COMPETITORS:      {applies_to: []}
  STAGE1_HOLD_COMPARISON: {applies_to: []}
  STAGE1_HOLD_ACTION:     {applies_to: []}
  STAGE1_HOLD_URGENCY:    {applies_to: []}
```

Rule `NEG-006` fails on any list applied to nothing — a list that protects no campaign is
protection that only appears to exist. This also feeds the collision engine: it decides
where each negative actually applies, and therefore what counts as a real collision.

Either tell me the mapping, or it comes out of the workbook in Phase 3.

---

## Part C — Before the first real build

Do not skip these. They are the difference between a tool that is trusted and a tool that
gets switched off after one bad import.

- [ ] Real workbook at `input/workbook.xlsx`.
- [ ] `call_assets.default.number` and `.schedule` filled with real values.
- [ ] Every shared negative list has a non-empty `applies_to`.
- [ ] `apex validate` run against it, and every BLOCKER fixed in the workbook. Waivers
      no longer suppress rules (Decision A2) — a BLOCKER is fixed, not argued with.
- [ ] Every landing page reports `PASS`. Any `UNKNOWN` means the build is a `DRAFT` and
      must not be imported.
- [ ] First `apex build` output imported into Google Ads Editor **into a draft or a test
      account first**, not straight into the live account.
- [ ] "Check changes" run in Editor, with zero errors, before anything is posted.
- [ ] Every campaign confirmed `Paused` after posting.
- [ ] Sign-off recorded in the workbook by a named person before anything is enabled.
