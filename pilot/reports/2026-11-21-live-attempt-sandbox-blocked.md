# VM1 pilot report — run `20261121T143240Z-live`

## Verdict
**INCONCLUSIVE / NO-GO for expansion.** Autonomous zero-cost discovery produced 0 raw / 0 evaluated candidates (target 30-40). The discovery test has NOT succeeded; see 'Discovery status' for the exact blockers. Manual/CSV inputs do not count toward autonomous-discovery metrics.

## Scope and ICP
ICP id: `frontend-studio-us-v1`. One ICP, no Gmail, no sending, no paid APIs. Actual paid API spend: **$0.00**. Credentials detected in env but ignored: none.

## Discovery status
- `wikidata` (free_keyless): **blocked**, 0 candidates — **query.wikidata.org: unsafe or unresolvable (host did not resolve)**
  - terms noted: Wikidata Query Service: keyless; send a descriptive User-Agent; keep queries narrow; back off on 429. Data is CC0. (verify before relying on it; license: CC0 (Wikidata))

## Funnel (automation vs manual inputs kept separate)
- raw candidates: 0 (automated: 0)
- after canonical-domain dedup/first-party filter: 0 (rejected: 0; duplicate domains removed: 0)
- evaluated: 0 = automated 0 + manual 0 + synthetic 0
- selection: deterministic hash order, seed `vm1-pilot-1`, cap 40

## Metrics (denominators shown; reference benchmarks are NOT adopted gates)
| Metric | Measured | Reference | Note |
|---|---|---|---|
| Reachable first-party homepages | 0/0 (n/a) | >=95% | robots-blocked: 0; errors: {} |
| Homepage + >=1 secondary page fetched | 0/0 (n/a) | >=80% | no secondary link found: 0 |
| Residual duplicate domains after dedup | 0/0 (n/a) | <=2% | by construction of the key; name-collision review list in manifest |
| Hard-exclusion rules triggered (companies removed) | 0 | 0 violations | rule-based only; independent check needs human labels: {} |
| Excerpt re-verification (verbatim in fetched page) | 0 kept / 0 dropped | 95% supported claims | this checks quoting, NOT whether the page's claim is true |
| Unsupported factual assertions in drafts (lint) | 0 failing of 0 drafts | 0 | automated lint; human review still required |
| Decision-maker named on first-party site | 0/0 (n/a) of eligible | report only | coverage, not accuracy |
| Fabricated/guessed emails | 0 | 0 | no email is collected or generated at all |
| Top-20 relevance | NOT MEASURED (no human labels) | >=70% | top-20 size 0 |

Tier counts: 

## Ranked top 20
_No eligible ranked companies._

## Excluded / ineligible

## Evidence samples (timestamped, short verbatim excerpts)
_No evidence to show._

## Error cases
- evidence items dropped because the excerpt was not re-verifiable: 0
- no homepage fetch errors in this run

## Unsent drafts
0 drafts in `drafts/` and `drafts.json`; every one is status UNSENT_DRAFT, has no recipient email, and uses placeholders for seller identity.

## Time and cost
Elapsed 0.0s ({'discovery_s': 0.0, 'research_s': 0.0, 'drafts_s': 0.0}); HTTP requests logged: 0; **paid API spend: $0.00**.

## Limitations
- Page statements are attribution, not verified truth; sizes/locations may be stale.
- Non-US detection is partial; absence of non-US evidence is not proof of US presence.
- Relevance and decision-maker accuracy need independent human labels; none are produced here.
- Scoring thresholds are arbitrary starting points, uncalibrated.
- Free discovery sources have thin coverage of small studios; coverage is measured, not assumed.
