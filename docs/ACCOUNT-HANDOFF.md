# Account handoff — Prospecting SaaS / VM1 pilot (written 2026-11-22)

**Read this first.** It says exactly what exists, what is verified, and what is NOT done. Nothing here authorizes
Phase 1, Gmail/sending, paid APIs, billing, auth or a SaaS UI. Those remain unapproved (see `CLAUDE.md`).

## 1. Where things stand (one paragraph)
Issues #1–#4.1 are complete and pushed. **Issue #5 (configurable ICP foundation) is STARTED BUT INCOMPLETE** on branch
`vm1-pilot-issue5-icp-foundation`, branched from `vm1-pilot-issue4-stabilization` @ `516c9f4`. The policy schema, the
policy-driven qualification engine, policy-driven page selection and the universal fact catalog are written and the
existing 194 tests still pass. Pipeline/CLI wiring, the two example policies, fixtures, all new tests and docs are NOT
done. Do not treat Issue #5 as finished.

## 2. Project overview
- **Eventual product:** a multi-industry prospecting SaaS: configurable customer profiles (ICPs) drive discovery,
  evidence-backed company research, transparent scoring, publicly named decision-makers and **human-reviewed, unsent**
  outreach drafts.
- **VM1 today:** a disposable, local, stdlib-only Python pilot (`pilot/vm1`, Python 3.13) for ONE ICP: US independent
  software/product studios needing React/Next.js/TypeScript frontend help. It is not a SaaS, has no UI, no auth, no billing.
- **Hard constraints:** $0 paid-API usage (fail-closed guard), no Gmail/sending code path, no fabricated companies/people/emails/
  results, no prohibited scraping, Overpass only with `--ack-overpass-terms`, third-party provider data not persisted/
  redistributed, never auto-send.

### Pipeline and entry points
`discovery -> canonical dedup -> prequalify ordering -> own-site research (PoliteFetcher) -> evidence extraction ->
verbatim re-verification -> classification/score -> decision-makers -> unsent drafts -> artifacts/report`.
CLI (`cd pilot`): `python3 -m vm1 run|synthetic|capture|replay|report` (see `vm1/cli.py`).
Modules: `discovery, canon, prequalify, fetch, netsafe, guard, pageselect, htmlparse, context, evidence, people, score,
drafts, pipeline, report, snapshot, fixture, cli`; new on the Issue #5 branch: `facts, policy`.

## 3. Completed work (all pushed)
| Branch | SHA | Contents |
|---|---|---|
| `main` | `6c9bb37` | docs/architecture only |
| `vm1-pilot` | `4e67181` | Issues #1–#2: VM1 pilot, SSRF-safe fetcher, evidence levels, company-type gate, size/people/service attribution |
| `vm1-pilot-issue2-alt-wip` | `055180b` | abandoned parallel Issue #2 attempt; reference only, **do not merge** |
| `vm1-pilot-issue3` | `793454e` | Issue #3: false vendor-signal fixes, client-service offering recognition, weak "consulting engagements" identity |
| `vm1-pilot-issue4` | `42077f0` | Issue #4: ICP-aware secondary-page selection (`pageselect.py`) |
| `vm1-pilot-issue4-stabilization` | `516c9f4` | Issue #4.1: canonical URL dedup, agency-development page slugs, own-product attribution, offline snapshot capture/replay |
| `vm1-pilot-issue5-icp-foundation` | see section 5 | Issue #5 WIP checkpoint |

Reports: `docs/ISSUE-2-HANDOFF.md`, `ISSUE-3-REPORT.md`, `ISSUE-4-REPORT.md`, `ISSUE-4.1-REPORT.md`, `VM1-QUALITY-REMEDIATION.md`.

Capabilities in place: keyless discovery (Wikidata SPARQL; Overpass gated); robots/SSRF/DNS-pinning/TLS/size/rate-limit
safe fetching; ICP-aware page selection with a 4-page secondary budget; evidence extraction with levels
(source_supported / corroborated / user_verified / inferred / unknown) and verbatim-excerpt verification; first-party
attribution (testimonials, docs, bios, own-product wording rejected); transparent additive scoring (strong>=65,
possible 40–64, weak<40, **uncalibrated**); qualification gate (only `agency_studio` can exceed weak; vendor/enterprise/
staffing excluded); publicly named decision-makers; unsent drafts with lint; capture/replay with redaction and staleness checks.

