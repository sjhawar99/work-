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

## 7g. The reviewer checked the fixes — and found three problems in them

This is worth pausing on, because it is the honest version of how this project works.

Last round we fixed six things. The reviewer then went back and attacked **the new parts
we had just built**, rather than re-reading the old code. He found three defects, two of
which existed *only because* of last round's fixes. That is the normal pattern: new
machinery gets the least scrutiny at exactly the moment everything else starts depending
on it.

All three are now fixed. Here they are.

**1. I overclaimed on the patient-search protection.**

Last round I told you the software was "physically unable to print a search". It was not.
The words were still stored on the object, and a single line of ordinary Python — the kind
of thing any tool that converts data to text does automatically — handed them straight
back.

The claim was in the code's own documentation, which is the dangerous part: anyone
building the Watchdog on top would have written their code trusting a guarantee that did
not exist. The searches would then have reached a log file, and nobody would have looked,
because the file said it was safe.

It is now genuinely true. The search text is not stored on the object at all — it is held
in a way that ordinary conversion, copying, saving and printing simply cannot reach. I
tested all seven routes in, individually, and each one now refuses.

*I should say plainly:* the previous statement to you was wrong, not merely optimistic. It
has been corrected in the record.

**2. A misspelled heading would have silently thrown away your override.**

Remember the new optional CALL ASSET REGISTRY block — the one where you'd put a different
phone number for one campaign? If Gaurav added it and typed `Call phone no.` instead of
`Call phone number`, the tool would have shrugged, treated the whole block as *not there*,
used the general number instead, and printed a note reading "None needed."

So the one thing the block exists to prevent — a number you chose being quietly replaced
by a different one — could have happened inside the block itself.

The rule is now: **a section that is missing is fine; a section that is there but broken
stops the build.** Missing means you didn't ask for anything. Broken means you asked for
something the machine couldn't read, and guessing at that point is never safe.

**3. The registry accepted instructions that don't mean what they look like.**

Three ways a row could mislead you:

- Two rows could name the same ad group with different numbers. The tool would take
  whichever came first and never say which one it used.
- A row saying *level: whole account, campaign: Neuro* looks like it's about Neuro. The
  tool ignores the Neuro part and applies that number to **all five campaigns**. Same trap
  the other way round: naming an ad group on a campaign-level row covers the entire
  campaign.
- A row marked `VERIFY` — meaning *nobody has confirmed this yet* — could still supply the
  live phone number patients dial. That is the identical mistake we'd just fixed for your
  ad extensions, one layer over.

The registry now enforces strict rules: each level requires exactly the boxes it actually
uses and refuses the ones it ignores; two rows can't cover the same thing; and a row must
be marked APPROVED before its number reaches a real build.

The guiding idea, worth remembering: **a box the machine ignores is a box a human will
trust.** If a row reads narrower than it acts, it is a trap regardless of whose fault it
is.

We also made the instruction sheet name the exact spreadsheet row each number came from —
"02 BUILD row 91" — because the first question anyone asks about a phone number in a live
account is *why is this one here*.

**One thing left open on purpose.**

The reviewer also noted that the code we use to refer to a search — the `query:q9f86d08`
handle — could in principle be guessed by someone testing likely phrases against it. He
flagged this as *worth doing later*, not as a blocker.

I have deliberately not changed it yet, and I want you to know why rather than have it
pass unnoticed. Making it unguessable requires a secret key, and every report that ever
quoted one of those codes stops matching if that key changes. Whether that's the right
trade depends on how the Friday Watchdog compares one week to the next — which is Phase 6,
and does not exist yet. Deciding it now would mean guessing. It is written down as an open
item so it gets settled when the Watchdog is designed, not forgotten.

### What this means for you

Still nothing to do. No decision needed, no change to your sheet. The reviewer's verdict
is that once these three are fixed, Phase 5 is finished and Phase 6 can begin.

## 7h. Phase 6 is built — the Friday Watchdog

The reviewer signed off Phase 5 and approved Phase 6. It is now written and tested.

**What it does, in one sentence:** every Friday, Gaurav exports what people actually
typed into Google, runs one command, and gets a ranked list of where your money went and
which words are wasting it.

**What it does NOT do.** It has no access to your Google Ads account. It does not change
your workbook. It suggests; you decide; you paste what you agree with into the sheet; the
next build enforces it. That chain is deliberate — it is the only reason there is a record
of *who approved what*.

### What you get, every Friday

