# Issue #2 — ALTERNATE WIP handoff (branch `vm1-pilot-issue2-alt-wip`)

> **Read this first: do NOT merge this branch over `vm1-pilot`.** Another account already pushed a
> "code complete" Issue #2 implementation to `vm1-pilot` (commits `74b95a2`..`4e67181`, see
> `docs/ISSUE-2-HANDOFF.md` on that branch). This branch is an earlier, **incomplete, parallel** attempt,
> preserved only so nothing is lost. It was written before I discovered the divergence.

## 1. Current state
- Base: `9a9a8e0` (old `vm1-pilot` head). Branch commit: `1773d0a` (WIP). Pushed to `origin/vm1-pilot-issue2-alt-wip`.
- `vm1-pilot` was NOT touched. No force-push, no reset, no merge.
- The suite is **red**: running `cd pilot && python3 -m unittest discover -s tests -t .` gave
  `Ran 82 tests ... FAILED (failures=2, errors=9)` (actual run, this session, on this branch).

## 2. Files changed (4)
| File | Purpose |
|---|---|
| `pilot/vm1/htmlparse.py` | Blocks now carry structural context (`block_ctx`: third_party/blog/docs/chrome from blockquote, class/id, footer/nav, and preceding-heading text) and `block_section`. Sanity-checked by hand on a small snippet. |
| `pilot/vm1/context.py` (new) | Self-name derivation, page-kind-from-URL, "is this the company speaking" helper, sentence splitter. (Remote `vm1-pilot` has its own different `context.py`; they will conflict.) |
| `pilot/vm1/evidence.py` | Rewrote extraction: service claims only from offering structures (else `tech_mention:*` at level `unknown`); `identity:*` cues (agency statement, client-service, vendor, enterprise); self-referential-only employee counts (ranges/historical/other-entity -> `unknown`). |
| `pilot/vm1/people.py` | Decision-makers require attribution (title names the company, team/about page or team heading, or JSON-LD org match); third-party `at <Org>` titles and org-like names rejected. |

## 3. Issue #2 items addressed in this WIP
Offline probe on reconstructed (not real) HTML, run this session, showed: size ranges/historical/other-entity -> `unknown`;
third-party executives and organisation-like "names" rejected; tech lists and portal copy no longer produce `service:*`
evidence. Probe script/outputs were only in the scratchpad and are **not committed**.

## 4. NOT done
- **`pilot/vm1/score.py` not updated** to the new schema (still reads removed `entity_type:*`; no agency-identity gate,
  no saas_vendor/enterprise exclusions, no tier cap). This is the main reason tests fail.
- `pipeline.py` does not yet pass `names=` into `extract_evidence` / `find_decision_makers`.
- No discovery/prequalification changes, no report changes, no regression test file, no docs, no before/after script.
- Known bug found last: `web_app` offering not recognised in "We build React and Next.js web applications for startups"
  (the first-person pattern's lazy `[^.]{0,120}?` run plus per-tag group did not match `web applications`; unresolved).

## 5. Tests
Last run: 82 tests, 2 failures + 9 errors. Failing/erroring tests are old assertions that depend on the old schema
(e.g. conflicting sizes, above-band penalty, people/drafts tests that need names/team context) plus score-dependent tests.
No new tests were added on this branch. Nothing here has been run against live network.

## 6. Decisions / rationale
Verbatim-excerpt verification does not prove interpretation, so context (testimonial/blog/docs/third-party heading) and
subject attribution are checked before a claim is asserted; ambiguity stays `unknown`. Tech words alone are never scored.

## 7. Next actions (for the next account)
1. **Do not build on this branch.** Work from `vm1-pilot` (`4e67181` or later) and read its `docs/ISSUE-2-HANDOFF.md`.
2. Only if useful, cherry-pick ideas (heading-based context in `htmlparse.py`, offering-structure service detection) into
   the remote implementation, with tests. Patch: `git diff 9a9a8e0 1773d0a`.
3. A new task text (Issue #3: recover genuine agencies without weakening vendor exclusions) was supplied by the user.
   It names `_identity_evidence`, `classify_company`, `VENDOR_SIGNALS`, which exist on `vm1-pilot`, not here. It also cites
   runs `20261121T183844Z-live` whose artifacts this environment has not seen. **Not started.**

## 8. Git state
Branch `vm1-pilot-issue2-alt-wip`, WIP commit `1773d0aa5086d3b7bace5da2e6ba18295ae26601`, push succeeded.
