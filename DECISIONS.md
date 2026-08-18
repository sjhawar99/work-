# DECISIONS.md

Locked implementation decisions. Each was ambiguous in the specification and has now been
resolved by the account owner. Codex MUST NOT re-infer any of these.

Encoded in `config/rules.yaml`, `config/workbook_schema.yaml` and the sections of
`docs/CODEX_BUILD_SPEC.md` referenced below.

| ID | Decision | Spec | Config |
| --- | --- | --- | --- |
| A1 | The four-sheet workbook is the only workbook | §4.1–4.2 | `workbook_schema.yaml` |
| A2 | ₹62,000 / 5 campaigns / 9 ad groups / `apexhospitals.com` are Stage-1 invariants | §9.3 | `rules.yaml → account` |
| A3 | `Modified Broad` → `Phrase` + warning; `Broad` blocks the build | §9.4 | hard-coded (§8.4) |
| A4 | Hybrid negative hierarchy, scope-aware collisions | §9.5 | `rules.yaml → negatives` |
| A5 | One default call asset, most-specific-wins overrides | §9.6 | `rules.yaml → call_assets` |
| A6 | Landing-page reachability is a blocking check; `UNKNOWN` ≠ `PASS` | §9.6, §10.5 | `rules.yaml → landing_pages` |
| A7 | Weekly manual search-terms export, Fridays | §13.1 | `rules.yaml → watchdog` |

---

## A1 — There is one workbook, and it has four sheets

```
APEX_Google_Ads_Operating_System_v1.1.xlsx
  01 ACTIONS
  02 BUILD
  03 KEYWORDS
  04 DAILY
```

The eleven-area structure — Setup, Campaign Blueprint, Keyword Map, Ads, Landing Pages,
Extensions, Negative Keywords, Tracking, Budget, Search-Term Monitor, Review/Sign-off —
is the **software's conceptual architecture**. It tells the implementation what
capabilities to build. It does not say "look for eleven Excel tabs", and doing so would
mean debugging a workbook that has never existed.

Each capability lives inside one of the four real sheets; the mapping is in spec §4.2 and
`config/workbook_schema.yaml`.

## A2 — Stage-1 invariants

| Setting | Value |
| --- | --- |
| Monthly budget | ₹62,000 exactly |
| Campaigns | 5 |
| Ad groups | 9 |
| Domain | `apexhospitals.com` / `www.apexhospitals.com` |

The compiler fails if any of the first three does not match. Landing pages must resolve
under the allowed domains unless explicitly whitelisted in
`landing_pages.extra_allowed_domains`.

These are not waivable. **This overrides the earlier draft**, where an action-item row
could waive the campaign and ad-group counts. The waivable-rule list is now empty
(spec §9.9): changing an invariant is a reviewed change to `config/rules.yaml`, not a row
somebody adds to a spreadsheet on a deadline.

## A3 — Legacy match types

```
IF match_type == "Modified Broad":
    normalized_match_type = "Phrase"
    warn("LEGACY_MATCH_TYPE_NORMALIZED",
         "Modified Broad is discontinued. Converted to Phrase.")

IF match_type == "Broad":
    BLOCK BUILD
```

Broad Match Modifier was retired by Google: legacy BMM keywords behave as Phrase, and new
BMM keywords cannot be created. Normalising is therefore correct. An actual Broad positive
is a different thing and still violates Stage-1 rules.

Keeping the two paths separate means legacy nomenclature in the workbook does not break
the compiler, while a real Broad keyword cannot ride in behind a "we normalise match
types" rule.

The mapping is **hard-coded in Python, not config** (spec §8.4), so no YAML edit can ever
point it at `BROAD`. Severity is WARNING, not INFO, so it appears in the report body.

