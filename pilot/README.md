# VM1 pilot (disposable local prototype)

Scope: one ICP (`icp/frontend-studio.json`), discovery from the ICP alone, own-site evidence, transparent
scoring, publicly named decision-makers, **unsent** drafts. No Gmail, no sending, no paid APIs, no Phase 1.
Python 3.11+, **standard library only** (no installs).

## Current Issue #5 branch (2026-11-22)

The configurable ICP foundation is implemented on `vm1-pilot-issue5-icp-foundation`, not merged into `main`.
GitHub Actions confirmed **211 offline tests passed**, plus all three policy JSON files validated and a
fictional synthetic pipeline run succeeded. The test results prove local code paths, **not live lead relevance**.
The earlier independent studio-pilot quality result remains 5/18 (28%) human-labelled top-20 relevance.

### New commands

    python3 -m vm1 validate-icp icp/frontend-studio.json
    python3 -m vm1 validate-icp icp/ai-automation-service-businesses.json
    python3 -m vm1 validate-icp icp/ecommerce-marketing-agency.json
    python3 -m vm1 requalify --from-run runs/<old-run-id> --icp icp/ecommerce-marketing-agency.json --out runs

The `requalify` command makes **no network requests**, regenerates no drafts, uses only previously stored
verified evidence, and labels its output as **not fresh discovery**. Historical source evidence may not cover
all claims needed by a different ICP. All policies remain illustrative until human-validated live runs exist.
See `../docs/ICP-FOUNDATION.md` for the schema, limitations, and instructions for adding another industry.
Snapshots and live runs stay local and git-ignored.

## Reproduce
    cd pilot
    python3 -m unittest discover -s tests -t .          # 211 tests as of Issue #5 checkpoint (check CI)
    python3 -m vm1 synthetic                             # offline pipeline check on FICTIONAL data (never a finding)
    python3 -m vm1 run --sources wikidata                # live, keyless, zero-cost discovery
    python3 -m vm1 run --sources wikidata,openstreetmap --ack-overpass-terms   # adds Overpass (see below)
    python3 -m vm1 run --sources wikidata --manual-csv my.csv                  # name,url CSV, labelled MANUAL
    python3 -m vm1 report --run runs/<run_id> --labels labels.csv              # add human labels

Outputs go to `runs/<run_id>/` (git-ignored): `manifest.json`, `candidates.json`, `rejected.json`,
`companies.json` (evidence + score explanations), `drafts/`, `fetch_log.jsonl`, `report.md`, `labels_template.csv`.

## Discovery methods (all free + keyless; paid/keyed names fail closed)
| Source | Status | Notes |
|---|---|---|
| Wikidata SPARQL | implemented | CC0. Expect thin coverage of small studios. Class/country IDs are verified by label at runtime. |
| OpenStreetMap Overpass (`office=it` + `website`, US) | implemented, **needs `--ack-overpass-terms`** | ODbL. Public instance policy: identifying UA, no parallel use, low volume, commercial use should self-host. You must confirm you accept that. |
| Manual CSV | implemented | Always labelled `manual`; never counted as autonomous discovery. |
| Synthetic fixture | implemented | Fictional, offline, tests only. |
Web-search engines are deliberately **not** scraped (terms) and keyed search APIs (Exa/Tavily/Brave) are blocked in the $0 pilot.

## Guarantees enforced by tests
SSRF checks on every URL and redirect hop with IP pinning; robots.txt honoured (5xx/unreachable = skip);
per-host delay; size cap; evidence excerpts must be verbatim in the fetched page; conflicting facts become `unknown`;
decision-makers only from first-party pages, never emails; drafts only from verified evidence, status `UNSENT_DRAFT`;
no mail/paid-client imports exist anywhere in `vm1/`.

## Qualification behavior (Issue #2, 2026-11-21)

The evidence and scoring engine now distinguishes `agency_studio`, `saas_vendor`, `enterprise_software`, `staffing`, and `unclear`. Only evidence-backed agency/studio prospects can reach `possible` or `strong`; ambiguous company types remain weak or require manual review. A `strong` classification additionally requires US evidence, a supported in-band team size and at least two offered target services. This conservative gate may yield few or no strong results.

Service/technology words appearing on a site are not automatically services **offered to clients**: irrelevant references are captured as `mention:*` with no score. Employee counts require unambiguous, present-tense attribution to the company itself; references to client teams, historical figures and ranges remain unknown. Decision-makers require evidence tying the person to the target company, not just a role displayed on its website. Evidence excerpts remain attributed observations, not independently verified truth.

