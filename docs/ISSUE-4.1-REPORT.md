# Issue #4.1 — Page-selection stabilization and offline replay

Base: `vm1-pilot-issue4` @ `42077f0`. Branch: `vm1-pilot-issue4-stabilization`. $0 spend, no network used, nothing sent.

## Honest limits
The real seven-company before/after **could not be produced here** (no network; the Five Quantum Bits and Ortem
domains are unknown to this environment). Tests use fictional `.example` hosts and prove rules and machinery only.
They are **not** a live relevance result. Run the commands below on your Mac for the real comparison.

## Part A
1. **Canonical URL dedup** — `canonical_key` ignores scheme, `www.`, case, trailing/repeated slashes, index docs, query and
   fragment. The linked URL is still the one fetched. A redirect to an already-fetched page is marked `duplicate_of`
   and not stored twice; the request budget is unchanged.
2. **Agency evidence** — generic slug recognition (`_dev_service_slug`): 2–5 tokens, e.g. `*-development-agency`,
   `*-development-company`, `<specialty>-development`; headline/listicle/blog/how-to slugs and SaaS pages
   (`/developers`, `/platform`, ...) are rejected. No hardcoded domains.
3. **Own-product wording** — "we build apps and SaaS products" without a client anchor becomes `mention:web_app`
   (note: could be the company's own product), not `service:web_app`. Client-anchored or services-heading wording
   still counts. Qualification rules unchanged.
4. **Diversity/safety** — slot plan unchanged (4 pages); robots, SSRF, TLS, size and rate limits untouched.

## Part B — snapshots (`vm1/snapshot.py`, CLI `capture` / `replay`)
Records through a transport under `PoliteFetcher`, so capture obeys robots/SSRF/rate limits. Stores redacted HTML
(emails, mailto/tel, scripts except JSON-LD removed), whitelisted headers only, hash-checked, plus failure states
and hosts that never resolved. Replay opens no sockets, stamps the ORIGINAL capture time, labels candidates
`discovery_method=replay`, `counts_as_fresh_discovery=false`, `counts_as_independent_live_result=false`. A page not
captured raises `SnapshotMissing` (exit 4; `--collect-missing` finishes, lists gaps, still exits 4). Captures older than
30 days are refused (exit 5) unless `--allow-stale`. Snapshot dirs are git-ignored; do not share them.
Bug found and fixed while testing: hosts that failed DNS at capture were re-requested on replay; now recorded and failed identically.

## Mac commands
```
cd pilot
python3 -m vm1 capture --from-run runs/<issue4_live_run_id> \
  --names "Telos Labs,Epic Design Labs,Interline,Velvet Disruption,Five Quantum Bits,Ortem Technologies,GitLab" \
  --out snapshots/seven --capture-pages 8
python3 -m vm1 replay --snapshots snapshots/seven --out runs
```
For "before": check out `42077f0` in a worktree and compare `companies.json` (selected pages, evidence, company type,
score, tier) between the two replays. A script for old-code replay/diff was **not** built.

## Tests
194 tests pass (165 existing, unmodified expectations; 29 new in `pilot/tests/test_issue41_stabilization.py`:
duplicate URLs, agency slugs, own-product attribution, exhausted coverage, determinism, no sockets, redaction, staleness, tampering).

## Remaining
Real seven-site results; old-vs-new diff script; whether Epic regains `agency_studio` depends on live pages.