- **actions_report.txt** — the summary, ranked by money. Read this first.
- **search_term_analysis.csv** — every search, with the actual words, so you can judge.
- **negatives_suggestions.csv** — blocking words we suggest adding, with the evidence.
- **routing_issues.csv** — searches that went to the wrong campaign, and what that cost.
- **dashboard.html** — the same thing, easier on the eye.

### Two things worth understanding

**1. It refuses to tell you what is "too much".**

You will see the word REVIEW next to almost every row. That is deliberate, not a bug.

The tool will happily tell you *"this one search took 79% of the Neuro budget last week"*.
It will **not** tell you that 79% is unacceptable — because nobody has decided that yet,
and there isn't enough of your own data to decide it honestly. If we picked a number today,
that number would quietly become policy forever and nobody would remember it was a guess.

So it ranks by money and shows the evidence. You decide. Later, once we have a month of
clean data, you set the real numbers and the same rows start carrying verdicts.

**2. Patient searches are handled carefully, and there is one file to be careful with.**

People type frightening, private things into Google. The report, the dashboard and the
technical files identify each search by a code like `q1148728cd7e9` — never the words.
Those are the files you can safely forward or paste into a message.

**Exactly one file has the actual words: `search_term_analysis.csv`.** It has to, because
you cannot judge whether a search is waste without reading it. That file stays on the
machine, is never committed anywhere, and is the one to think twice before emailing.

### One new thing on your machine

The first Friday run creates a small key file called `.apex_secrets/query_id.key`.

What it does: it makes those `q1148...` codes both **consistent** (the same search gets the
same code next week, so we can spot repeat offenders) and **unguessable** (someone holding
a report cannot test whether a particular phrase produced a particular code).

What you need to do: **back that file up**, alongside the workbook. If it is lost, nothing
breaks — but next week's codes stop matching this week's, so you lose the ability to say
"this junk search is back again". That is the honest trade, and the reviewer and I both
think it is the right one.

### Three bugs I found by running it

I want to name these because they show what the testing is for.

- It suggested blocking the word **"apex"** — your own hospital name. A brand search going
  to the wrong campaign is a *routing* problem; the fix is to cover it properly, never to
  stop bidding on your own name.
- It classified **"apex hospital job"** as a brand win rather than junk, because your name
  outranked the word "job". Backwards: a word a human deliberately put on a blocking list
  is a decision, and it should win.
- It suggested blocking the word **"in"**. That would have blocked nearly every search in
  the account.

None of these could have reached Google — everything goes through you first. But all three
would have wasted your Friday, and the third would have looked authoritative while being
catastrophic.

### What you need to do: nothing yet

The Watchdog only becomes useful **after launch**, when there are real searches to read.
The 12 red items in `01 ACTIONS` and the missing phone number are still the only things
between you and a first build.

## 7i. The reviewer checked Phase 6 and found five more — including two in the tests

I need to correct something I told you last time, and explain a pattern that matters more
than any single bug.

**Correction first.** I told you: *"Exactly one file has the actual searches:
`search_term_analysis.csv`."* That was not true. A second file, `routing_issues.csv`, also
listed them. So the number of files you had to be careful about was double what I said.
Fixed — there is now exactly one, and there is a test that counts the files rather than
listing them, so a third one cannot appear quietly.

**Now the pattern, because it is the real lesson.** Last time I reported 448 passing tests.
Two of those tests were *wrong* — they had written down the bug as if it were the intended
behaviour. So the code, the documentation and the tests all agreed with each other, and
everything looked perfectly healthy. They just agreed on the wrong thing.

That is worth knowing about this project generally: a green tick means "it does what we
wrote down", not "what we wrote down was right".

**The four other problems, in plain English:**

**1. It would have told you to block searches for other hospitals *everywhere*, including
your own brand campaign.** Your plan deliberately blocks competitor names in four
campaigns but *not* in the Brand campaign — because someone searching "Apex vs [other
hospital]" is worth having. The tool ignored that and proposed blocking them account-wide.
Then, worse, when it wrote the suggestion into a file for you to paste, it relabelled it
from "competitor list" to "junk list" — so the following Friday it would have read its own
suggestion back and treated a competitor as junk. It was quietly changing the meaning of
its own evidence week by week.

**2. It classified "apex hospital jaipur" — your own main search term — as a competitor.**
Here is how. A blocking phrase like "ck birla hospital" was being chopped into three
separate words: "ck", "birla", "hospital". Any search containing *any one* of them counted
as a competitor. Your own name contains "hospital". It would then have suggested blocking
the word "hospital" across the whole account.

