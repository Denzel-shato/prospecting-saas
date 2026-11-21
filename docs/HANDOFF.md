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

## VM1 pilot implementation kickoff — 2026-11-21

- Explicit user approval is recorded in `docs/DECISIONS.md`: architecture approved *as design*, initial no-paid-API VM1 pilot authorized (one ICP, 30–40 companies, no Gmail). No Phase 1 or external spending permission.
- Created [GitHub issue #1](https://github.com/Denzel-shato/prospecting-saas/issues/1) with the exact build-and-evaluate specification, deliverables, quality checks and stop rules.
- Created `vm1-pilot` branch from current `main` for prototype development. **This is a branch setup, not an implemented prototype.**
- The next Claude account should **implement the pilot** instead of producing another architecture review. If it cannot write to GitHub, it must return complete changed files or ZIP; the user can pass them to ChatGPT for review and commit.
- No discovery, provider API calls, Gmail calls, tests, purchases or live evaluations have been run as part of this kickoff.

## Instructions for the next account
Read all planning files and the original Phase 0 reports when available. Restate agreed choices separately from proposed revisions. Do not code or incur costs without explicit permission. Finish the session by updating this file with exact work done and commit/PR links.