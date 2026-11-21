# Project handoff — 2026-11-21

## Current state
**VM1 PILOT AUTHORIZED 2026-11-21.** The architecture is approved as a *design*, and the user explicitly authorized local disposable VM1 pilot work: **one ICP, 30–40 US companies, no Gmail, $0 paid-API spending**. No pilot implementation or API use was reported before this approval. No Phase 1, expanded VM1, sending, or paid API usage is authorized.

## Product goal
A configurable, quality-first B2B prospecting and outreach SaaS. The customer specifies their business and ideal customer profile (ICP). The engine discovers companies, researches cited evidence, ranks and explains fit, identifies public decision-makers when possible, and drafts evidence-grounded outreach for human approval. Sending, pipeline, billing and account infrastructure come later.

## Directions expressed by the user
- Build for B2B service providers broadly; test initially with independent software/product studios, design agencies and specialist tech consultancies.
- Initial discovery tests focus on US-based prospects.
- Quality, truthfulness and inspectable evidence over high lead volume.
- Eventually use web discovery plus permitted licensed data and user-provided CSV/URLs.
- Gmail send-only in eventual MVP, manual reply marking, Outlook deferred. No autonomous sending.
- Sending beta starts US-first subject to compliance review; UK/EU blocked pending review.

## Architecture design (approved 2026-11-21; not implementation authority)
The Phase 0 review v2 proposes Next.js, React, TypeScript, PostgreSQL, modular monolith, durable background jobs; source-supported/corroborated/user-verified/inferred/unknown claim levels; at-most-once Gmail sending with an explicit `unknown` outcome; provider adapters with transient output by default.

## Initial VM1 pilot authorized; expanded VM1 still proposed
Run a disposable local validation **before Phase 1**. Only test discovery from an ICP, website research, evidence, scoring, public decision-makers and unsent drafts. No SaaS UI, authentication, billing, Gmail or real sending. Start with 30–40 companies under one ICP, then expand to three test seller profiles and ~150 companies. Suggested $10 checkpoint and $50 overall ceiling are **not permission to spend**. See `docs/PROPOSED-VM1-REVISIONS.md`.

## Important blockers
- Architecture approved **as a design**, initial VM1 local pilot authorized. Later VM1 expansion, spending and Phase 1 require separate approvals.
- Provider retention/display/commercial-use rights are unresolved (Exa, Brave, Tavily, Hunter, Apollo).
- Second independent human labeler has not been assigned.
- Original full PRD has not been exported; `docs/PRODUCT-BRIEF.md` is a summary, not verbatim PRD.
- Both Phase 0 **text extracts are committed** in `docs/reviews/` (`phase0-v1-extracted.txt` and `phase0-v2-extracted.txt`). The original PDF files are **not** committed.

## Cross-account handoff received — 2026-11-21

A subsequent Claude account read a ZIP of this repository and reported reviewing the six key project documents plus both extracted Phase 0 reports. The user pasted its session summary into ChatGPT. **This section reflects that pasted summary, not a verbatim copy of the Claude-generated HANDOFF.md artifact.** That account reported no GitHub write access, no implementation, no API calls, and no spending.

### Issues identified by that account — still unresolved
- Budget conflict resolved for the initial pilot: **$0 paid API spending authorized**. The v2 $100 proposal and later $10/$50 suggestions remain **unapproved**.
- Sending scope resolved for the initial pilot: **no Gmail or sending**. Phase 0 v2's Gmail tests E/F are deferred until an email-sending milestone is specifically authorized.
- Discovery and qualification test thresholds differ between the v2 report and proposed revisions; user must set final gates.
- Provider candidates conflict: v2 rules out Tavily, while later review recommends re-evaluating its current terms and use restrictions. No provider rights are confirmed.
- Repo visibility: the repository has been made **public** to help another account access it, but that did not unblock the other account's GitHub web fetcher. GitHub must be explicitly connected there or the files attached as ZIP. Consider restoring private visibility if public access is unnecessary.