Blocking phrases are now kept whole, the way Google actually treats them.

**3. It was using the wrong rulebook to decide whether you have a keyword for a search.**
Google has two different matching systems: a strict one for *blocking* words and a much
looser, meaning-based one for *bidding* words. The tool was using the strict one for both.
That made it report "you have no keyword for this" when in fact you did — which would have
sent you chasing searches you were already covering.

The fix is the honest one: Google's own report already tells us which keyword served each
search, so we read that instead of guessing. And where the tool genuinely cannot know
something, it now says UNKNOWN rather than inventing an answer.

**4. One unreadable row could turn "25% of budget" into "70% of budget".** If a row in the
export is corrupted, the tool skips it — correctly — but it was then calculating
percentages as though the remaining rows were the whole picture. Now, if any row from a
campaign cannot be read, that campaign's percentages are withheld and it says so. You still
get the actual rupee amounts.

### What this means for you

Nothing to do, and nothing about the plan changes. The Watchdog still cannot touch your
account or your workbook.

The one thing worth carrying forward: **exactly one file — `search_term_analysis.csv` —
contains real patient searches.** Everything else uses codes. That is now enforced by a
test that counts, not by me remembering.

## 7j. A decision you should know about: the Watchdog will not write blocking words for you

The reviewer found seven more problems in Phase 6. Four were serious. But one of them
forced a real decision about what this tool is, and you should hear it from me rather than
find it in a file.

### The decision

**The Friday Watchdog will tell you what happened. It will not tell you what to change.**

Specifically, it no longer proposes new blocking words, and it no longer proposes changing
which campaigns an existing blocking list covers. Both of those are decisions about
strategy, and it hands them to you with the evidence attached.

### Why I changed it

Two reasons, and the second is the serious one.

**First:** to propose a *new* blocking word, the tool would have to write out either a
word nobody approved, or the patient's search itself. The second is exactly the text we
have spent weeks making sure stays in one file. There is a safe way to do it — a review
step before that text is written anywhere — but it does not exist yet, and I would rather
ship the safer tool and say so than ship the clever one quietly.

**Second, and this is the real find:** your plan deliberately blocks competitor hospital
names in four campaigns but **not** in your Brand campaign — because someone searching
"Apex vs [other hospital]" is a person comparing you to a rival, and you want that click.

The tool spotted a competitor search running in Brand and produced a ready-to-paste
instruction to **add Brand to the competitor blocking list**. That would have reversed a
decision you made on purpose. And it would have done it in a file labelled "paste this
into your sheet."

Every individual *word* in that suggestion had been checked and was correct. Nobody had
asked whether the tool should be making that kind of change at all.

Now it says instead: *"the competitor list does not cover Brand, and this term served
there, and it cost ₹X — that is a strategy question for you."* No paste-ready row.

### The other four worth knowing

**It was proposing to add blocking words you already have.** For a word already on your
list, the "fix" was to add it again — a duplicate. What that situation actually means is
either the export covers a period before you added it, or the list is not switched on in
the account. It now tells you to check those, in that order, instead of guessing.

**I broke the meaning of "missed demand" while fixing something else.** Last round I
changed it to mean "you have no keyword with exactly this wording" — which is not missed
demand at all. The example that proves it: someone searched *paralysis treatment cost
jaipur*, Google served your ad through the keyword *neurologist jaipur*, and it converted
twice. Nothing was missed. Calling that missed demand would have sent you chasing traffic
you already had. Both meanings now exist, under two honest names.

**A keyword running in the wrong place was being marked as fine.** The tool checked "does
this keyword exist in the plan?" but not "is it running where the plan says it should?" It
now checks both.

**Row numbers in the error file were wrong** — off by three, because Google puts a title
and a date line above the table. If Gaurav had gone to "row 2" he would have looked at the
wrong line. And an export with no date column could quietly be a month of data being read
as a week. Both fixed.

**One more privacy hole, and it was a genuinely interesting one.** Everything we built
guards the patient's search text. But if somebody searches for a word that is *already on
your blocking list* — imagine someone literally searching "job" — then the tool prints
that word for perfectly legitimate reasons, and in doing so prints the search. The
protection was never broken; the word arrived by a different door. It now withholds any
such word from the shareable files and points to the one file that is allowed to hold it.

### What this means for you

Nothing to do. But the shape of the tool has changed, so it is worth being clear:

