# Prospecting SaaS — shared planning repository

**Status (2026-11-21): Architecture approved as design; initial disposable VM1 pilot authorized (one ICP, 30–40 companies, no Gmail, $0 paid-API spending). No Phase 1, paid API calls, or sending authorized.**

This repository is the shared project context for switching between Claude accounts and ChatGPT reviews. Every new account should read [CLAUDE.md](CLAUDE.md), [docs/HANDOFF.md](docs/HANDOFF.md) and [docs/DECISIONS.md] before changing anything.

## What we're building
A configurable, research-first B2B prospecting and outreach SaaS. Users describe their offering and ideal customer profile; the system finds relevant real companies, builds attributable evidence, transparently ranks fit, identifies public decision-makers, and drafts truthful outreach for human approval. Sending, pipeline and accounts follow only after validating research quality.

## Current work
Read [docs/VM1-START-HERE.md](docs/VM1-START-HERE.md) for the **authorized initial VM1 pilot**. No API spending, production build or email sending has been approved.

## Navigate the project
- [CLAUDE.md](CLAUDE.md) — instructions for future Claude accounts.
- [docs/HANDOFF.md](docs/HANDOFF.md) — latest project state and blockers.
- [docs/DECISIONS.md](docs/DECISIONS.md) — user directions versus proposals and open questions.
- [docs/PRODUCT-BRIEF.md](docs/PRODUCT-BRIEF.md) — condensed product description; **not** the original full PRD.
- [docs/PROPOSED-VM1-REVISIONS.md](docs/PROPOSED-VM1-REVISIONS.md) — suggested experiment design, **not yet approved**.
- [docs/SETUP.md](docs/SETUP.md) — how another Claude account should resume and hand off.
- [docs/reviews/README.md](docs/reviews/README.md) — source-review documents, still requiring upload.

## Current stop rules
Only the initial local VM1 pilot may be developed/run. Do not start Phase 1, send email, use paid APIs or incur expenses without new explicit user permission. Do not commit secrets or private prospect data. Work on separate branches when agents overlap. Update the handoff and decision log before a Claude account reaches its usage limit.

## Sources not yet complete
The full original PRD was created in a ChatGPT writing block but not exported. Searchable text exports of both architecture reviews are now in `docs/reviews/`. The original PDFs (and v1 Markdown export) from the starter ZIP still need to be uploaded. Summaries are not substitutes for those originals.