Reference: [About changes to phrase match and broad match modifier](https://support.google.com/google-ads/answer/10286719)

## A4 — Hybrid negative architecture

Preserve the `Scope` field. Do not flatten everything to campaign negatives.

```
ACCOUNT
├── ACCOUNT_JUNK
└── OUTSIDE_GEO

SHARED CAMPAIGN LISTS
├── ROUTE_BRAND
├── ROUTE_COMPETITORS
├── STAGE1_HOLD_COMPARISON
├── STAGE1_HOLD_ACTION
└── STAGE1_HOLD_URGENCY

CAMPAIGN-SPECIFIC
└── GENERIC_EXCLUDE_SPECIALTY

AD-GROUP-SPECIFIC
└── ORTHO_PROVIDER_TO_KNEE
```

Better than duplicating a hundred negatives five times — not least because one of the five
copies always goes stale.

**Consequence for the collision engine:** a negative is not dangerous because it could
block some positive somewhere in the account. It is dangerous when it blocks a positive
**in a place where that negative actually applies**. For a shared list, that means
resolving the list's `applies_to` campaigns *first*, then checking overlap. Scope-blind
checking produces a wall of false BLOCKERs, and a wall of false BLOCKERs teaches everyone
to stop reading the report. Full algorithm in spec §9.5.

References: [account-level negative keywords](https://support.google.com/google-ads/answer/11396330),
[negative keyword lists](https://support.google.com/google-ads/answer/2453987)

## A5 — Call assets

One default number for Stage 1, with optional overrides:

```yaml
call_assets:
  default:
    country: IN
    number: REQUIRED
    schedule: REQUIRED
  overrides:
    campaigns: {}
    ad_groups: {}
```

Nine ad groups do not imply nine phone numbers. If a specialty later gets a properly
staffed coordinator line, it becomes a campaign override:

```yaml
overrides:
  campaigns:
    "MLN | Search | Nephro | Jaipur":
      number: "+91…"
      schedule: "…"
```

Resolution is most-specific-wins — ad group, then campaign, then default — which is how
Google resolves call assets across levels. `AD-006` requires every ad group to *resolve*
to an asset, not to declare one.

Reference: [About call assets](https://support.google.com/google-ads/answer/2453991)

## A6 — Landing-page checking is blocking

Per destination URL:

```
 1. Parse URL                    7. Cap redirect depth
 2. HTTPS required               8. Final status must be 200
 3. Domain must be allowed       9. Final URL still on an allowed domain
 4. GET request                 10. Retry with GoogleAdsBot user agent
 5. Timeout ~10s                11. Record latency
 6. Follow redirects            12. Record final URL
```

Three outcomes:

```
PASS      /google/neurologist-jaipur         200   1.23s
BLOCKER   /google/knee-replacement-jaipur    404
BLOCKER   /google/dialysis-jaipur            redirected to unrelated domain
UNKNOWN   /google/apex-jaipur                network validation could not complete
```

**`UNKNOWN` does not equal `PASS`.** If URL validation cannot complete, no `READY`
deployment build is produced — the run ends as `DRAFT`, quarantined and marked
`DO_NOT_IMPORT`, exit code 6 (spec §10.5).

**This overrides the earlier draft**, which let `--no-network` produce a normal passing
build with a "URL checks skipped" note. Fail-closed here is annoying for about twelve
seconds and then saves us from uploading ads to a page the web team renamed on Wednesday
afternoon.

Reference: [Destination not accessible](https://support.google.com/adspolicy/answer/16428223)

## A7 — Weekly operating rhythm

```
MONDAY    Siddhant + Gaurav — efficiency review
          Qualified / Appointment / OPD
          budget and bidding decisions if warranted

FRIDAY    Gaurav — Google Ads search-terms export, previous 7 days
          → input/search_terms/
          → run Watchdog
          → review routing / junk / concentration
          → approved changes into 03 KEYWORDS and 01 ACTIONS
```

v1 is a manual export. Google Ads API ingestion is a later phase and **must not block
v1**. Reliable software a human triggers on Friday comes before an autonomous process
poking Google's API at 3 a.m. — which is simply a new category of surprise.
