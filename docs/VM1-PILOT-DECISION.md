# VM1 pilot decision

**Checkpoint reached on 2026-11-22. Hold expansion and Phase 1.** VM1 demonstrated zero-paid-cost discovery, first-party research, configurable qualification, and unsent drafts. It did not establish enough relevant autonomous leads for the US frontend-studio audience. The evidence supports continued manual outreach from verified leads.

## Evidence

| Measure | Latest autonomous run | Interpretation |
|---|---|---|
| Discovery volume | 500 Wikidata rows, 150 after filtering, 40 researched | Research volume reached the 30–40 target. |
| Top-20 relevance | 3 plausible fits, 13 skips, 4 unresolved in a manual review | 3/16 resolved (19%) versus the 70% reference. Earlier independent review: 5/18 (28%). |
| Reachable homepages | 30/40 (75%) | Below the 95% reference. |
| Homepage plus secondary page | 23/40 (57.5%) | Below the 80% reference. |
| Residual canonical duplicates | 0/40 | At the reference for this run. |
| Decision-makers | 3/20 eligible named, all three displayed employer/title pairs checked | Low coverage. Three matches cannot establish the top-1 or wrong-person benchmarks. |
| Evidence and drafts | 202 excerpts retained, 2 drafts passed lint, zero guessed emails | Verbatim checks and lint do not measure semantic accuracy or independent draft quality. |
| Cost | $0 paid API spend | Zero-cost constraint met. |

Source run: `20261122T085458Z-live`. Labels are outreach-fit judgments, with uncertain rows unresolved. False-strong rate is unevaluable because there were no strong candidates. Hard-exclusion accuracy and independently labeled claim/draft accuracy are unmeasured. The 10-company manual seed test reached 9 homepages and yielded 4 possible matches. The [directory comparison](VM1-STUDIO-DISCOVERY-COMPARISON.md) supports using Vercel manually after checking fit.

## Final discovery check

Ran the existing broad Wikidata SPARQL query and a description-focused variant on the same date. The focused query required English descriptions matching client-service language and excluded companies with a stock exchange statement. After deduplicating the returned website URLs by registrable domain, the broad query returned **500 rows across 153 domains**, and the focused variant returned **51 rows across 15 domains**, before first-party eligibility checks. These counts describe the live query response, separate from the Mac pilot's earlier 150-company pool. Even perfect qualification of the focused sample would fall short of 30 candidates. This measurement covers discovery only.

To reproduce the focused variant, take `WikidataAdapter.build_query(enriched=True)` and replace the optional description clause with:

```sparql
?item schema:description ?desc .
FILTER(LANG(?desc) = "en")
FILTER(REGEX(LCASE(STR(?desc)), "(development|design|engineering|software|digital|product) (agency|studio|consultancy|consulting|services)|custom software|development firm"))
FILTER NOT EXISTS { ?item wdt:P414 ?exchange }
```

## Branch status

All 220 offline tests passed, all three ICPs validated, and the fictional smoke run succeeded. The repo retains one automated baseline and a manual seed route. Qualification now recognizes explicit software offers to client audiences, avoids web-frontend credit from the observed mobile/backend wording, and treats Epic's own-product passage as a mention. The offline suite does not establish post-fix live relevance.

The next implementation milestone requires a discovery source that can supply a repeatable, permissioned studio batch and a fresh labeled run. The current Phase 1 decision is a hold. Keep using the manual directory review and first-party evidence for outreach while that prerequisite is unmet.
