# Engine #1 (autonomous company discovery) audit — 2026-11-23

Branch `vm1-pilot-issue5-icp-foundation`. Offline work only: no live crawl, no API call, $0. Nothing here is a measured
real-world lead-quality improvement; see "What is and is not proven".

## Limitations found (by adapter)

| Adapter | Limitation | Evidence |
|---|---|---|
| PickAnAgency | Documented API has **no pagination or sort**; `limit` ≤ 25, so 3 queries ≤ 75 records. Last live run: 75 raw → 37 unique domains (heavy overlap and rejections). | openapi.json; `docs/HANDOFF.md` |
| PickAnAgency | Ignored documented fields: `team_size` (1-10 … 500+), `industries`, `rating`, `is_verified`, city. | openapi.json vs `pickanagency.py` |
| PickAnAgency | In US mode, global queries returned non-US records that were then rejected: requests spent for nothing. Documented `country` filter was unused. | code |
| PickAnAgency | Only the first query that returned a domain was kept, so per-query yield and overlap were unmeasurable. | code |
| PickAnAgency | India screen matched only the literal "india"; unknown country passed silently. | code |
| Wikidata | `ORDER BY ?item LIMIT` fills the window with the lowest Q-ids (old, large, listed companies); studios rarely have items or headcounts. | query design |
| Wikidata | SPARQL returns one row per website × headcount; multi-valued items became several candidates and the survivor depended on row order. Dissolved companies not excluded. | code |
| Drupal.org | Candidates had **no record text**, so Engine #2 ranked them on structure/hash alone. Recent-edit order (`sort=changed`), 200 records max, includes vendors, old listings, non-US and marketing agencies. No documented size/services fields. | code; `VM1-STUDIO-DISCOVERY-COMPARISON.md` (1 plausible lead in 100 records) |
| OpenStreetMap | `office=it` also covers repair shops/retail; name-only records; one unordered window; **US only** (cannot serve a worldwide ICP); branch/way duplicates inflated counts; ODbL + acknowledgement required. | code |
| Pipeline | `candidates.json` kept discovery attributes only for researched companies; the rest of a run's pool was lost, so the real 37 could not be re-ranked or benchmarked. | `pipeline.py` |
| Benchmark | No method existed to measure yield per request, unique coverage or labelled precision. | repo |

## Implemented

- **PickAnAgency**: documented `country=United States` in US mode (client screen kept); audit-only metadata
  (`directory_team_size`, `industries`, rating, verified, city) never copied into `employees` (that would become
  source-supported headcount evidence); only the unambiguous `500+` bucket is screened out and counted; per-query yield
  (`yield.per_query`) and every query that returned a domain (`directory_discovery_queries`); India aliases; unknown
  country counted; opt-in `--pickanagency-profile complementary` (third query = `service=Software Development&industry=SaaS`),
  default unchanged.
- **Wikidata**: deterministic per-item merge (largest headcount, smallest website), dissolved companies excluded in the
  enriched query only (the live-proven fallback is untouched), row/merge stats.
- **Drupal.org**: 200-char attributed profile excerpt as `directory_tagline` plus software/marketing identity hints
  (shared `discovery_hints.py`), unknown headquarters counted. One Engine #2 compat test invariant was narrowed
  (Drupal now has text, so specificity ranking may reorder it); ranking code is untouched.
- **OpenStreetMap**: domain dedupe, retail-tagged objects counted and skipped, `description` tag kept, yield stats.
- **`pool.json`** written by every run; **`discover`** command (adapters only, no company site fetched);
  **`discovery-benchmark`** command; fictional fixtures in `pilot/fixtures/discovery_benchmark/`.
- Source decisions are recorded in `pilot/source_catalog.json` → `evaluated_sources`.

Not modified: Engine #2 ranking weights, qualification scores, backfill, evidence extraction, decision-maker code,
robots/SSRF/TLS/rate limits, the `$0` guard, the keyless registry, outreach.

## Benchmark method

`python3 -m vm1 discovery-benchmark --pool ARM=pool.json [--pool ...] [--manifest ARM=manifest.json] [--labels labels.csv] --out DIR`

- Arms are runs you want to compare (e.g. query profiles). Reports yield per request, unique companies, overlap and
  per-query first-seen yield.
- **Automated record tiers** (`record_target_like`, `_mixed`, `_generic`, `_negative`, `_no_text`) come from record
  wording via Engine #2's `record_evidence`. They are *not labels*.
- **Human labels** (`domain,label,labeler,reviewed_on,notes`; relevant / not_relevant / unsure) are the only source of
  precision. Reported over labelled rows with denominator, coverage and Wilson 95% interval; unsure excluded; conflicting
  labels dropped and listed. Without labels the report says precision is NOT MEASURED.
- Tier calibration shows whether a tier predicts human "relevant".
- Fictional input is bannered as not real-world evidence. Deterministic; offline; no network imports.
- Import the real 37-company pool as `--pool previous_37=pickanagency-candidates-rich.json` (flat or `attrs` records are
  accepted); it is gitignored and was not available here.

## What is and is not proven

Proven offline (unit tests): adapter parsing/dedupe/stats, request bounds, no evidence leakage, determinism, benchmark
arithmetic. **Not proven**: that the `complementary` profile, the US country filter, the Drupal excerpt or any change
finds more relevant studios. The fictional fixture numbers demonstrate the format only.

## Smallest live validation (documented, not executed)

All keyless, $0, 6 PickAnAgency requests (≥1.1 s apart, no pagination, no company site fetched):

```
cd pilot
python3 -m vm1 discover --icp icp/frontend-studio-worldwide.json --sources pickanagency --pickanagency-profile legacy --label legacy
python3 -m vm1 discover --icp icp/frontend-studio-worldwide.json --sources pickanagency --pickanagency-profile complementary --label complementary
python3 -m vm1 discovery-benchmark --pool legacy=runs/<legacy>/pool.json --pool complementary=runs/<complementary>/pool.json \
  --manifest legacy=runs/<legacy>/manifest.json --manifest complementary=runs/<complementary>/manifest.json \
  --out runs/bench --labels-template
```
A person then labels the unique companies (at most ~60) in `runs/bench/labels_template.csv` from each company's own public
site, and reruns with `--labels`. Compare human-confirmed relevant studios per request, not candidate count. Optional
single request to size Wikidata's window: a `COUNT` of the same query, to learn whether `ORDER BY ?item LIMIT 500` hides
most of the class.
