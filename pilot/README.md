# VM1 pilot (disposable local prototype)

Scope: one ICP (`icp/frontend-studio.json`), discovery from the ICP alone, own-site evidence, transparent
scoring, publicly named decision-makers, **unsent** drafts. No Gmail, no sending, no paid APIs, no Phase 1.
Python 3.11+, **standard library only** (no installs).

## Reproduce
    cd pilot
    python3 -m unittest discover -s tests -t .          # 82 tests, offline
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

## Known limits
Scoring thresholds are uncalibrated starting points. Non-US detection is partial. Page statements are attribution, not truth.
