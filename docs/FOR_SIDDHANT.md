# For Siddhant — what we're building, in plain English

No jargon in this document without an explanation. If something here is still unclear,
that is a fault in this document and I should fix it.

---

## 1. The one-sentence version

We are building a **safety machine** that sits between your Excel plan and Google Ads, so
that the ads you actually run are exactly the ads you approved — and stay that way.

---

## 2. The problem we have today

You already have an Excel workbook that says what the Google Ads account should look
like: which campaigns exist, how the ₹62,000 monthly budget is split, which keywords you
want to buy, which words you want to block, what the ads say, which pages they point to.

That workbook is correct. The problem is **the journey from the workbook into Google
Ads**, which today is a human copying and typing.

Humans copying hundreds of rows produce a predictable set of mistakes:

| What goes wrong | Why it's expensive |
| --- | --- |
| A keyword gets set to the wrong "match type" | You pay for searches you never wanted |
| A budget gets typed as ₹600/day instead of ₹329/day | You overspend, quietly, for weeks |
| A blocking word accidentally blocks a word you're paying for | You pay for a keyword that can never show |
| An ad points at a page that was renamed or deleted | You pay for clicks that land on a 404 error |
| Someone changes a setting three months later | Nobody notices until the money's gone |

None of these announce themselves. Google Ads will happily run a badly built account and
charge you for it. That's the real issue: **the account can be wrong without looking
wrong.**

---

## 3. What we're building — three programs

Think of a restaurant. Your workbook is the recipe book. Google Ads is the kitchen.

### Program 1 — The Build Compiler ("the checker and the printer")

Before service starts.

It reads your recipe book, checks it against every rule you've agreed, and then prints
clean instruction cards for the kitchen.

If it finds a real problem, it **stops and prints nothing.** It doesn't print
three-quarters of a plan and let someone improvise the rest.

Plain example of it refusing:

```
BUILD FAILED

✅ Monthly budget        ₹62,000
✅ Campaigns             5
✅ Ad groups             9
❌ Landing pages         1 broken (404)
❌ Missing call numbers  5

NO FILES GENERATED
```

You fix the workbook. You run it again. That loop is the whole idea.

### Program 2 — The Search-Term Watchdog ("what did we actually pay for?")

Every Friday, after launch.

Google shows your ads for searches you never typed into a spreadsheet. Some are great and
you should buy them properly. Some are junk you should block. Some went to the wrong
campaign.

The Watchdog reads last week's search report and tells you which is which — and suggests
words to block. **It only suggests.** A human approves before anything changes.

### Program 3 — The Drift Checker ("did anyone change things?")

Also weekly.

It compares what your workbook says the account *should* be against what the account
*actually is*, and reports differences:

```
CRITICAL DRIFT

MLN | Search | Ortho | Jaipur
  Budget
    Approved: ₹329/day
    Live:     ₹600/day
```

Somebody changed a budget. Maybe for a good reason, maybe by accident. Either way you now
find out this week, not next quarter during the traditional corporate ritual of asking
"who changed this?"

---

## 4. How one build actually runs

```
Your Excel workbook
        ↓
1. READ      the software reads the workbook (and never edits it)
        ↓
2. CHECK     it runs every rule you've agreed to
        ↓
3. DECIDE    any serious problem? → STOP, print the problem list, produce nothing
        ↓
4. WRITE     no problems? → write the import files
        ↓
5. HUMAN     a person loads those files into Google Ads Editor and reviews them
        ↓
6. PAUSED    every campaign arrives switched OFF
        ↓
7. SIGN OFF  a person checks it, then turns the campaigns on deliberately
```

Two things to notice, because they're the heart of the design:

- **The software never turns your ads on.** It prepares; a person launches.
- **The software never edits your workbook.** The workbook stays yours.

---

## 5. Why everything arrives "PAUSED"

Paused means the campaign exists in Google Ads but isn't spending money.

If the software created campaigns already running, then any mistake that slipped through
would start costing money instantly, at 2am, with nobody watching. Paused means a mistake
costs nothing until a human has looked at it and switched it on.

This is not adjustable. There is no setting to make it launch things live.

---

## 6. What the seven decisions you approved actually mean

You approved these as A1–A7. Here they are in plain English, because some of them have
real consequences.

**A1 — "There is only one workbook, with four tabs."**
An earlier document listed eleven sections. Those were descriptions of what the *software*
needs to do, not eleven Excel tabs. Without this decision, the software would have spent a
long time hunting for tabs that don't exist.

**A2 — "₹62,000, 5 campaigns, 9 ad groups are fixed."**
The software refuses to build anything that doesn't match these exactly.
**What you agreed to:** you can no longer override this from inside the spreadsheet. If
the strategy genuinely changes, someone changes a settings file and that change is
visible. This is stricter than my first draft, and you were right to make it so — a
setting that can be argued away in a hurry always is.