### Next milestone decision sequence
1. **Completed:** Architecture approved as a design, and the first VM1 local pilot (one ICP, 30–40 companies, no Gmail, $0 paid APIs) is authorized.
2. **Now:** Build/test only the first local pilot, one frontend-studio ICP; preserve provenance, distinguish genuine automated discovery from any hand-curated candidates, and report blockers if free permitted discovery is unavailable.
3. **Later:** Separate approval required for full VM1 expansion, final quality gates, second human labeler, any budget >$0, Phase 1, Gmail and production deployment.

### Cross-account collaboration note
The other account could inspect a ZIP but could not read or write GitHub directly. At the end of future sessions, ask Claude to return the changed Markdown file or ZIP when its GitHub integration is unavailable. ChatGPT's connected GitHub tools can apply those edits after reviewing the exact file content; do not assume a file was committed merely because Claude said it drafted one.

## Fast path to execution (2026-11-21)
Read `docs/VM1-START-HERE.md`: architecture A is approved *as a design*, and initial $0 paid-API VM1 pilot B is authorized. **Begin the local VM1 prototype, not Phase 1.** Confirm provider rights and do not incur any API cost.

## VM1 pilot implementation status — 2026-11-21 (Claude Code session)

**Prototype implemented on branch `vm1-pilot`, code in `pilot/`. The discovery test has NOT succeeded: no real companies were discovered or evaluated. There are no pilot findings, no relevance numbers, and no go/no-go basis yet.**

### Built (all stdlib-only Python, $0 paid API, no Gmail/sending code)
Keyless discovery adapters (Wikidata SPARQL, OSM Overpass behind `--ack-overpass-terms`, manual CSV labelled `manual`, synthetic fixture); canonical-domain dedup; SSRF-safe polite fetcher (IP pinning, robots.txt, delay, size cap, off-site redirect refusal); HTML parser (no mailto/tel harvesting); evidence extraction with levels and verbatim-excerpt re-verification; deterministic scoring with hard exclusions and listed unknowns; first-party decision-maker extraction; unsent deterministic drafts with lint; report generator with denominators and human-label ingestion; fail-closed paid-API guard. See `pilot/README.md`.

### Tested (real results)
- `python3 -m unittest discover -s tests -t .` in `pilot/`: **82 tests pass** (offline). Covers dedup, exclusions, evidence classification, unsupported-claim omission, no guessed contacts, no sending/paid-client imports, fail-closed behavior, SSRF/robots, an end-to-end synthetic run, and the socket transport against a loopback server.
- Bug found by these tests and fixed: decision-maker titles in uppercase (e.g. "CTO") were never matched.
- A synthetic offline run works end to end. **It uses fictional `.example` data and proves only that the pipeline runs; it says nothing about discovery or ICP fit.**

### Blocker (exact)
Live discovery could not run in the Claude Code sandbox: DNS does not resolve and the egress proxy returns 403 on CONNECT for `query.wikidata.org`, `overpass-api.de`, `en.wikipedia.org` and `www.example.com` (only api.github.com is reachable). Recorded by the pipeline itself in `pilot/reports/2026-11-21-live-attempt-sandbox-blocked.md` (0 candidates, $0). Not routed around.
Consequences: (1) the real-network path (`PinnedTransport` against real TLS hosts, real robots.txt, real Wikidata/Overpass responses) is **untested against the internet**; (2) the Wikidata SPARQL query and Overpass query have never been run, so their result quality and whether Wikidata returns enough US studios with websites are unknown (thin coverage is expected); (3) Wikidata class ID `Q1058914` ("software company") could not be verified by me; the adapter verifies its English label at runtime and aborts if wrong; (4) Overpass usage requires the user to accept its public-instance policy via `--ack-overpass-terms`; I did not ack it on the user's behalf.

