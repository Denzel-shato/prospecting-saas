# VM1 pilot (disposable local prototype)

Scope: one ICP (`icp/frontend-studio.json`), discovery from the ICP alone, own-site evidence, transparent
scoring, publicly named decision-makers, **unsent** drafts. No Gmail, no sending, no paid APIs, no Phase 1.
Python 3.11+, **standard library only** (no installs).

## Reproduce
    cd pilot
    python3 -m unittest discover -s tests -t .          # 148 tests, offline
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
