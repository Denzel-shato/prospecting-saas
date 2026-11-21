# Issue #2 handoff (written 2026-11-21 under token pressure)

Branch `vm1-pilot`. Do NOT merge to `main`. No Phase 1. Keep $0 paid APIs, no sending, Overpass off.

## 1. Current state
Code for Issue #2 items A–E and the discovery improvements is **implemented and committed**. All **124 offline tests passed**
(`cd pilot && python3 -m unittest discover -s tests -t .`, run just before the WIP commit). **Nothing is validated live**: the sandbox
blocks outbound HTTPS, and the baseline run artifacts (`runs/20261121T150320Z-live`) were never available. No precision is measured.

## 2. Files changed
- `pilot/vm1/htmlparse.py`: per-block context labels (quote/client/editorial/nav/footer) and heading chain (`block_ctx`, `block_section`).
- `pilot/vm1/context.py` (new): URL page kind, sentence bounds, third-party/section regexes, quote-neighbour check.
- `pilot/vm1/evidence.py`: self-referential identity, offering-context services (`mention:*` otherwise), self-referential present-tense headcount (ranges/history/third-party => unknown), vendor/enterprise signal evidence, client-work without nav labels; `extract_evidence(..., company_name=)`.
- `pilot/vm1/people.py`: attribution needs credible context (matching org / team page / team heading / JSON-LD org); rejects other-org titles, org-like names, testimonial/client/blog structure; `basis` field.
- `pilot/vm1/score.py`: `classify_company()` + qualification gate (only `agency_studio` can be possible/strong; others capped weak, saas_vendor/enterprise excluded; strong needs US + in-band size + >=2 services).
- `pilot/vm1/prequalify.py` (new), `discovery.py`, `pipeline.py`, `report.py`: record-based prioritisation, enriched Wikidata query with fallback to the original on HTTP 400, coverage/selection info in manifest and report, company type column.
- `pilot/tests/test_issue2_regressions.py` (new, 42 tests); `test_evidence.py`, `test_score_people_drafts.py`, `util.py` updated to the stricter semantics.
- `pilot/scripts/issue2_before_after.py`; `docs/VM1-QUALITY-REMEDIATION.md` (root cause, before/after, risks, labeling + Mac run procedure).
- Untouched: `netsafe.py`, `fetch.py`, `guard.py`.

## 3. Completed (in code, offline-tested only)
A company-type gate; B employee attribution; C decision-maker attribution; D service attribution; E scoring gate; discovery prioritisation;
regression tests for the exact quoted patterns (reconstructed pages, not live pages); before/after script.

## 4. Incomplete
- `pilot/README.md` and `docs/HANDOFF.md` not yet updated (README still says 82 tests; add the new guarantees and a link to the remediation doc).
- GitHub Issue #2 needs the final implementation/testing summary (only a brief progress note was added).
- Live rerun, baseline top-20 human labels, and any calibration of thresholds: not done.
- Issue item 6 (reachability: too_large, robots, network, offsite_redirect) not touched.

## 5. Tests
Last run: `python3 -m unittest discover -s tests -t .` in `pilot/` => `Ran 124 tests ... OK`. Before/after output is in the remediation doc section 3
(reconstructed patterns). No failing tests are known.

## 6. Known issues / concerns
- Enriched SPARQL (`schema:description`, `BIND(EXISTS{P414})`, `ORDER BY ?item`) never ran against Wikidata; fallback exists for HTTP 400 only.
- Thresholds are uncalibrated (>=3 vendor signals, >=2 enterprise, strong gate). Recall risk: bare noun-phrase service lists (no "we build") are `mention` only.
- `org_matches` prefix rule could match a sibling brand ("Acme Labs" vs "Acme").
- Wikidata coverage of small studios is expected to be thin (inference, unmeasured); `discovery_coverage` in the next live manifest will measure it.
- Some old doc statements (README) are stale until updated.

## 7. Next actions (in order)
1. `git pull`, run the test suite and `python3 scripts/issue2_before_after.py`.
2. Update `pilot/README.md` and `docs/HANDOFF.md`; post the full summary on Issue #2.
3. On the user's Mac: preserve baseline, label top 20 blind, then `python3 -m vm1 run --sources wikidata` (see remediation doc sections 6-7). Review the new report's query note and coverage line.
4. Review false positives/negatives by reading `mention:*` evidence and `manual_review` flags; calibrate thresholds only against human labels.
5. Decide with the user whether Wikidata is adequate, or whether to use `--manual-csv` or acknowledged Overpass.
6. Optionally address reachability (item 6) without bypassing robots/SSRF protections.

## 8. Decisions
Conservative-by-design: unknown stays unknown; identity must be proven before secondary signals count; no company-name lists (rules only);
prioritisation never drops candidates or feeds the score; security/spend/no-send code left unchanged.

## 9. Git
Branch `vm1-pilot`; WIP commit `74b95a26b4234463e4a21ec2cd436c8287c1ba31` pushed to origin (fast-forward from `9a9a8e0`). Handoff commit follows this file.