**Before:** it would suggest blocking words and you would approve them.
**Now:** it shows you what happened and what it cost, and you decide what to block.

That is more work for you on a Friday and much less risk of the tool quietly undoing a
decision you made deliberately. If you would rather have the suggestions back, that is a
conversation we can have — it needs the review step built first, and I would want to build
that properly.

## 7k. We deleted one of the Watchdog's reports — it was measuring the wrong thing

The reviewer came back a fourth time. Four things needed fixing. One of them is worth
your attention, because it is about a number I nearly gave you that would have been wrong.

### The report that could not exist

The Watchdog was going to give you a section called **"held demand"** — meaning
*"people are searching for this and we are not showing up at all."* That is a genuinely
useful thing to know. It is also a thing the file we read **cannot tell us.**

The file is Google's search-terms report. It lists searches where your ad **did** show.
A search where your ad never appeared does not create a line in that file. There is
nothing there to count.

So what was the section actually counting? Searches where your ad **did** show, but
through a keyword that isn't in your workbook. That is a real and useful finding — it
means your live account has drifted away from your plan. But it is not "we're invisible
for this". It is nearly the opposite: you paid for that click.

Two completely different situations, one label. Whoever read that section on a Friday
would have drawn the wrong conclusion and spent money accordingly. The section is gone.
The two honest questions it was mixing up now have their own names:

- **"No keyword of our own"** — someone searched, converted, and we have no keyword
  specifically for it. *Worth considering bidding for deliberately.*
- **"Unapproved keyword"** — someone searched and we showed up through a keyword that
  isn't in your workbook. *Your account has drifted; go and look.*

If you do want the original — real "we're invisible for this" data — that needs a
different file from Google (keyword planner or impression-share data). We do not have it
yet. I would rather say that than invent a substitute and give it a confident name.

### The tool was asking you to re-approve your own decisions

You decided that the competitor blocking list covers the specialty campaigns and
deliberately does **not** cover the Brand campaign. That was on purpose.

Every Friday, the tool was going to see that decision working exactly as intended and
write you an amber action item asking you to review it. Same one. Every week. Forever.

The reviewer's phrase: *"that is how dashboards become wallpaper."* Ask someone to
re-approve a working decision fifty times and they stop reading the file — and the
fifty-first line is a real problem.

Now that situation is filed under **"EXCLUDED BY DESIGN"**, marked as information only,
with the remedy line reading *"None. Approved policy deliberately excludes this
campaign."* It shows you the cost so you can see it. It asks you for nothing. The new
rule:

> Something becomes an action item when it **contradicts** your decision — not when it
> follows it.

The opposite case still raises an action, because that one genuinely contradicts you: a
blocking word you approved, and the search got through anyway.

### It was warning you about perfectly good exports

If you asked Google for "last 7 days" and Sunday happened to be quiet, the tool counted
the days that had activity, got six, and warned you the export looked short.

Quiet days are normal. A warning that fires on healthy files gets ignored, and then it
fires on a genuinely broken file and nobody looks. Fixed: the tool now reads the date
range Google prints at the top of the file — *the window you asked for* — and treats the
day-by-day activity as a cross-check rather than as the answer. If the two disagree, it
says so specifically. If neither can be read, that is still a warning, exactly as before.

### A promise I made about privacy, walked back slightly

Earlier I told you the "only one file ever contains real patient searches" guarantee was
now **structural** — a property of the design, not luck. That was slightly too strong,
and the reviewer said so.

What is actually true: raw searches have exactly one deliberate destination, and the two
ways an account setting could accidentally *be* a patient's search — a blocking word, a
keyword — are guarded and will print as "withheld" instead. That covers the routes we
know about. It is not a mathematical proof that nothing else could ever coincide,
because your account settings are typed by people and could say anything.

Nothing about the code changed here. Only what I claim for it, which now matches what it
does. I would rather tell you the honest boundary than let a confident sentence sit in a
file you might one day rely on.

### What you need to do

Nothing. No decision for you here.

The thing worth carrying: **a finding was deleted, not renamed.** It had a definition, a
setting, a report section and passing tests — everything except data that could actually
produce it. That is the failure mode this whole review process exists to catch, and it
has now caught the same shape three times. Deleting is allowed. Keeping a number because
it looks complete is not.

## 7l. The tool knew the right answer; its reports didn't all say it

Fourth review, and the pattern this time is a single sentence: **we fixed the part that
works out the answer, and forgot that four different files each write the answer down in
their own words.**

