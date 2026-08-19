"""The Search-Term Watchdog (spec §13).

Weekly, manually triggered, post-launch. Reads a Google Ads search-terms export and the
same workbook, and produces analysis, ranked findings, observations about what approved
negative policy did and did not prevent, and a human actions report. It authors no negative
policy (§13.5, amended). It never touches the account and never modifies the workbook.

Five invariants govern every module here:

1. **Raw term boundary.** Ingest builds a protected `SearchTerm` immediately. No raw query
   reaches an exception, a log, a finding, a dashboard or the actions report.
2. **Keyed identity.** Query handles are HMAC under one stable local secret, so the same
   query recurs under the same ID and a report holder cannot confirm a guessed phrase.
3. **No invented thresholds.** Every Stage-1 threshold is `null`, and `null` means
   rank-and-review. The Watchdog shows the evidence and decides nothing.
4. **Suggestions are not actions.** Every candidate negative goes through the same
   scope-aware collision engine the compiler uses; a conflict becomes `ROUTING_CONFLICT`,
   never an auto-negative.
5. **No workbook mutation.** `--propose-writeback` emits new files. The four-sheet source
   is never written to.
"""
