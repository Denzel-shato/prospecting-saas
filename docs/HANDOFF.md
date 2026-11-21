# Project handoff — 2026-11-21

## Current state
**Planning only.** The user is changing Claude accounts because of usage limits. No app, prototype, API jobs or Gmail sending has been implemented.

## Product goal
A configurable, quality-first B2B prospecting and outreach SaaS. The customer specifies their business and ideal customer profile (ICP). The engine discovers companies, researches cited evidence, ranks and explains fit, identifies public decision-makers when possible, and drafts evidence-grounded outreach for human approval. Sending, pipeline, billing and account infrastructure come later.

## Directions expressed by the user
- Build for B2B service providers broadly; test initially with independent software/product studios, design agencies and specialist tech consultancies.
- Initial discovery tests focus on US-based prospects.
- Quality, truthfulness and inspectable evidence over high lead volume.
- Eventually use web discovery plus permitted licensed data and user-provided CSV/URLs.
- Gmail send-only in eventual MVP, manual reply marking, Outlook deferred. No autonomous sending.
- Sending beta starts US-first subject to compliance review; UK/EU blocked pending review.

## Architecture proposals (not finally approved)
The Phase 0 review v2 proposes Next.js, React, TypeScript, PostgreSQL, modular monolith, durable background jobs; source-supported/corroborated/user-verified/inferred/unknown claim levels; at-most-once Gmail sending with an explicit `unknown` outcome; provider adapters with transient output by default.

## Proposed VM1 revisions (not approved)
Run a disposable local validation **before Phase 1**. Only test discovery from an ICP, website research, evidence, scoring, public decision-makers and unsent drafts. No SaaS UI, authentication, billing, Gmail or real sending. Start with 30–40 companies under one ICP, then expand to three test seller profiles and ~150 companies. Suggested $10 checkpoint and $50 overall ceiling are **not permission to spend**. See `docs/PROPOSED-VM1-REVISIONS.md`.

## Important blockers
- Architecture and VM1 do not have final user approval.
- Provider retention/display/commercial-use rights are unresolved (Exa, Brave, Tavily, Hunter, Apollo).
- Second independent human labeler has not been assigned.
- Original full PRD has not been exported; `docs/PRODUCT-BRIEF.md` is a summary, not verbatim PRD.
- Both Phase 0 **text extracts are committed** in `docs/reviews/` (`phase0-v1-extracted.txt` and `phase0-v2-extracted.txt`). The original PDF files are **not** committed.

## Cross-account handoff received — 2026-11-21

A subsequent Claude account read a ZIP of this repository and reported reviewing the six key project documents plus both extracted Phase 0 reports. The user pasted its session summary into ChatGPT. **This section reflects that pasted summary, not a verbatim copy of the Claude-generated HANDOFF.md artifact.** That account reported no GitHub write access, no implementation, no API calls, and no spending.

### Issues identified by that account — still unresolved
- Budget conflict: Phase 0 v2 proposes a **$100** VM1 cap, whereas `docs/PROPOSED-VM1-REVISIONS.md` suggests a **$10** initial checkpoint and **$50** ceiling. Neither amount is approved.
- Sending scope conflict: v2 includes Gmail tests E/F in VM1 and makes E an exit gate; later recommendations move all email sending tests to a separate milestone.
- Discovery and qualification test thresholds differ between the v2 report and proposed revisions; user must set final gates.
- Provider candidates conflict: v2 rules out Tavily, while later review recommends re-evaluating its current terms and use restrictions. No provider rights are confirmed.
- Repo visibility: the repository has been made **public** to help another account access it, but that did not unblock the other account's GitHub web fetcher. GitHub must be explicitly connected there or the files attached as ZIP. Consider restoring private visibility if public access is unnecessary.

### Next milestone decision sequence
1. Resolve architecture approval (including provider rights remaining open) **separately** from VM1 authorization.
2. Resolve VM1's timing, exact scope, provider candidates, acceptance thresholds, evaluation method, three sample seller profiles, second human labeler, and spending permission.
3. Do not authorize implementation or paid calls merely because documentation has been synchronized.

### Cross-account collaboration note
The other account could inspect a ZIP but could not read or write GitHub directly. At the end of future sessions, ask Claude to return the changed Markdown file or ZIP when its GitHub integration is unavailable. ChatGPT's connected GitHub tools can apply those edits after reviewing the exact file content; do not assume a file was committed merely because Claude said it drafted one.

## Instructions for the next account
Read all planning files and the original Phase 0 reports when available. Restate agreed choices separately from proposed revisions. Do not code or incur costs without explicit permission. Finish the session by updating this file with exact work done and commit/PR links.