### The week it analysed vs the week it said it analysed

Last round we taught the tool the difference between *"the 7 days you asked Google for"*
and *"the days that actually had traffic"*. It learned that correctly and stopped warning
you about good files.

But the tool produces four things — a text report, a web page, a spreadsheet and a small
record file — and three of them were still writing down the *old* answer. So you'd get a
file where the built-in check said "this is a correct 7-day export" and the header of that
same file said "covering 6 days."

Worse: an export that has no day-by-day column at all — which is the normal shape — was
being accepted as valid while the report told you the period was unverified.

Now there is **one** place that decides what period a run covers, and all four files read
from it. The record file also keeps both dates side by side, so if you ever look back at
an old run you can see both what window was selected and which days had traffic.

### The tool was calling your own decision a mistake

You decided the competitor blocking list covers the specialty campaigns and deliberately
**not** the Brand campaign.

Last round I stopped the tool nagging you about that. But it was still *reporting* it — in
one section it said "nothing to do, this is approved policy," and two sections later, about
the exact same search, it said "competitor traffic leaked."

Both about the same event, in the same file. If you read only one of them you'd act, and
the one that looks like a problem is the one people act on.

Now: **"leaked" means the blocking list covers that campaign and the search got through
anyway.** If the list deliberately doesn't cover the campaign, it's filed as approved
policy and nothing else. The opposite case — list covers it, search got through — still
shows up as a leak, because that one genuinely contradicts your decision. I tested both
directions, so the fix can't quietly switch off real leak detection.

### The pretty file was the confidently wrong one

When some rows in Google's export can't be read, the text report says *"₹8,000 across
readable rows — total unknown."* Honest.

The web-page version still showed a big number under the single word **SPEND**. That is
the file someone screenshots and puts in a WhatsApp group, and a screenshot doesn't carry
the text report's caveat with it. Now it says "readable-row spend" with "TOTAL UNKNOWN · 2
rows unreadable" underneath.

### Our own instructions were telling the next robot to undo our work

This one is uncomfortable and worth your attention.

This project keeps two instruction files that any future AI working on it is told to
trust. One of them still said, in plain words, *"the Watchdog suggests blocking words, a
human approves them"* — the design we spent four review rounds deliberately removing. The
other still had an unticked to-do asking someone to build a file-reading module that was
built months ago under a different name.

So: we carefully stopped the software from inventing policy, and left behind a set of
instructions asking the next assistant to build it all back. Both are rewritten, and
there's now an automatic check that fails if anyone reinstates the old wording.

The general lesson, and I think it's the important one for you: **in this project the
written instructions are part of the machine.** A stale sentence in a document isn't
untidiness, it's a live instruction. I'd rather flag that than have you discover it later.

### Two smaller corrections

A summary line said "no explicit keyword: 8" and labelled it as a specific test — but that
test only fired once, because it also requires the search to have converted. Two different
counts under one heading. Now shown as two lines.

And the record file that fingerprints every output was skipping the folder containing the
two files you and Gaurav are actually told to copy-paste. Everything only a computer reads
was covered; the ones with human consequences weren't. Fixed, and the same fix was applied
to the build side so the two can't drift apart.

### What you need to do

Nothing. No decision for you.

The thing worth carrying: **the tool being right isn't the same as the tool saying the
right thing.** Four times now the calculation was correct and a file described it wrongly,
and a file is all you ever see. That's why there's now one place that decides, and
everything else just picks a shape for the answer.

## 7m. Two ways the tool was letting a weak answer stand in for a real one

Fifth review. Two things to fix, and they turn out to be the same mistake made twice —
once in the software, once in our own written instructions.

The mistake, in one line: **something that exists as a backup answer quietly started being
treated as a real answer.**

### It could read a month of data and call it a week

Google's export has two ways to tell us what period it covers. The date line printed at the
top — "August 11 to August 17" — is the window Gaurav actually asked for. And the
day-by-day column, which is just when clicks happened.

We already knew those are different. Last round I made the tool use the top line and treat
the day column as a cross-check. Good.

What I missed: some exports don't print that top line at all. And in that case the tool
fell back to counting the day column — and if that came to seven days, it said "fine, this
is a 7-day export" and moved on.

Here's why that's dangerous. Suppose Gaurav accidentally exports **a whole month**, but
traffic that month happened to fall in one busy week. The day column shows seven days. The
tool sees seven. It says nothing. You spend Friday reviewing a month of data believing it's
last week, and every "this is up / this is down" comparison you make is wrong.