**A3 — "Modified Broad becomes Phrase; Broad is banned."**
These are "match types" — how loosely Google is allowed to match your keyword to what
someone actually searched. Broad is the loosest and the most wasteful. Google retired
"Modified Broad" years ago, so if the workbook still says it, the software quietly
converts it and tells you. But if the workbook says plain "Broad", the build fails.

**A4 — "Blocking words keep their scope."**
A blocked word can apply everywhere, or to a group of campaigns, or to just one. Keeping
that structure means you write a blocking word once instead of copying it five times — and
five copies is how one copy ends up out of date.
**Why this mattered technically:** the software checks whether a blocking word accidentally
blocks a keyword you're buying. It has to check that *only where the blocking word actually
applies*. Otherwise it produces hundreds of false alarms, and false alarms train people to
ignore the report.

**A5 — "One phone number, with exceptions if needed."**
Nine ad groups don't need nine phone numbers. One number that gets answered beats nine that
don't. If one specialty later gets its own coordinator line, that's a small change.

**A6 — "If we can't check a webpage, we don't ship."**
Before building, the software visits every landing page to confirm it loads. Three possible
answers: works, broken, or **couldn't check** (no internet, timeout).
**What you agreed to:** "couldn't check" is treated as *not good enough*. The build gets
quarantined and marked do-not-import. This is stricter than my first draft, which would
have let it through with a note. Your version costs a few seconds of waiting and prevents
launching ads at a page that quietly disappeared.

**A7 — "Gaurav exports the search report every Friday."**
Manual, on purpose, for now. Later this could connect to Google automatically. Doing that
first would mean debugging an automatic system before anyone trusts the basic one.

---

## 7. Where we are right now

Think of building a house.

| Stage | Status |
| --- | --- |
| Deciding what the house must do | ✅ Done |
| Detailed architectural drawings | ✅ Done — this is the "spec" |
| Deciding the disputed details | ✅ Done — your A1–A7 answers |
| Fixing seven contradictions in the settings | ✅ Done — your review caught them |
| Reading the real workbook, writing the true map | ✅ Done — "Pre-Phase" |
| Laying foundations | ⬜ Not started — "Phase 0" |
| Building it, room by room | ⬜ Phases 1–7 |
| Moving in | ⬜ First real build |

**There is no working software yet.** What exists is a very detailed instruction manual so
that whoever writes the code — me, or an AI coding tool called Codex — builds the right
thing and can't quietly cut corners.

That's deliberate. Writing the rules down first is cheap. Discovering halfway through the
code that nobody agreed what "correct" means is not.

---

## 7b. What changed when you sent the workbook

I opened the real file. Two useful things happened.

**First, the guesses were wrong, and that's exactly why we looked before building.** I had
guessed your `02 BUILD` tab held sections called things like "ACCOUNT" and "ADS". It
doesn't. It holds `CAMPAIGN SETTINGS — ONE ROW PER CAMPAIGN`, `LANDING PAGE BUILD BRIEFS`,
`RSA 1` and three others. Your `03 KEYWORDS` tab isn't two lists — it's **one** list where
a `Type` column says whether each row is a keyword you're buying or a word you're blocking.
Had we written the software against my guesses, it would have failed on the real file and
someone would have spent a day wondering why.

**Second, the workbook is in good shape.** The five budgets add up to ₹62,000 exactly —
no rounding fudge needed. There are 112 keywords you're buying and 226 words you're
blocking, all marked approved. Zero of the keywords use the loose "Broad" setting we
banned. Your blocking lists already record which campaigns they apply to, and it matches
what you told me independently.

**One thing I moved.** You'd asked me to keep the phone number in the settings file. The
workbook already has a column for it (currently `[REQUIRED BEFORE LAUNCH]`). By your own
rule — approved values live in the workbook, rules live in settings — the number belongs
in the workbook. So that's where it now comes from, and the settings file only holds the
rule about *how to find* it. Fill in that column in `02 BUILD` when the call centre
confirms the number and hours.

---

## 7c. Google Sheets instead of Excel — yes

Short answer: **use Google Sheets if you prefer.** Edit there, then
`File → Download → Microsoft Excel` before each build. Everything works identically.

Why not connect the software directly to Google Sheets? Because that needs Google login
keys stored on a computer somewhere, and we've promised this tool holds no passwords or
keys of any kind. Trading that promise for one saved menu click is a bad deal. It can be
added later as its own reviewed piece of work if the export ever becomes annoying.

The one genuine risk with Sheets: someone edits the Sheet, forgets to download, and the
software cheerfully builds last week's plan. So every report now prints the file's date
next to its fingerprint, and warns if the download is more than 3 days old.

---

