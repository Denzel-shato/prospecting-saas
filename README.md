# Prospecting SaaS — shared planning repository

**Status: Planning only. No implementation, VM1 execution or paid API usage is authorized.**

This private repository is the shared project context for switching between Claude accounts and ChatGPT reviews. Every new account should read [CLAUDE.md](CLAUDE.md), [docs/HANDOFF.md](docs/HANDOFF.md) and [docs/DECISIONS.md] before changing anything.

## What we're building
A configurable, research-first B2B prospecting and outreach SaaS. Users describe their offering and ideal customer profile; the system finds relevant real companies, builds attributable evidence, transparently ranks fit, identifies public decision-makers, and drafts truthful outreach for human approval. Sending, pipeline and accounts follow only after validating research quality.

## Next decision
Read [docs/VM1-START-HERE.md](docs/VM1-START-HERE.md) for the short approval-ready pilot plan. **No approvals or spending have yet been granted.**

## Navigate the project
- [CLAUDE.md](CLAUDE.md) — instructions for future Claude accounts.
- [docs/HANDOFF.md](docs/HANDOFF.md) — latest project state and blockers.
- [docs/DECISIONS.md](docs/DECISIONS.md) — user directions versus proposals and open questions.
- [docs/PRODUCT-BRIEF.md](docs/PRODUCT-BRIEF.md) — condensed product description; **not** the original full PRD.
- [docs/PROPOSED-VM1-REVISIONS.md](docs/PROPOSED-VM1-REVISIONS.md) — suggested experiment design, **not yet approved**.
- [docs/SETUP.md](docs/SETUP.md) — how another Claude account should resume and hand off.
- [docs/reviews/README.md](docs/reviews/README.md) — source-review documents, still requiring upload.

## Current stop rules
Do not start Phase 1, run VM1, send email, use paid APIs or approve expenditures without explicit user permission. Do not commit secrets or private prospect data. Work on separate branches when agents overlap. Update the handoff and decision log before a Claude account reaches its usage limit.

## Sources not yet complete
The full original PRD was created in a ChatGPT writing block but not exported. Searchable text exports of both architecture reviews are now in `docs/reviews/`. The original PDFs (and v1 Markdown export) from the starter ZIP still need to be uploaded. Summaries are not substitutes for those originals.