Now: if the top line is missing, the tool says **"SELECTED WINDOW UNVERIFIED"** — no matter
how tidy the day column looks. It still shows you the days it saw, clearly labelled as
"when traffic happened, not the window that was selected."

The rule I've written into the project: *a backup answer is allowed to describe what we
don't know. It is not allowed to promote itself into proof.*

And the good behaviour from last round is protected by its own test: a proper 7-day export
with a quiet Sunday is still accepted silently.

### Our own instructions were still ordering the removed feature

I told you last round that the project's written instructions are part of the machine. This
round proves it, and I got it wrong the first time.

I fixed the *headline* instructions. But the spec also contains a **checklist that defines
what "finished" means** for each part of the project — and two items on it still said, in
plain words: *"produce suggested blocking words, each with evidence"* and *"test those
suggestions."*

So the file simultaneously said "never write blocking words" and "you are not finished
until you write blocking words." Both live. Both instructions to whoever builds next.

Both rewritten to the current behaviour.

**And the check I added last round would not have caught it.** It looked for one specific
old sentence. I tested it against a rewording — *"Watchdog offers candidate exclusions"* —
which is the same removed feature under a different name, and the check let it straight
through. So the checklist items for the Watchdog are now **frozen and held inside the
test**: change any of them and the build fails with a message saying the change has to be
made deliberately, in both places at once.

That is the honest fix. You cannot keep a list of banned words ahead of someone rewording
around them; you can pin the actual promise and make any change to it visible.

### Two small ones

A summary line said "no exact keyword: 8 — queries served by a broader keyword." The number
was right; the explanation was a guess. Some of those 8 were served by a keyword that isn't
in your workbook at all, and for some we don't know what served them. Now it just says
"Workbook has no exact keyword: 8" and claims nothing more.

And an internal list of "files this run produced" was pointing at the wrong location for
the two files you and Gaurav are told to copy-paste. The files were fine and in the right
place; the list describing them was wrong. Nothing uses that list today — which is exactly
why I fixed it now, before Phase 7 starts using it.

### What you need to do

Nothing. No decision for you.

**The thing worth carrying.** Both problems this round were *backups*. A backup sits right
next to the thing it's meant to substitute for, so it's the easiest thing in the world for
it to quietly become the answer. That's true of the day column standing in for the date
range, and it's true of a stale checklist standing in for a decision you made months ago.

## 7n. Google doesn't show us every search — and our report was pretending otherwise

Sixth review, and this one found something more important than the wording problems of the
last few rounds. It's about a number you would have trusted.

### The headline problem: "spend" wasn't spend

Google's search-terms report **does not list every search**. Searches that only a handful
of people made are left out on purpose, for privacy. Those clicks happened. That money was
spent. They're just not in the file.

Our report was adding up the rows it could see and calling the result **"Spend."** And the
"one search took 34% of this campaign" figure was dividing by that same partial number.

Why that matters, with made-up figures:

| | |
| --- | --- |
| What the Neuro campaign actually spent | ₹10,000 |
| What the searches Google showed us cost | ₹6,000 |
| What Google hid (small searches) | ₹4,000 |
| One particular search | ₹3,000 |

Our report would have said: **"this search is 50% of the campaign."**
The truth: **it's 30% of the campaign** — and 50% of the part Google let us see.

That's not a typo-level problem. "One search is eating half this campaign" and "one search
is eating under a third" lead to different decisions about your money.

Nothing was being calculated wrongly. It was being **named** wrongly. So now:

- the figure is called **"reported search-term spend"** everywhere;
- every percentage says **"% of reported search-term spend in [campaign]"**;
- and every report carries a section headed **WHAT THIS FILE DOES NOT CONTAIN**, telling
  you to check the campaign's real spend in Google Ads before acting on any share.

### While fixing that, I found something worse

A real Google download has summary lines at the bottom — "Total: Search terms", "Total:
Other search terms". Our reader had no idea those were footers. It was treating them as
**things patients had typed.**

On a test file where the real spend was ₹450, the tool reported ₹8,900 — Google's own
totals counted as traffic, twice — and it reported that number as complete and reliable.

Fixed. Those lines are now recognised and set aside. And one of them is genuinely
useful: "Total: Other search terms" is Google telling us how much the hidden searches cost.
When it's present we now show you that number. When it's absent — which is normal — we say
"not stated," never "zero."

### It could accept the wrong week

Last round I made the tool check that the export covers seven days. It turns out that isn't
the same as checking it covers **the right** seven days.

