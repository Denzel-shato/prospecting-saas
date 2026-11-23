# Project handoff — 2026-11-21

## Engine #6 recovery review — 2026-11-23

Completion addendum: see `docs/VM1-ENGINE6-RECOVERY-AUDIT.md`. The subsequent
batch adds separate inline people parsing, explicit Person article cards,
cross-card boundaries, local JSON-LD reference resolution, report summary and
research-to-report regressions. Full suite 471 passes; all four ICPs valid.
Fictional comparable evaluation: positives 1/4 -> 4/4, false positives 2/4 -> 0/4.
No live-quality claim. Prior paragraph's remaining implementation work is superseded
by this addendum; real captured-page validation remains pending permission/data.

Rebuilt from remote `f8035e1`; the reported Claude commits c087ac0,
1320160 and f25dddc were unavailable from GitHub. This is independent work,
not confirmation or recreation of those exact commits.

Confirmed and fixed: nested about/team links ranked as low-value details;
About-page leadership links never followed; organisation-prefix collisions;
engineering VPs incorrectly ranked as CEOs; shorter founder titles losing to
engineering titles; malformed JSON-LD type arrays crashing extraction;
escaped Unicode names extracted then dropped by excerpt verification;
explicit conflicting employer ignored under a matching parent organisation.

Added per-company decision_maker_outcome and eligible-company counters;
unknown report entries show the recorded cause or unrecorded for old runs.
An extraction outcome means no attributable person was extracted from fetched
company pages, not proof that an identifiable person was missed.

Validation: 464 offline tests pass (455 baseline), four policies validate,
git diff --check passes. Nine new fictional regression tests. No live requests
or measured real-company coverage improvement. No discovery/ranking/scoring changes.

Remaining: inline span name/title structures and article-based team cards still
need safe structural attribution work; JSON-LD graph references are not resolved.
The original 10-company captured pages were unavailable. Replay those same pages
when available, independently label correct/incorrect names and identifiable
misses, then authorize a bounded live capture only for missing leadership pages.
Do not claim the full Engine #6 audit is complete or coverage improved from these tests.

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

## Issue #3 (branch `vm1-pilot-issue3`, base 4e67181)
Completed: offline evidence-extraction fixes (see `docs/ISSUE-3-REPORT.md`). Changed: `pilot/vm1/evidence.py`, `score.py`, `pipeline.py`, new `pilot/tests/test_issue3_regressions.py`, `pilot/scripts/issue3_before_after.py`. Tests: 148 OK. Blockers: no network here; no live re-run; Velvet cause unknown. Next: fresh live run on a networked machine and human labeling. Not merged to main; no live improvement claimed.

## Issue #4 (branch `vm1-pilot-issue4`, base `vm1-pilot-issue3` @ 793454e)
Completed (offline only): ICP-aware secondary-page selection (`pilot/vm1/pageselect.py`, wired in `pipeline.py`), selection reasons and per-page `text_blocks` diagnostics, 17 new tests, `pilot/scripts/issue4_before_after.py`, `docs/ISSUE-4-REPORT.md`. Tests: 165 OK. Blockers: no network here; real Telos/Epic/Velvet pages unavailable, so no live relevance claim. Open: inspect Epic's `service:web_app` excerpt in a live run (own-product vs client offering, see report). Next: fresh live run on the Mac; compare `secondary_candidates`/`secondary[].text_blocks` for Telos and Velvet; human-label top 20. Not merged to `main`.



## Issue #4.1 (branch `vm1-pilot-issue4-stabilization`)
Done: canonical URL dedup, agency-development slug recognition, own-product attribution, snapshot capture/replay
(`vm1/snapshot.py`, CLI `capture`/`replay`), 29 new tests (194 total, all pass). Blockers: real seven-site capture needs
the user's Mac. Next: run the commands in `docs/ISSUE-4.1-REPORT.md`, compare against `42077f0`, report. Not built: old-vs-new diff script.

