# Instructions for Claude accounts working on Prospecting SaaS

## Read first
Read `README.md`, `docs/HANDOFF.md`, `docs/DECISIONS.md`, `docs/PRODUCT-BRIEF.md`, and `docs/PROPOSED-VM1-REVISIONS.md`. Read original Phase 0 reports once they are uploaded to `docs/reviews/`.

## Authorization
- **Updated 2026-11-21:** The user approved the architecture **as a design** and authorized the **initial local VM1 pilot** (one ICP, 30–40 companies, no Gmail) with **$0 paid-API use**. The pilot may now be implemented. **Phase 1, spending, expanded VM1, and email sending remain unapproved.**
- Separate user-approved decisions from proposals and external reviews.
- Obtain explicit user approval before moving through any milestone gate.
- Do not turn architecture or review requests into coding tasks.

## Research and quality
- Never fabricate companies, decision makers, email addresses, sources, vendor terms, prices, or results.
- Separate source-supported claims, corroborated claims, user-verified facts, inferences and unknowns.
- A page excerpt containing a statement does not prove the statement is true.
- Assume third-party search and contact provider data cannot be persisted or redistributed until rights are confirmed for this product.
- No prohibited scraping, access-control circumvention, or private personal contact data.
- Human-reviewed outreach; never enable automatic sending unilaterally.

## Cross-account handoff
1. Start by reading the latest handoff, decision log, open PRs, and recent commits.
2. Prefer a dedicated branch/PR per task. Never overwrite parallel work.
3. Before stopping, update `docs/HANDOFF.md`: completed work, changed files, tested results, blockers, next action, exact commit/PR.
4. Update `docs/DECISIONS.md` only after actual user decisions.
5. Never commit keys, OAuth tokens, passwords or private user data.

## Next task
Begin the **authorized local VM1 pilot only**. Read `docs/VM1-START-HERE.md` and the VM1 GitHub issue. Work with free, permitted methods only. If automated discovery requires unapproved API keys, paid usage, impermissible scraping, or storage rights, stop that step and report the blocker; never invent a passing evaluation. Do not implement Phase 1, Gmail, auth, billing, or a production SaaS.