Run it on the 18th with an export covering the 8th to the 14th: seven days, only four days
old, nothing looks wrong — and it's the wrong week entirely. Every "up from last week"
comparison you'd make from it would be nonsense.

Now the tool checks the exact dates it should be — yesterday going back seven days — and if
they don't match it prints both: what you gave it, and what it expected.

Related: it now works out "today" using **your account's timezone (Asia/Kolkata)** rather
than UK/global time. For several hours a day those are different dates, which is enough to
flag a perfectly good Friday export as stale.

### It was telling Gaurav to undo your decision — again

You'll remember this one. The competitor blocking list deliberately doesn't cover the Brand
campaign; that was your call. Two rounds ago I stopped the tool raising it as a task.

But the instructions at the bottom of the report still said, about the whole blocking-words
file: *"check whether the list is actually applied in the account."* That file contains both
kinds of row — the "nothing to do" kind and the "worth checking" kind. So a busy Gaurav
reads that line, sees the list isn't applied to Brand, and applies it. Your decision,
reversed, by a sentence.

I removed the false task from the spreadsheet two rounds ago and then recreated it in the
prose. The instructions now split explicitly: one kind says **do not investigate, do not
change which campaigns the list covers**; the other gets the check-this-first sequence.

### One smaller thing

The report claimed "every row says REVIEW" — meaning the tool never declares anything
definitely wrong at this stage. That was untrue in our own test data: a search matching a
blocking word you already approved gets marked FLAGGED, correctly, because that's not a
judgement call, it's a decision you already made. The behaviour was right; the sentence
above it was wrong.

### What you need to do

Nothing. No decision for you.

**The thing worth carrying, and it's the big one.** For five rounds we've been making the
tool careful with the data Google gives it. This round found that the tool was also quietly
implying Google gives it *everything*. It doesn't, and it never will.

The rule I've written down for the next part of the project: **ask what a source doesn't
contain before trusting what it does.** Phase 7 reads a different Google file, and it will
have its own holes.

## 7o. The last round — including a mistake I made while fixing the last one

Seventh review, and the reviewer called it the closure gate: fix three things, then the
Friday Watchdog is finished and we stop reviewing it.

### I introduced a bug while fixing a bug, and it's worth telling you about

Last round I built a reader for the summary lines at the bottom of Google's file, so we'd
stop treating them as patient searches. One of those lines is Google saying *"here's what
the searches I hid from you cost."*

I wrote it so that if that figure couldn't be read, it quietly became **₹0**.

So the report could have told you: *"Google states ₹0 of spend on searches it did not
name."* That reads as "nothing was hidden — all good." The truth would have been "we
couldn't read the number."

This is the exact mistake this whole project has spent months stamping out — **unreadable is
not zero** — and I made it inside the very piece of code written to prevent it.

Fixed, and fixed properly: the tool now distinguishes four different situations and says
which one it's in.

| What's in the file | What the report says |
| --- | --- |
| Google printed ₹0 | "it states 0.00" |
| Google printed ₹4,000 | "it states 4,000.00" |
| Google printed something unreadable | "the figure could not be read — UNKNOWN" |
| Google printed nothing | "does not state — which is not zero" |

I've also changed how it's built so this can't come back: the number is now allowed to
be *literally absent* in the code, so a future version can't accidentally treat "missing"
as "zero" without the tests failing.

### The warning reached you but not the next piece of software

Last round I added the caveat "this is reported search-term spend, Google may be hiding
queries" to everything a **person** reads. But each run also writes a small record file
that's meant for **other software** — and that file still just said "spend is complete:
yes."

So a human got the full picture and a program got a bare number with no warning attached.
Phase 7, the next thing we build, is exactly the kind of program that would read that file.
Fixed: the record now carries the same caveat, in the same detail.

While checking it I also found a **false claim in my own notes** — I'd written that the
warning was being saved into a file the Watchdog doesn't actually produce. Corrected in
place rather than quietly deleted, because a wrong sentence in our own records is the same
kind of problem as a wrong sentence in the instructions.

### The rulebook was two versions behind — again

The spec's official list of "what each finding means" still said:

- a competitor search is a leak **whenever it appears** — which we fixed two rounds ago;
- the "one search took 34%" figure is a share of **campaign spend** — which we fixed last
  round.

Both are now corrected there too, with automatic checks so they can't drift back.