## 4. Validation evidence — what is and is not proven
- **Offline tests (194 passing):** prove rules and machinery on fictional `.example` fixtures. NOT lead quality.
- **Live baseline run `20261121T150320Z-live`:** 500 raw, 266 after dedup, 40 evaluated, 33/40 reachable; 12 excluded /
  24 weak / 4 possible / 0 strong; 3 drafts; $0.
- **Live run `20261121T183844Z-live` (Issue #3 input):** human-reviewed top-20 relevance **5/18 (28%)**; 4 of the 5
  relevant companies were classified weak. This is the only independent quality number and it is poor.
- **Six-company capture/replay (figures as reported in the Issue #5 brief; I did NOT reproduce them):** Five Quantum Bits
  agency_studio/possible/59; Ortem Technologies agency_studio/possible/45; Epic Design Labs unclear/weak/25 (its agency
  page was eligible but skipped by the page budget); Telos Labs unclear/weak/20; Interline unclear/weak/20; Velvet
  Disruption unclear/weak/20 (Telos and Velvet show no recognized evidence even after relevant pages were fetched).
- **Known false negatives (keep as limitations, never fix by per-company hacks):** Epic, Telos, Interline, Velvet.
  Velvet's cause is unknown (absent evidence vs selection vs extractor rejection).
- **Replay is not validation:** replay stamps `counts_as_fresh_discovery=false` and `counts_as_independent_live_result=false`.
  No live improvement has been claimed since the 28% run. A fresh networked run plus human labeling is still required.
- This sandbox has no outbound network (proxy 403), so nothing live can be run here.

## 5. Current state of the repo (exact)
- Branch: `vm1-pilot-issue5-icp-foundation` (remote name identical). Base: `516c9f4`. `vm1-pilot-issue4-stabilization`
  is untouched at `516c9f4`. The final SHA is reported in the hand-off message / `git log -1`.
- Tests: `cd pilot && python3 -m unittest discover -s tests -t .` -> **Ran 194 tests, OK**. There are **0 new Issue #5 tests**.
- Spot check only: the new engine matched the frozen legacy `score.py` on 4 hand-built evidence sets. This is NOT the
  full differential test and must not be cited as proof of equivalence.

### Issue #5 — implemented in the checkpoint commit
- `pilot/vm1/facts.py` (new): registry `CLAIM_TYPES`, `SERVICE_TAGS`, phrase tables for new fact families
  (local-service signals, storefront signals, platform/email/loyalty/intake capabilities, service lines, marketing-agency and
  AI-consultancy identity regexes).
- `pilot/vm1/policy.py` (new): schema v1 dataclasses, strict validator (unknown keys, unknown claim types, ranges,
  unreachable tiers, unsafe page-selection hints), `load_policy` (v1 dict/file, or legacy flat file -> baseline +
  overrides), `baseline_policy()`, `summarize()`, content `digest`.
- `pilot/icp/frontend-studio.json`: rewritten into schema v1 (same id `frontend-studio-us-v1`), with every label string
  copied from the old code so output stays identical.
- `pilot/vm1/score.py`: generic `qualify_company(evidence, dms, policy, ...)`; `score_company` and `classify_company` are
  compatibility wrappers over the baseline policy; `ScoreResult` gained `policy_id`, `policy_version`, `criteria`;
  `explain_verdict()` renders evidence-cited criteria. Intentional naming change: size hard-exclusion rule is
  `size_over_{hard_max}` (identical `size_over_250` at the default).
- `pilot/vm1/pageselect.py`: tokens, extra path synonyms, slot order and the `<x>-development-agency` slug heuristic now
  come from `policy.page_selection`; shared safety sets (editorial/legal/docs/pricing paths, same-site, dedup) stay fixed.
  `classify_link/rank_candidates/plan_selection` take an optional policy config (default = baseline).
- `pilot/vm1/evidence.py`: new service tags (`home_services, healthcare_practice, professional_services`) and
  `_catalog_facts()` appended LAST so legacy evidence order is unchanged.
- `pilot/tests/reference/legacy_*_516c9f4.py`: frozen copies of score/prequalify/pageselect/evidence/people from `516c9f4`
  for differential tests (not yet used by any test).

### Issue #5 — NOT done (do these next, in this order)
1. `vm1/prequalify.py` still has the hard-coded software-agency regexes (a rewrite was interrupted and **not applied**).
   Planned: `Prequalifier` built from `policy.prequalify` terms (`outsourc*` wildcard), keep `coverage()` key names.
2. **Wire the pipeline.** `pipeline.research_company` still reads `icp.get("size_band")`/`size_hard_max` from a dict and
   calls `score_company(...)` without the policy; `RunConfig.icp`, `rank_candidates/plan_selection` calls,
   `order_pool/coverage`, the manifest (`icp_id` + policy version + digest), `drafts_enabled` gating and `snapshot.capture`
   (page-superset must use the policy(ies) in play) all need to take an `IcpPolicy` via `load_policy`. Today it works only
   because the baseline defaults equal the old values; any other policy would be silently ignored. Filter
   decision-makers by `policy.decision_makers.role_classes` is already done inside the engine.
3. CLI: `--icp` should go through `load_policy` (legacy flat files must still work); add `validate-icp` and a
   `requalify` command that re-scores stored `companies.json` evidence under another policy without refetching.
4. Two example policies (fictional sellers): `icp/ai-automation-service-businesses.json` (targets US local/professional
   service businesses; identity = >=2 distinct `company_type:local_service_signal`; capabilities = service lines +
   `capability:customer_intake`; exclusions = vendors, software studios, AI consultancies, staffing, enterprise;
   `drafts.enabled=false`) and `icp/ecommerce-marketing-agency.json` (targets ecommerce companies; identity = >=2 distinct
   `company_type:storefront_signal`; capabilities = platform/email capture/loyalty; competitor exclusion
   `entity_type:marketing_agency`; `drafts.enabled=false`; custom `slot_order` and `extra_segments`).
5. Fictional offline fixtures (`.example` hosts) with match / non-match / ambiguous companies per profile, plus companies that
   are relevant to one ICP and irrelevant to another (needs `FakeTransport` support for inline `html` or static page files).
6. Tests: (a) differential tests vs `tests/reference` (score over randomized evidence sets compared ignoring the new
   fields and comparing `type_evidence_ids` exactly; pageselect on a link corpus; prequalify; legacy-claim evidence on
   existing fixtures); (b) policy validation failures; (c) same evidence -> different verdicts per policy;
   (d) replay-based policy switching; (e) policy-independence of extraction; (f) catalog completeness (every emitted claim
   in `CLAIM_TYPES`, `SERVICE_PATTERNS` keys == `SERVICE_TAGS`); (g) `TIER_*` constants equal the baseline policy.
7. Docs: `docs/ICP-FOUNDATION.md` (architecture, schema, backward compatibility, limitations, how to add an ICP) and an
   update to `docs/HANDOFF.md`/`pilot/README.md` test counts. Update `docs/DECISIONS.md` only after real user decisions.
8. Report-level explanations: surface `criteria`/`explain_verdict` in `report.py`.

Known design limits to document, not fix silently: extraction only distinguishes US vs non-US; decision-maker title
vocabulary is unchanged (no marketing/operations titles); draft wording is software-specific so new policies disable
drafts; `max_possible_score` validation is a heuristic; fictional fixtures never prove lead quality for any ICP.

## 6. Operational commands
```
git fetch origin && git checkout vm1-pilot-issue5-icp-foundation && git log --oneline -5
cd pilot && python3 -m unittest discover -s tests -t .          # expect 194 OK at this checkpoint
python3 -m vm1 synthetic --out /tmp/vm1-synth                    # offline fictional pipeline run
python3 -c "from vm1.policy import baseline_policy, summarize; print(summarize(baseline_policy()))"
```
Never force-push; do not merge to `main`; one branch/PR per task. Shallow clones make "unpushed commits" hooks misfire:
verify with `git ls-remote origin <branch>` or `gh api repos/Denzel-shato/prospecting-saas/branches/<branch> --jq .commit.sha`;
`gh` GraphQL is blocked here, use `gh api` REST.

## 7. Local-only files the next account cannot see
`pilot/runs/` (live run artifacts, incl. `20261121T150320Z-live`, `20261121T183844Z-live`) and `pilot/snapshots/` (redacted
third-party page copies for the six/seven-company replay) live only on the user's Mac and are git-ignored. Do not
commit, share or recreate them from memory. Re-run capture on the Mac if needed (commands in `ISSUE-4.1-REPORT.md`).

## 8. Do not repeat
Issues #1–#4.1 are done; do not rebuild the pipeline, fetcher, snapshot machinery or page selection. Do not add per-company
(Epic/Telos/Velvet) rules. Do not use `vm1-pilot-issue2-alt-wip`. Do not claim live improvement from fixtures or replay.