## 7d. You can test it now

The checker works today. It reads the workbook and reports what is wrong; it does not yet
produce files for Google Ads.

Step-by-step instructions are in [`HOW_TO_RUN.md`](HOW_TO_RUN.md) — three options,
including "send me the file and I run it", which needs no installation at all.

The most useful thing to try is breaking something deliberately: change a budget in a copy
of the Sheet, run the check, watch it get caught, change it back. That loop — edit, run,
read, fix — is the entire product.

The next result worth waiting for is **Phase 3**, which checks whether any of your 226
blocking words accidentally blocks one of the 112 keywords you are paying for. That is the
first answer the software is likely to know that you do not.

---

## 7e. What this looks like when it is finished

Three moments in the week, and one loop before launch. Nobody learns a new tool: the
workbook stays the interface, and Gaurav runs one command.

### Before launch — the build loop

```
Someone edits the Google Sheet
        ↓
Gaurav downloads it as Excel and runs one command
        ↓
The checker reports every problem, with sheet and row numbers
        ↓
People fix the Sheet
        ↓
Repeat until it says READY
        ↓
It writes the import files
        ↓
Gaurav loads them into Google Ads Editor, runs "Check changes", posts
        ↓
Five campaigns appear in Google Ads — PAUSED, spending nothing
        ↓
A second person does QA against the report
        ↓
Sign-off recorded in 01 ACTIONS
        ↓
A human enables the campaigns, deliberately
```

The loop is the product. Today it takes a person a day and mistakes survive it. Finished,
it takes ten seconds and mistakes do not.

### Monday — the efficiency review

Unchanged from how you work now: you and Gaurav look at mature 7- and 28-day Qualified
Leads, and decide about budget and bidding. Software is not involved. It should not be.

### Friday — the Watchdog

```
Gaurav exports last week's search terms from Google Ads
        ↓
Runs one command
        ↓
Gets four things:
   what people actually searched, classified
   traffic that went to the wrong campaign, with the money at stake
   junk worth blocking, ranked by spend
   demand we are not buying but converted anyway
        ↓
Gaurav and you decide what to accept
        ↓
Approved changes get pasted into 03 KEYWORDS
        ↓
The next build applies them — through the same checker as everything else
```

It suggests. A person approves. Nothing reaches the account without passing the same
checks as the original build.

### Weekly — the drift check

```
Gaurav exports the live account from Google Ads Editor
        ↓
Runs one command
        ↓
Gets a list of every difference between what was approved and what is live
```

```
CRITICAL DRIFT

MLN | Search | Ortho | Jaipur
  Budget      approved ₹329/day     live ₹600/day

MLN | Search | Neuro | Jaipur
  Search Partners   approved OFF    live ON
```

Somebody changed something. Maybe for a good reason. Either the account is wrong and gets
reverted, or the workbook is stale and gets updated and re-approved. A person decides
which; the software never picks a side, because quietly updating the workbook to match
reality would launder an unapproved change into the source of truth.

### Who does what

| Person | What they do | How often |
| --- | --- | --- |
| Siddhant | Approves strategy, budget, the Qualified Lead definition. Reads reports. | As needed |
| Gaurav | Edits the Sheet, runs the commands, imports into Editor, reviews suggestions | Daily / weekly |
| Web | Builds and maintains the nine landing pages | Until launch |
| Tech | Tracking, GCLID, LeadSquared handoff | Until launch |
| QA | Second-person check before launch | Before launch |
| Compliance | Medical, privacy and advertising approval | Before launch |

### What it will never do

It cannot upload to Google Ads, enable a campaign, apply a blocking word on its own,
change your workbook, or be told to skip a check. None of those code paths exist, and
tests fail if anyone adds one.

The worst thing a bug can do is refuse to build something that was actually fine — which
costs you a conversation, not money.

---

## 7f. The outside review found six things — all six are fixed

Someone independent read the code and found six problems worth fixing before we build the
Friday Watchdog. None of them had reached your account — nothing has been imported yet —
but four of them would have been very hard to spot once it had. Here is each one in
plain English.

**1. The phone number could be checked in one place and printed in another.**

The tool checks your call number (is it real? is it staffed?) and then writes an
instruction sheet telling whoever does the import what number to create. Those were two
separate lookups. If you had ever set a different number for one ad group — say a staffed
neuro line — the tool would have *checked* the special number and *told your operator to
type* the general one. Both halves looked perfectly correct on their own.

We fixed it by making one lookup, once, that everything else reads. And the phone number
now lives only in your workbook, never in the settings file — where a number does not
belong. If you ever want a different number for one campaign or ad group, there is a new
optional block in `02 BUILD` called **CALL ASSET REGISTRY** where it goes. You do not need
it today; leaving it out means "one number for everyone", which is what you have.