I know this keeps happening. The honest explanation is that this project has a lot of
written rules, and until recently the tests only checked the code. Every round we've added
more checks that read the *documents*, and this round adds two more.

### One wording change

I'd written that the tool "knows" Google is hiding searches in every export. Strictly,
Google says it *can* hide low-volume searches — not that it always does in any given week.
So the tool now says **"not provably complete"** by default, and upgrades to **"withheld
activity confirmed"** only when Google's own file proves it. Same practical effect; a more
honest word.

### What you need to do

Nothing.

### One thing still genuinely untested

Everything above was checked against made-up test files. Those prove the tool does what it
claims. They cannot tell us **what Google's real export looks like in your account** — how
much money sits in searches Google won't name.

That needs one real seven-day download compared against your real campaign totals. It's on
the task list to do before the first real Friday run. The reviewer's view, and mine: that
single real check is now worth more than any further round of reviewing made-up data.

### And with that, the Friday Watchdog is done

Seven rounds of review, thirty-odd defects found and fixed. The pattern across all of them,
if you want one sentence: **the tool was usually calculating correctly and describing it
wrongly** — and a description is all you ever see.

Next is Phase 7, the Drift Checker, which watches whether your live account has wandered
away from the plan. It stays blocked until you say to start.

## 7p. The same bug came back wearing a disguise — and that's the last of it

Eighth and final review of the Friday Watchdog. Two things to fix, then it's finished.

### I said this bug was dead. It wasn't.

Last round I told you about the worst mistake I'd made: the tool could turn "we couldn't
read Google's figure for hidden searches" into a confident **₹0**. I fixed it and wrote a
test to prove it was gone.

The test checked what happens when the figure is **gibberish**. It is gone for gibberish.

But Google doesn't write gibberish. When Google has no number for something it writes a
dash — `-` or `--`. And for those, the tool still turned it into **₹0** and reported:

> *"Google states ₹0 of spend on searches it did not name."*

Same bug. Same false reassurance. Different character in the cell.

Why it survived: the dash-means-zero rule is *correct* everywhere else in the file. On an
ordinary search row, `--` genuinely means "no clicks, no cost." I reused that rule for the
summary line at the bottom without noticing that in that one place, a dash means the
opposite — "I'm not telling you."

Fixed properly this time. The summary line now has its own strict rule, and the test covers
**every** way a cell can fail to be a number — blank, `-`, `--`, `—`, and gibberish — rather
than the one I happened to think of.

I'd rather you heard this from me: my first fix was tested against the one input the bug no
longer had. That's the honest description.

### The tool was telling you things the data didn't support

The report carried a standing paragraph on every run saying:

> *"Google omits low-volume search terms. Those searches happened and cost money."*

But internally the tool knew there were two different situations:

- **Google's file proves searches were hidden** (it printed a total for them), or
- **We simply can't prove the file is complete** (it said nothing either way).

The paragraph asserted the first one in both cases. The tool's own records said "unproven"
while its report said "definitely happened."

There was a second version of this too: an unrelated blank cell somewhere else in Google's
summary lines could make the report announce *"the hidden-search figure couldn't be read"*
— for a figure that file never contained at all.

Both fixed the same way: there's now **one** place in the code that works out what a given
week's file actually proves, and the report, the dashboard, the warning and the record file
all print that same sentence. Not four compatible sentences — the identical one, and there's
a test that checks they match character for character.

### And the rulebook, one last time

The spec still named an old finding we deleted five rounds ago. Corrected, with a check so
it can't return.

### What you need to do

Nothing.

### What's actually left

**One real download.** Everything across eight rounds was checked against made-up test
files. Those prove the tool does what it claims. They cannot tell us what Google's real
export looks like in *your* account — whether it even includes that "hidden searches" line,
what format it's in, or how much money sits in searches Google won't name.

That single real check is now worth more than any further round of reviewing invented data.
It's on the list for before the first real Friday run.

### The Friday Watchdog is finished

Eight rounds of review. Roughly forty defects found and fixed. If you want the whole thing
in one sentence: **the tool was almost always calculating correctly and describing it
wrongly** — and a description is all you ever see.

Two habits came out of it that I'll carry into the rest of the project:

1. **Unreadable is never zero.** A missing number and a zero are different facts, and the
   difference is exactly the one that costs money.
2. **Work a fact out once, print it everywhere.** Every time two files described the same
   thing in their own words, one of them eventually lied.

Next is Phase 7, the Drift Checker — the program that watches whether your live account has
wandered away from the plan. It stays blocked until you say to start.

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
