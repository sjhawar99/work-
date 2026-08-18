# CLAUDE.md — how to work in this repo

## Who you are talking to

Siddhant owns this project and the Google Ads account behind it. He is **not** a
developer and has said so plainly. He makes the business decisions; he does not read code.

### Standing rule: always include a "For Siddhant" section

Every substantive reply MUST end with a section headed **"For Siddhant"** that explains,
in plain English:

- what just happened,
- why it matters to the business,
- what he needs to do next, if anything.

Rules for that section:

- No jargon without a plain-English gloss the first time it appears in a reply. "BLOCKER
  (a problem serious enough that the tool refuses to continue)".
- Analogies over abstractions. Recipes, checklists, spell-checkers, safety catches.
- Say what a thing *does*, not what it *is*. "This stops us launching ads pointing at a
  page that doesn't exist" beats "this implements LP-003".
- Never assume he remembers a rule ID, a file name, or a decision code. Re-state it.
- Short sentences. No walls of code in that section.
- Explain trade-offs like a colleague, not a vendor: what we gain, what it costs, what
  could go wrong.
- If he approved something whose consequences he may not have understood, say so plainly
  and explain what he actually agreed to. Do not let a decision slide by unexplained
  because it was technically phrased.

The technical sections above it stay technical — they are for the coding agent and for
review. The "For Siddhant" section is how he stays in control of his own project.

Keep [`docs/FOR_SIDDHANT.md`](docs/FOR_SIDDHANT.md) up to date as the project moves. It
is the living plain-English guide.

## What this repo is

A specification (and later, the code) for software that turns the Apex Google Ads Excel
workbook into safe, validated Google Ads Editor import files, then monitors search terms
and account drift after launch. It never touches the live Google Ads account.

Read [`DECISIONS.md`](DECISIONS.md), then [`AGENTS.md`](AGENTS.md), then
[`docs/CODEX_BUILD_SPEC.md`](docs/CODEX_BUILD_SPEC.md).

## Working agreements

- Develop on the branch named in the task. Commit with clear messages. Push when done.
- Never weaken a guardrail in `AGENTS.md` or spec §18 to make something work.
- If the spec is wrong, say so and stop — do not quietly widen scope.
- Flag honestly when something failed, was skipped, or is still guesswork.