## 2026-11-22 checkpoint
Issue #5 (configurable ICP foundation) is STARTED, NOT COMPLETE, on `vm1-pilot-issue5-icp-foundation`. Read `docs/ACCOUNT-HANDOFF.md` first; it lists what exists and the ordered remaining work.


## Issue #5 implementation checkpoint — 2026-11-22

**Branch:** vm1-pilot-issue5-icp-foundation, based on the earlier partial checkpoint b42227e. This branch has NOT been merged to main. The original Issue #4.1 branch remains unchanged.

**Completed in this session:**
- Policy-aware discovery prequalification, candidate selection and descriptive coverage; baseline legacy behaviour checked against frozen implementation.
- Validated active ICP now propagates through the entire pipeline: page selection, size/geography/type scoring, exclusion gates, target roles, historical draft eligibility and manifest policy version/digest.
- Capture and replay accept the active policy; capture continues using the existing network restrictions and replay never accesses the network.
- Added offline validate-icp and requalify CLI commands. Requalification uses stored evidence only, produces no drafts, makes no network calls, records original run provenance, and is explicitly NOT fresh research or an independent quality measurement.
- Added two **fictional** industry policies: automation consultancy targeting local/professional service businesses, and marketing agency targeting ecommerce storefronts. Draft generation DISABLED for both.
- Extended reports with ICP-relative discovery coverage, policy ID/version/digest and evidence-cited criterion descriptions. Added requalification notices.
- Added cross-ICP, offline requalification, baseline scorer and prequalification tests.
- Added GitHub Actions workflow .github/workflows/vm1-tests.yml for offline tests, policy validation and fictional synthetic pipeline, triggered by Issue #5 branch pushes; no paid APIs or external scraping.

**Test evidence:** The user's Mac passed 201 tests following initial integration. GitHub Actions run 45001430418 on commit 10fbcb5 later reported **211 tests in 0.596 seconds, OK**, all 3 example policy validations passed, and the fictional synthetic pipeline succeeded. Documentation-only revisions do not alter behavior. Verify newest branch head and subsequent CI run before treating later changes as tested.

**What these tests do NOT prove:** 28% (5/18) remains the independent live top-20 relevance reference. Neither synthetic tests nor offline replay prove lead precision, decision-maker accuracy across industries, compliant source availability, or positive buying intent. Real matched company identification still needs permitted discovery plus independent human labels. Incomplete extraction for another ICP must remain unknown, never guessed.