The code includes 42 Issue #2 regression tests, bringing the offline suite to **148 tests** (reported as passing in the implementation handoff). This does **not** establish live lead quality or precision. Full details, root causes, test cases, known false positives/negatives and a live-validation procedure are in [VM1 quality remediation](../docs/VM1-QUALITY-REMEDIATION.md) and [Issue #2 handoff](../docs/ISSUE-2-HANDOFF.md).

### Live pilot status

On 2026-11-21 the user reported a completed baseline run, `runs/20261121T150320Z-live`: 500 Wikidata raw results, 266 after first-party/dedup filtering, 40 researched; 33/40 homepages reachable; 30/40 homepage + secondary; 12 excluded, 24 weak, 4 possible, 0 strong, 3 unsent drafts, $0 paid API spend. This was the **pre-remediation** run. The new company-type gating, prequalification and enriched SPARQL query have **not** been validated against live data, and no independent human relevance labels have been provided.

Preserve and human-label the baseline before another live run. On a Mac with Homebrew's Python/OpenSSL configuration, the previously successful live setup used a valid CA bundle, e.g. `SSL_CERT_FILE=/usr/local/etc/ca-certificates/cert.pem python3 -m vm1 run --sources wikidata` where that file exists. Do not disable TLS verification. Overpass remains opt-in only after reviewing and acknowledging its terms.

## Known limits
Scoring thresholds are uncalibrated starting points. Non-US detection is partial. Page statements are attribution, not truth.

## Weekly prospect review

Use completed live runs from one ICP to build a review queue. Run manual CSV intake separately for each source you want to compare. Each intake CSV uses the existing `name,url` format. Set the run's candidate cap to cover its input batch.

```sh
python3 -m vm1.weekly \
  --batch vercel runs/<vercel-run-id> \
  --batch targeted-search runs/<search-run-id> \
  --history weekly/<previous-week>/review.csv \
  --out weekly/<current-week>
```

Omit `--history` for the first week. Repeat it for every previous review file you want counted. The queue deduplicates canonical domains across current batches and previous skips or fully verified contacts. The first current batch containing a domain gets source credit. Earlier unresolved prospects can appear again.

Edit `review.csv` with `contact`, `skip`, or `needs_research` and record the reason. For contacts, confirm the person's name and role on the company's own site and fill in `verified_person`, `verified_role`, `verified_person_url`, and `outreach_angle`. Suggestions and cited service evidence appear alongside the review fields. Weak candidates remain visible for review.

Use `fit=strong` only for a close match to the ICP. For the frontend-studio campaign, confirm an independent US studio in the target size band with client application work and a clear React, Next.js, or TypeScript frontend fit. In `reason`, record the facts that make the match strong, including size and geography evidence. Add the company-site case study or portfolio URL in `client_project_url`. Use `plausible` for an otherwise promising company with an important unknown, and `weak` for a poor match.

Run the same command again to preserve your edits and regenerate the exports. `ready.csv` includes manually approved contacts with verified person details and an outreach angle. `qualified.csv` contains only the strong fits in that list with a documented reason and first-party client project URL. The summary counts only the qualified export toward the **150–200 high-fit leads per week** target. The command works offline and does not send outreach.

## Automatic studio discovery experiment

The opt-in `drupal_org` adapter screens up to 200 recently edited organization listings through the documented Drupal.org API. It collects organization names and websites with attribution, prioritizes directory hints, and uses the normal first-party crawler for qualification. Directory text, geography, and frontend hints do not become qualification evidence. The default source remains Wikidata.

For a source-isolated test from `pilot/`:

```sh
python3 -m vm1 run --icp icp/frontend-studio.json --sources drupal_org --max-candidates 35
```

For a mixed candidate pool, use `--sources drupal_org,wikidata`. The first source listed retains provenance when the same canonical domain appears in both. Drupal is most relevant to the studio profile. Label eligible companies against the same high-fit criteria before comparing yield.

The first probe retrieved 200 directory records. The adapter extracted 31 distinct candidate domains, six with frontend or headless hints. These are pre-crawl counts. The live pilot in the development workspace could not resolve the API host through VM1's direct transport, so end-to-end qualification and weekly yield remain unmeasured.
