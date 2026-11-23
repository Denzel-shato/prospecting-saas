# Engine #6 audit and recovery — 2026-11-23

Implemented from f8035e1 (455 tests). Claude's reported batches were unavailable;
this review does not attest to their contents. Recovery batch e154e3e was committed
locally first. The completion commit follows it locally; remote publication may
use equivalent trees via the GitHub API because shell authentication is absent.

## Confirmed defects and remediation

| Severity | Root cause / affected implementation | Fix and regression |
|---|---|---|
| High | pageselect.classify_link demoted /about/team to detail | Recognize nested team paths; selection test |
| High | pipeline.fetch_secondary_pages only expanded project links | Follow linked leadership from About within same budget; budget test |
| High | people.org_matches accepted arbitrary organisation prefixes | Exact normalized name match; other-company CEO rejection |
| Medium | _role_class matched president inside vice president | Engineering VPs remain engineering leaders |
| Medium | add required longer titles even when new role ranked higher | Shorter founder title can outrank engineering title |
| High | JSON-LD malformed @type arrays raised TypeError | Filter type values; malformed fixture |
| High | Explicit worksFor mismatch could be overridden by parent | Conflicting employer veto |
| Medium | Unicode JSON escapes passed extraction, failed evidence check | Preserve exact escaped excerpt spelling |
| High | HTML flattening lost inline field boundaries | Separate people text view; ordinary service evidence blocks unchanged |
| High | Adjacent cards exchanged dangling name/title fields | Container boundaries stop cross-card pairing |
| Medium | All article elements treated as editorial | Explicit Person article cards supported; editorial classes and third-party ancestors veto |
| Medium | JSON-LD graph references ignored | Resolve only same-document IDs; bounded traversal, conflicting/unresolved IDs unknown |
| Medium | Reports only said unknown | Persist outcome, aggregate eligible-company counts, show causes; old records unrecorded |

Tests: test_engine6_review.py and test_engine6_outcomes.py cover extraction,
attribution negatives, page budget, research verification, report aggregation and
old-record compatibility. All existing discovery, ranking, scoring and fetch-safety
tests remain in the full suite. No qualification thresholds changed.

## Comparable offline evaluation

Run `cd pilot && python3 scripts/engine6_before_after.py`. It loads the frozen
f8035e1 modules from local Git and evaluates identical fictional inputs, including
the final excerpt-verification gate. No network needed.

| Development-used fixtures | Before | After |
|---|---:|---:|
| Positive fixtures retaining a named person | 1/4 | 4/4 |
| Negative fixtures incorrectly returning a person | 2/4 | 0/4 |

This is neither independent validation nor a population precision/recall estimate.
Full suite: 471 tests passed, baseline 455. All four ICP policies validated.
git diff --check passed. No live crawl, paid calls or sending.

## Data and remaining limits

The reported 10-company run and its HTML captures were unavailable. Two older local
run directories contain extracted JSON/reports, not captured HTML, and cannot
support an honest extraction before/after comparison. The requested later run
artifacts were not found. No real decision-maker coverage gain is claimed.

Bare article cards without explicit Person markup remain unknown. JavaScript-only
content, unconventional names/titles, unlinked leadership pages and ambiguous
company identity can still cause misses. The extractor is deterministic and not
a complete DOM/entity resolver. Exact organisation matching deliberately leaves
unestablished aliases unknown. Access restrictions remain restrictions.

`no_attributable_person_extracted` means a company page was fetched without a
retained person. It does not prove a person was present, prove an extraction bug,
or distinguish all possible omissions. Named means source-supported, not independently
verified or outreach-ready. Existing weekly human review remains required.

## Minimum controlled validation

First replay the original ten companies if their captured HTML can be supplied.
Independently label whether each contains an identifiable target leader, the correct
name/role/employer and source URL. Compare named-company coverage, wrong-company
names, misses on identifiable pages and page-fetch outcomes using identical pages.
If captures are unavailable, seek approval for one fixed ten-company capture using
the existing four-secondary-page budget and all existing fetch safeguards. Do not
repeat discovery. Review every returned person. A zero-error small sample still
does not establish population accuracy or the 150–200 weekly high-fit target.