**Important source links:** docs/ICP-FOUNDATION.md (schema, usage, limitations), docs/ACCOUNT-HANDOFF.md (historical checkpoint; superseded by this entry for Issue #5 status), docs/ISSUE-4.1-REPORT.md (capture/replay behavior).

**Next Mac validation (without a full crawl):**

    cd ~/prospecting-saas
    git fetch origin && git switch vm1-pilot-issue5-icp-foundation
    git pull --ff-only origin vm1-pilot-issue5-icp-foundation
    cd pilot
    python3 -m unittest discover -s tests -t .
    python3 -m vm1 validate-icp icp/ai-automation-service-businesses.json
    python3 -m vm1 validate-icp icp/ecommerce-marketing-agency.json
    python3 -m vm1 requalify --from-run runs/20261122T065358Z-replay --icp icp/ecommerce-marketing-agency.json --out runs

The old 6-company replay is ONLY on the user's Mac and its data may not include ecommerce signals. Zero matches under another ICP is therefore not a live relevance conclusion.

**Remaining milestone / decisions:** Do not add frontend SaaS, Gmail/sending, paid data, billing or auth without a separate milestone authorization. First validate the code against the user's real snapshots, inspect extraction quality and source coverage for other industries, and expand independent human labeling. Some requested tests (complete randomized differential across all old/new components, independent policy-invariant extraction with factual fixtures) can still be strengthened before treating Issue #5 as fully audited. There is no company-specific hack for Epic/Telos/Velvet, and no claim of live improvements.


### Issue #5 follow-up — deterministic replay CI fix

An automated run at 75becd5 exposed an intermittent test failure: replayed robots-blocked/DNS-failed homepage fetches used the current replay wall-clock timestamp when no original GET response was stored. Repeated replays across a second boundary therefore produced different companies.json output. vm1/snapshot.py now uses the stored capture start time as the deterministic provenance fallback for such failures, and tests/test_issue41_stabilization.py has an explicit failed-page timestamp regression test. No old assertion was weakened.

**Verified:** GitHub Actions VM1 offline-tests run 45001805631 passed **212 tests**, all three ICP JSON validations, and the fictional synthetic pipeline, on code commit b6241265823c83f4d9b4b604ba38cce54e73d1be. This does not change the independent live relevance result of 5/18 (28%) for the earlier studio ICP. Next step on the user's Mac is an offline requalify of an existing saved six-company run; this must not be interpreted as live evidence for other industries.


### Qualification-quality pass (2026-11-22, offline only)
Raw real-run artifacts (`runs/`) are not in the repo or this workspace; patterns came from probes of realistic fictional pages plus documented Issue #3/#4 findings. Changed: `vm1/evidence.py` ("digital product agency/consultancy", "product agency" identity; self-referential hyphenated headcounts "Our 25-person team", "We are a 12-person studio"), `vm1/score.py` (new `ScoreResult.disposition`: disqualified / not_assessable / manual_review / low_fit / qualified; a failed fetch alone is not_assessable, not disqualified), `vm1/report.py` (disposition counts; old runs show `unrecorded`). Thresholds and strong requirements unchanged. Tests: 256 OK incl. `tests/test_qualification_quality.py`. NOT verified: any live precision change; tier names/exclusion for unreachable are unchanged (frozen legacy differential tests).


### Discovery-quality pass (2026-11-22, offline only)
Gap found: Drupal.org candidates carried only boolean hints, so the ICP's vendor/negative terms never applied and a product/hosting vendor profile ("we build our platform, a SaaS...") earned the same +3 client-services boost as an agency. Now `DrupalOrgAdapter` flags `directory_vendor_hint` (own-product/hosting wording AND no agency/studio/consulting noun), withholds the service hint, and `prequalify` applies -3 (research order only; nothing is dropped or loosened). New `yield_stats` (records, geography_rejected, no_website, no_service_wording, vendor_like_no_service_noun, duplicate_domain, frontend_hint, candidates) flows to the manifest discovery status (`yield`) and the report. Tests: 259 OK. Not measured: real Drupal/Wikidata yield; end-to-end manifest rendering of `yield` is covered only by code inspection. Remaining limit: Drupal ordering is last-edited, not relevance (≈1 verified lead in 100 records per docs/VM1-STUDIO-DISCOVERY-COMPARISON.md); Wikidata's "software company" class skews to vendors.


### Decision-maker identification pass (2026-11-22, offline only)
Page selection already targets about/team/leadership slugs (`pageselect.TEAM_SEGS/ABOUT_SEGS`), so the misses were extraction. Reproduced on fictional pages and fixed in `vm1/people.py`: prose self-descriptions ("X is the founder and CEO of <Co>", "I'm X, owner of <Co>", "<Co> was founded by X") accepted ONLY when the named organisation matches the target company; reversed title-then-name cards (not when a name above already owns the title); accented and particle names (José García, Jan van der Berg); titles "Chief Executive", "Founding Partner", "Co-owner" and extra title words ("Founder & Creative Director"); JSON-LD names stored as \uXXXX escapes were silently rejected by the raw-text check. Unchanged: testimonial/quote/client/blog rejection, wrong-org rejection, no emails. Tests: 270 OK incl. `tests/test_people_patterns.py`; 4 ICP JSONs validate. Not measured: any live name-coverage change (the 4/32 Drupal artifacts are not in the repo); bare "Name, Title" on a homepage with no org tie stays unknown by design.


### Live false-negative pass: rehabcreative / 1xinternet / zoocha (2026-11-22, offline only)
Real pages unavailable; patterns reproduced with fictional fixtures (`pilot/tests/test_live_false_negatives.py`). Fixes in `vm1/evidence.py`: "creative/design/interactive agency|studio" (and "brand and web") are self-referential agency identity; a short element whose WHOLE text is a service name ("Software Development", "React development", "Frontend expertise") counts as an offering; navigation/footer service labels count ONLY when a strong agency identity exists elsewhere and no vendor/enterprise signal does (bare "React"/"Frontend" never); "bespoke software/custom builds" recognised; the bare phrase "React development" no longer overrides product-feature wording ("Our SDK supports React development" was a service claim before). Bios, client work, testimonials, docs pages and Drupal-only agencies remain mentions/no claim. Thresholds, strong gate and evidence verification unchanged. Tests 281 OK; 4 ICPs validate. Unverified: the actual wording of the three live sites; zoocha's miss could not be reproduced beyond Drupal-only (which correctly yields no target service).


### rehabcreative identity fix (2026-11-22, offline only)
Cause: `CLIENT_SERVICES_RE` required "we build/design ... for <clients/startups/...>"; "We help organizations plan, build, improve, and support websites and digital tools" puts the client noun as the object of "help", so no identity was found (reproduced with the quoted homepage text). Fix in `vm1/evidence.py`: "we [also] help <organizations|businesses|companies|brands|startups|founders|nonprofits|institutions|clients> ... plan/build/design/develop/improve/support/..." counts as `entity_type:client_services` on first-party non-bio/blog/docs/case-study pages; sentences with product/feature or own-product wording are vetoed (new narrower `CLIENT_SERVICE_VETO_RE`, since "support"/"API" are normal service words). A bare "We build websites, custom applications, APIs, integrations." is still NOT identity. Scores/thresholds unchanged. One earlier test (`test_qualification_quality`) used "We help startups design and build..." as its ambiguous example; its wording was changed to "We design and build digital products..." because the former is now deliberate identity. Tests 289 OK; 4 ICPs validate. Unverified: the live rehabcreative page itself.


### Directory seed ingestion + Vercel/Netlify access review (2026-11-22, offline only)
**Branch:** `vm1-pilot-issue5-icp-foundation`. **Code commit:** `671d97f10a7c3f4148b045cc4a10a8b71837652e` (pushed, no force).
**Done:** `vm1/directory_seed.py` (catalog loader that fails closed on unverified automated claims; CSV ingest with directory name/URL
attribution; domain dedupe with a full occurrence log; `DirectorySeedAdapter`, always `manual`); CLI `run --directory-seed-csv/--directory-source`
and offline `seed-directory`; pipeline records directory attribution on each company, adds `raw_/selected_manual_directory_seed` counts
(subset of manual, never automated) and a manifest `directory_seed` block, and logs `source`/`source_id` on cross-adapter duplicate rejects;
report treats `directory_seed`-only runs as manual qualification. Changed: `vm1/{directory_seed,discovery,pipeline,report,cli}.py`,
`source_catalog.json` (`access_review` for Vercel and Netlify), `fixtures/directory_seed/*` (fictional), `tests/test_directory_seed.py`, CI smoke step.
**Vercel/Netlify:** no automated adapter. No documented API/feed found; Vercel AUP prohibits scraping with no directory exception; Netlify terms
give no collection permission; robots.txt unreadable in this review (unverified, not "allowed"); Netlify index shows no agency website URLs.
**Tests:** 308 OK locally (289 prior + 19 new, incl. fictional fixture smoke through the pipeline). CI for this push not yet checked.
**Not done / limits:** no live crawl and no real directory data ingested; real seed CSVs must be hand-collected. If an automated and a manual
source find the same domain, the first adapter in order is kept (automated runs first in the CLI), so a manual seed can never be relabelled
as autonomous; the second source's attribution is in the reject log, not the company record. Directory-seed fit is unmeasured.
**Next:** hand-collect a small labelled batch (e.g. 10 agencies per directory in catalog priority order), run `seed-directory` then `run`, and
compare yield per directory; ask Vercel/Netlify for permission or an API only if the user wants automation.


## Engine #2 — candidate prequalification, selection and research backfill (2026-11-23, offline only)
Branch `vm1-pilot-issue5-icp-foundation`. No live crawling, no paid APIs, no outreach; scoring and tier standards unchanged.

**Root causes (code audit; the live run's per-company attribution was not re-crawled).**
1. `select_with_reasons` cut the pool to `max_candidates` *before* research, so every inaccessible (HTTP 403, timeout, TLS, unsafe redirect), robots-refused or evidence-excluded attempt permanently consumed a slot. Nothing replaced it.
2. Ties in the integer prequalify priority (e.g. every PickAnAgency "Software Development" record gets the same +3) were broken only by a seeded hash, while the adapter's tagline and service labels were never compared with the ICP's vocabulary.
3. The unresearched remainder of the pool was not recorded anywhere except as a count.

**Changes.** `prequalify.rank_pool` adds a graded, ICP-relative tie-break (distinct policy terms matched in description / tagline / service labels; missing text is neutral); `prequalify()` scores are untouched (frozen differential tests still pass); the hash only separates candidates no signal distinguishes. `pipeline.research_with_backfill` researches the ranked pool until `max_candidates` companies are *assessed* (any tier, including weak) or `max_research` attempts are spent (default `max_candidates` + 50%, `--max-research`). Each company carries `research_selection` (attempt, wave, pool_rank, outcome, `backfill_for`); the manifest has `research_plan`; `skipped.json` lists unresearched pool members with rank and reason; `counts.selected` now means researched. Replay never backfills. Fetch protections (SSRF, robots, TLS, rate limits) are untouched.

**Deliberate non-changes.** Directory-seed occurrences and cross-source corroboration do not rank (existing "directory listing never ranks" rule). Listing on an exchange and record headcount are not used to gate backfill: scoring does not treat listing as an exclusion and the record can be stale; they only affect order via the existing priority.

**Tests.** `tests/test_engine2_ordering.py`, `test_engine2_backfill.py`, `test_engine2_compat.py` (all 4 ICPs x 7 adapters; 64 outcome patterns). Mutation-checked: disabling backfill or counting weak as failure fails the suite.

**Smallest live validation.** One run, no new crawl scope: `python3 -m vm1 run --icp icp/frontend-studio-worldwide.json --sources pickanagency,drupal_org,wikidata --max-candidates 10 --max-research 15`; read `research_plan` in the manifest and `skipped.json`. Compare assessed count to the earlier 10-researched run (4 possible / 4 weak / 2 inaccessible).


## Engine #2 — specificity-aware candidate ordering (2026-11-23, offline only)
Branch `vm1-pilot-issue5-icp-foundation`. Ordering only: `prequalify()`, evidence extraction, scoring/tiers, fetch protections and backfill are unchanged. No live crawl.

**Trigger.** Live validation (37 discovered, 11 researched, 2 possible, 1 founder) was worse than the earlier ordering (4 possible, 2 founders from 10 attempts). Code-audit causes: generic labels (`consulting`, `web design`, `web development`) widened breadth; `saas`/other ambiguous negatives penalised SaaS-development studios; broad directory category labels counted like company positioning; the integer priority (+3 for any service-hint record) was compared before any ICP-specific evidence.

**Change.** `prequalify.record_evidence` + `rank_pool`. For policies that declare `generic_terms` / `ambiguous_negative_terms` / `service_context_terms` (currently only `frontend-studio-worldwide`, policy_version 1.1.1) the order key is ONE score: structural priority (exchange listing, headcount, vendor/identity flags) + record evidence. Specific terms: +4 in description/tagline, +2 in directory labels (2 distinct max, overlapping phrases once). Generic terms: +2/+1 once in total. Unambiguous negatives -4/-2. Ambiguous negatives: 0 when in service context ("SaaS product development", "development for fintech") or beside the company's own specific wording; otherwise -2/-1. Missing text is neutral. The legacy wording-derived +/-3 is replaced, not added. Policies without the vocabulary keep the exact previous order (tested). Manifest `tie_break` now carries `rank_score` and matched specific/generic/negative/ambiguous terms.

**Offline evidence** (`python3 scripts/engine2_specificity_before_after.py`; 21 FICTIONAL records, 50 seeds; archetypes are the author's labels, not human ground truth): software-studio-style records' top-8 share 12% -> 62%, mean rank 10.5 -> 5.5; generic web-agency records 88% -> 38%, 5.4 -> 9.1; vendor/marketing/unknown records stay out of the top 8.

**Limitations.** No historical candidate metadata (taglines/services per company) is in the repo (`runs/` is gitignored), so the real 37-candidate pool could not be re-ranked; weights (4/2/1) and the context window (2 words) are heuristic, uncalibrated and unvalidated against human labels. Record text is often thin or absent, so many candidates still tie and fall to the seeded hash. Whether this improves possible-fit/founder yield needs one fresh live run (same command as above under Engine #2) plus human review.


## Engine #2 — mixed-service agency correction (2026-11-23, offline only)
Branch `vm1-pilot-issue5-icp-foundation`; worldwide ICP policy_version 1.1.2. Ordering only; scoring, tiers, backfill, fetch safety and other ICPs unchanged.

**Defect.** `social media` was an unconditional negative, so in directory LABELS it cost -2 and exactly cancelled the +2 for a specific label such as `custom software`; a mixed software + social-media listing scored like a listing with no software signal. Marketing was treated as an identity, though a label is only a service line.

**Fix.** New optional policy field `prequalify.service_line_terms` (subset of negative_terms; worldwide ICP: `social media`). As a directory label it is neutral (0, reported as `service_line_neutralised`) when the record also shows a specific target-service term; it is not a bonus. Unchanged on purpose: marketing-only labels keep -2; labels with only generic web terms keep -2; first-party description/tagline stays authoritative (the same words there are penalised unless that text itself names a specific specialization, so a marketing tagline over software labels stays penalised); `directory_marketing_focus_hint` (-1, name/tagline), exchange listing, headcount, SaaS/platform/cloud penalties unchanged. No company names or per-company values.

**Evidence.** `pilot/runs/pickanagency-candidates-rich.json` was NOT available in the sandbox (gitignored), so the real 37-company pool was not re-ranked and Build Me App / Synoviq movements are unmeasured here. Run locally: `cd pilot && python3 scripts/engine2_mixed_service_before_after.py --pool runs/pickanagency-candidates-rich.json --seed <seed used live>` (prints old->new rank, score and reason per domain). On the fictional fallback pool, mixed software+marketing listings moved 6->3 and 3->2, marketing-only and SaaS-vendor records did not move. Automated tiers are not ground truth; fit for the real pool still needs independent review of each record (unknowns: services depth, real first-party positioning, whether software work is client-facing).


## Engine #1 discovery audit — 2026-11-23 (branch `vm1-pilot-issue5-icp-foundation`)
Done (offline, $0, no live calls): audited PickAnAgency/Wikidata/Drupal.org/OSM; adapter hardening; PickAnAgency per-query yield,
documented US `country` filter, audit-only team-size/industry metadata, opt-in `--pickanagency-profile complementary`;
`pool.json` for every run; `discover` (discovery-only) and `discovery-benchmark` commands; source decisions in
`pilot/source_catalog.json`. Read `docs/VM1-ENGINE1-DISCOVERY-AUDIT.md`. Tests: 455 offline pass (was 416). Engine #2 ranking,
scoring, backfill, evidence and decision-maker code untouched (one compat-test invariant narrowed, see audit doc).
Not proven: any real-world yield improvement. Real 37-company pool was not available; import it with `discovery-benchmark --pool`.
Next: run the 6-request live A/B in the audit doc, human-label the unique companies, compare relevant studios per request.