### Next action (user, on a normal internet connection)
1. `cd pilot && python3 -m unittest discover -s tests -t .`
2. `python3 -m vm1 run --sources wikidata` and read `runs/<id>/report.md`. If fewer than 30 US studios come back, add `--ack-overpass-terms --sources wikidata,openstreetmap` if you accept the Overpass policy, or report that free discovery is insufficient.
3. Fill `labels_template.csv` yourself (relevant y/n, us_based, decision_maker_correct), then `python3 -m vm1 report --run runs/<id> --labels labels.csv`. No relevance claim should be made without these human labels.
4. Review first-party-site terms of use for any site you research before using the output; robots.txt is honoured, ToS is not machine-checked.

### Not done
No real-company run, no labels, no top-20 precision, no decision-maker accuracy, no timing on real fetches. Gates in `docs/VM1-START-HERE.md` remain unmeasured. No decisions were changed in `docs/DECISIONS.md`.

### Commits
Branch `vm1-pilot`; see `git log` (latest commit recorded in the push). No PR opened.

## Instructions for the next account
Read all planning files and the original Phase 0 reports when available. Restate agreed choices separately from proposed revisions. Do not code or incur costs without explicit permission. Finish the session by updating this file with exact work done and commit/PR links.

## Issue #2 quality remediation — status update (2026-11-21; supersedes older VM1 status above)

**The earlier statement that the pilot has not discovered any real companies is outdated.** The user ran a baseline live Wikidata pilot on their Mac, run `20261121T150320Z-live`, and supplied its report excerpt. The baseline completed with 500 raw Wikidata results, 266 after canonical-domain filtering, 40 evaluated companies, 33/40 successful homepages and 30/40 successful homepage-plus-secondary research. It produced 12 excluded, 24 weak, 4 possible, **0 strong**, 3 unsent drafts, and reported **$0.00** paid API spend. No human relevance labels were supplied, so the benchmark is **not** a claim of acceptable precision.

**Issue #2 code implemented, pushed, but not yet validated live.** On `vm1-pilot`, implementation commit `74b95a26b4234463e4a21ec2cd436c8287c1ba31` and handoff commit `724f69663328d7b7f068e9ff701edca2673751dc` cover conservative company-type gating (agency/studio vs SaaS vendor/enterprise/unclear), stronger self-attribution for employee counts, role attribution for decision-makers, contextual checks for client-facing services, stricter scoring, and Wikidata record-based prequalification. There are 42 new regression tests; the prior implementing agent reported **124/124 offline tests passing**. No new live run was completed in that agent's environment, and the baseline JSON artifacts are only on the user's Mac.

**Files of record:** Read `docs/ISSUE-2-HANDOFF.md` and `docs/VM1-QUALITY-REMEDIATION.md` for exact implementation status, reconstructed before/after examples, remaining risks, and baseline-labeling/live-rerun steps. `pilot/README.md` now summarizes these behaviors. These sections supersede the older “82 tests / no live companies / live networking untested” statements in this document; historical notes are retained for traceability.

**Immediate next steps:**
1. On the user's Mac, preserve `pilot/runs/20261121T150320Z-live` unchanged, copy it for reporting, and manually label the baseline top 20 before any new live test.
2. Pull `vm1-pilot`; run `cd pilot && python3 -m unittest discover -s tests -t .` and `python3 scripts/issue2_before_after.py` locally. Record the actual outputs; do not replace evidence with the prior agent's assertion.
3. Run Wikidata-only live pilot with verified TLS certificates; inspect the enriched SPARQL query's response or fallback, `discovery_coverage`, `selection_priorities`, company-type classifications, evidence attribution, weak/unclear volume and the true relevance of the ranked set. The enriched SPARQL query and its ordering were not previously tested live.
4. Human-label the updated run's top 20, compare against the baseline, and decide whether a generic software-company Wikidata source adequately serves the targeted independent agency/studio ICP. If not, report inadequate coverage instead of manufacturing a successful result.
5. Reachability (baseline 33/40) remains unaddressed; do not bypass robots.txt, SSRF protections or TLS. The exact Claude-generated docs drafts from another account were not available to this update; this entry was authored from the committed Issue #2 handoff and remediation documents.

**Still outside scope:** Phase 1, Gmail/SMTP/sending, paid APIs, and Overpass without explicit usage-policy acknowledgment. Keep `vm1-pilot` separate from `main`.
