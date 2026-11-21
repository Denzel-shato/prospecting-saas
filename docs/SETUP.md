# Working across Claude accounts

Repository: `Denzel-shato/prospecting-saas` (private).

Each Claude account must separately have GitHub permissions or use authenticated local Git through Claude Code.

## New-session prompt
"Read README.md, CLAUDE.md, docs/HANDOFF.md, docs/DECISIONS.md, docs/PRODUCT-BRIEF.md, docs/PROPOSED-VM1-REVISIONS.md and the Phase 0 reports in docs/reviews. Summarize current state, approved decisions and pending gates. Do not implement or spend money until I approve."

## End-of-session prompt
"Update docs/HANDOFF.md with completed tasks, files changed, evidence, tests, blockers and next actions, and update docs/DECISIONS.md only for my explicit decisions. Commit changes on your branch or open a PR and link it."

## Safety
Never commit API keys, tokens, passwords, private contact data or bulk scraped provider outputs. Separate work by branch or pull request.

## Missing source files
The starter ZIP prepared for this project includes original Phase 0 PDFs and textual exports. When these files are not yet on GitHub, upload `docs/reviews/` from the ZIP using your local Git checkout or GitHub's Add file > Upload files.

The original complete PRD from the earlier ChatGPT writing block has not been exported. The product brief is a summary, not a verbatim replacement.