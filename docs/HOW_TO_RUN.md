# How to run it — plain English

**Yes, you can test it today.** One of the three programs works: the checker.

It reads your workbook and tells you what's wrong with it. It does not yet produce files
for Google Ads, and it never touches your live account — there is no code in this project
that can.

---

## What it can tell you today

| Question | Answered? |
| --- | --- |
| Do the five campaign budgets add up to exactly ₹62,000? | ✅ |
| Are there exactly 5 campaigns and 9 ad groups? | ✅ |
| Is any keyword using the wasteful "Broad" setting? | ✅ |
| Does every ad group, ad and keyword point at something that exists? | ✅ |
| Are any campaign names malformed, or duplicated? | ✅ |
| Could any landing page belong to two different ad groups? | ✅ |
| Are any red action items still open? | ✅ |
| Do the workbook's own summary boxes match its own rows? | ✅ |

## What it cannot tell you yet

| Question | Arrives in |
| --- | --- |
| Does a blocking word accidentally block a keyword we're paying for? | Phase 3 — next |
| Are the ads within Google's character limits? Is a phone number reachable? | Phase 4 |
| Do the nine landing pages actually load? | Phase 4 |
| Can I have the files to import into Google Ads Editor? | Phase 5 |

The blocking-word check in Phase 3 is the valuable one. Today's checks are the boring
foundation underneath it.

---

## Three ways to run it — pick one

### Option A — send it to me (no setup at all)

Download the Sheet as Excel and send me the file. I run it and send you the report back.
Zero installation. Best if you just want to see what it says.

### Option B — ask someone technical to run it once

Gaurav or the tech team, five minutes. Steps are below and have been tested from a clean
copy of the repository.

### Option C — run it yourself

You need Python installed. On Windows: python.org → Downloads → install, and tick **"Add
Python to PATH"** during setup. On a Mac it is already there.

---

## The steps (tested end to end)

```bash
# 1. Get the code (once)
git clone https://github.com/sjhawar99/work-.git
cd work-

# 2. Install the three things it needs (once)
python3 -m venv .venv
.venv/bin/pip install openpyxl pydantic pyyaml
#    Windows: .venv\Scripts\pip install openpyxl pydantic pyyaml

# 3. Put the workbook where it can find it (every time you want fresh results)
#    In Google Sheets: File → Download → Microsoft Excel (.xlsx)
#    Save it as input/workbook.xlsx inside the folder you just cloned.

# 4. Run the check
.venv/bin/python src/cli.py validate
#    Windows: .venv\Scripts\python src\cli.py validate
```

That is the whole thing. It prints a report and also saves a copy under
`output/validate/`.

---

## Reading the result

```
RESULT: VALIDATION FAILED — 12 BLOCKERS, 10 WARNINGS

SUMMARY
  ✅ Monthly budget         ₹62,000
  ✅ Campaigns              5
  ✅ Ad groups              9
  ✅ Positive keywords      112
  ✅ Negatives              226
  ✅ Broad positives        0
  ✅ Landing pages          9
  ❌ Open RED blockers      12
```

- **✅** — checked, and fine.
- **❌ BLOCKER** — serious enough that the tool would refuse to build anything.
- **⚠️ WARNING** — worth knowing, would not stop a build.

Every blocker names the sheet and row, so you can open the workbook and go straight to
it, and every one suggests a fix:

```
[ACT-001] 01 ACTIONS r13   RED action still Open: 'Approve + operationalise the
                           Qualified Lead definition' (Siddhant)
          Fix: Close the item in 01 ACTIONS, or reduce its severity with the owner's
          agreement.
```

**What today's result means.** Twelve red action items are open, which is true and which
you already know — the workbook says so itself. Everything else passes. That is the
correct answer, and it is worth having the software confirm it independently rather than
trusting the summary box.

---

## A good first experiment

Break something on purpose and watch it get caught. In a **copy** of the Sheet:

1. Change one campaign's monthly budget from ₹20,000 to ₹19,000.
2. Download as Excel, replace `input/workbook.xlsx`, run the command again.

You should see:

```
[BUD-001] 02 BUILD   campaign budgets total ₹61,000 but the approved monthly budget
                     is ₹62,000 (difference ₹1,000)
```

Then change it back. That thirty-second loop is the entire product: **edit the Sheet →
run → read → fix.**

---

## Safety, restated

- It **reads** your workbook. It never writes to it.
- It never connects to Google Ads. It holds no passwords or keys of any kind.
- Nothing it does can change a live campaign, because no such code exists in this project.

The worst thing a wrong answer can do today is waste your time.

---

## When to test again

After **Phase 3**, which adds the blocking-word collision check. That is the first result
likely to tell you something you did not already know.