*Trade-off:* one more optional block in the sheet. In exchange, the number that gets
checked is guaranteed to be the number that gets created.

**2. An unverified claim could reach a finished build.**

Your workbook has an ad extension marked `VERIFY FACT` — "Diagnostics Available" — which
is a human saying *I am not sure this is true*. The tool treated that as a mild note. It
treated a *blank* status as serious. That was backwards: a blank cell is an unfinished
spreadsheet, while `VERIFY FACT` is a warning about a claim you would be making to
patients. Now anything not marked APPROVED stops a deployable build.

**3. Patient searches are now impossible to leak into a log file.**

Phase 6, the Friday Watchdog, reads what real people typed into Google. Those are
searches like *paralysis treatment cost* or a doctor's name. We already masked anything
that looked like a phone number or an email — but that only catches things with the right
*shape*. A sentence about a diagnosis has no shape to catch.

So we changed how the software holds a search. It is now physically unable to print one.
Every accidental way of writing it out produces a code like `query:q9f86d0818821` instead
of the words. Getting the actual words requires deliberately asking, and only in the one
place allowed to write your private analysis file. We built this **before** the Watchdog
exists, because "remember not to write it down" is not a safeguard.

**4. A failed build could report that nothing was wrong.**

Two of the checks run late, during file-writing rather than during checking. If one of
those failed, the tool correctly refused to produce files — and then printed a report
listing no problems at all. A report that says "FAILED" and then shows a clean page is
worse than no report: it teaches people to stop believing it. All findings now go into
one report.

**5. Two identical column headings in the sheet.**

If somebody pastes a column back into `02 BUILD` and you end up with two `Status`
columns, the tool used to read one and quietly ignore the other. You would have a 50/50
chance of maintaining the one it ignored. It now stops and tells you both positions —
"column S and column W" — so you can find them.

**6. A finished build now has to come from saved work.**

Every build records which version of the code produced it. It was recording that even
when the code had unsaved edits — naming a version that never actually ran. Builds from
unsaved work are now marked DRAFT, never deployable, with the reason written on the box.

### What this means for you

Nothing to do. No decision needed. The 12 red items in `01 ACTIONS` and the missing phone
number are still the things standing between you and a real build — that has not changed.

## 8. What happens next

**One thing only you can provide:**

- **The phone number and its hours** — the `Call phone number` and `Call schedule`
  columns in `02 BUILD`, currently `[REQUIRED BEFORE LAUNCH]`. Not urgent: development
  runs fine without it. It only becomes blocking when we try to produce a build that's
  actually deployable, which is the correct place for it to bite.

✅ The workbook is here and has been read. That unblocked everything else.

**Then, step by step:**

- **Phase 0** — the empty shell. Proves the setup works. Doesn't need the workbook.
- **Phase 1** — teach it to read your workbook.
- **Phases 2–4** — teach it the rules: budgets, keywords, blocking words, ads, pages.
- **Phase 5** — teach it to write the Google Ads Editor files. *First real output here.*
- **Phase 6** — the Friday Watchdog.
- **Phase 7** — the Drift Checker.

Each phase is small and reviewable. You'll be able to see something work early rather than
waiting months for one big reveal.

---

## 9. Glossary

| Term | Plain English |
| --- | --- |
| **Campaign** | A container in Google Ads with its own budget. You have 5. |
| **Ad group** | A smaller container inside a campaign, holding related keywords and ads. You have 9. |
| **Keyword** | A word or phrase you're willing to pay to show ads for. |
| **Match type** | How loosely Google may match your keyword to a real search. Exact = strict, Phrase = medium, Broad = loose and wasteful. |
| **Negative keyword** | A word that *stops* your ad showing. "Blocking word." |
| **Search term** | What a real person actually typed. Different from your keyword. |
| **Landing page** | The page on your website the ad sends people to. |
| **Google Ads Editor** | A free desktop app from Google for making bulk changes. It can load files. This is how our files reach Google. |
| **CSV** | A plain table file. Excel can open it. Google Ads Editor can import it. |
| **PAUSED** | The campaign exists but isn't spending. |
| **Compiler** | Software that turns one format into another — here, workbook → import files. |
| **Validation / rule** | An automatic check, like spell-check for your ad account. |
| **BLOCKER** | A problem serious enough that the tool refuses to produce anything. |
| **WARNING** | Worth knowing, doesn't stop the build. |
| **Spec** | The instruction manual for whoever writes the code. |
| **Repo (repository)** | The folder on GitHub where all of this is stored. |
| **Commit** | A saved snapshot of changes, with a note about what changed. |
| **Branch** | A working copy of the project where changes happen before being made official. |
| **Codex** | An AI tool that writes code by reading instructions like our spec. |
| **Phase** | One chunk of building work, reviewed before the next starts. |
