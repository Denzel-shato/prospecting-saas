# Proposed VM1 revisions — awaiting approval

**Review recommendations only. Not authorization to code, run APIs or spend money.**

## Scope
Run a disposable local research-quality validation **before Phase 1**. VM1 covers ICP-to-company discovery, own-site research, evidence integrity, fit scoring, public decision-maker identification and unsent personalized drafts. It does not cover Gmail OAuth, email sending, suppression, UI, authentication, multi-tenant schema or billing.

## Staged evaluation
1. Feasibility pilot: one ICP, about 30–40 companies. Check relevance, own-site fetchability, evidence accuracy, and costs.
2. Expand to three ICPs and about 150 companies; compare permitted providers, score results, audit decisions and draft outputs.
3. Second human reviewer independently labels a sample; do not claim inter-rater agreement until two human reviewers genuinely participate.

## Suggested thresholds

| Metric | Suggested gate |
|---|---|
| Top-20 relevance | >=70% |
| Top-50 relevance | >=60% per ICP |
| Reachable company sites | >=95% |
| Duplicates after deduplication | <=2% |
| Hard exclusion violations | 0 |
| Own-site home + secondary-page fetchability | >=80% |
| Manual reference list overlap | Report, not a pass/fail gate |
| False strong matches | <=15% |
| Human-strong matches marked weak/disqualified | <=20% |
| Source-supported claim accuracy | >=95% |
| Unsupported factual assertions in drafts | 0 |
| Decision-maker top-1 accuracy where independently identifiable | >=70% |
| Wrong-person rate | <=5% |
| Invented / falsely verified emails | 0 |
| Independent human label agreement | Cohen's kappa >=0.6 if two humans have labeled |

Report coverage separately, including cases where no decision-maker is identifiable.

## Spending — NOT APPROVED
Suggested $10 initial checkpoint, maximum $50 across VM1. Hard cost limits by job/provider/model, no chargeable calls without separate explicit authorization.

## Providers
Exa is a candidate, not an approved source. Re-evaluate Tavily's current Platform Terms alongside its restrictions on unsolicited marketing; Brave may restrict storage and uses connected with mass mail. Hunter and Apollo are not approved. Seek written confirmation for the intended multi-tenant prospecting and outreach use case before persisting or redistributing provider output.

## Next
Obtain user's decisions on scope, thresholds, provider permissions, second labeler and budget. Update decision log only when explicitly confirmed.