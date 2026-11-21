# VM1 — execution-ready decision sheet (2026-11-21)

> **STATUS: AWAITING USER APPROVAL.** This file consolidates earlier planning to accelerate the next step; it does **not** supersede `docs/DECISIONS.md`, authorize programming, approve a vendor, or permit API spending.

## Approval A — architecture, independently of VM1

Recommend accepting Phase 0 v2's broad architecture **conditionally**: Next.js/TypeScript modular monolith, Postgres with tenant isolation, durable external jobs, evidence levels (`source_supported`, `corroborated`, `user_verified`, `inferred`, `unknown`), and future at-most-once Gmail `gmail.send` with an explicit `unknown` outcome and no blind retry. Human-approved outreach, send eligibility and company research are separate. This accepts a *design*, not immediate implementation.

**External blockers remain:** written provider permissions (storage, use, display, resale), legal review for outreach, and Gmail OAuth verification before release. Do not interpret architecture approval as vendor authorization.

## Approval B — VM1, independently of architecture

### Immediate scope: cheap disposable pilot *before* Phase 1
- Local scripts; no dashboard, production auth, multitenancy, payments, CRM, or Gmail.
- **One ICP first:** hypothetical frontend/Next.js service studio seeking independent US software agencies with approx. 5–50 employees and potential client delivery/overflow needs. Exclude staffing/recruiting agencies, unrelated industries, non-US firms and inaccessible/fictional websites. Signals such as hiring or client delivery are **not** evidence of purchase intent.
- Given the ICP and **no URLs**, discover ~30–40 candidate companies, independently fetch their own websites (respect robots.txt, site terms, and SSRF limits), extract verifiable source-supported evidence, assess suitability, identify named business decision-makers only when public evidence exists, and draft **unsent** outreach.
- Label results manually, record costs and errors. No fake contact details or fabricated source claims. No autonomous sending.
- Work may start only after the user explicitly authorizes this pilot. No paid API calls or charges without a separate explicit user budget approval.

### Expansion (later VM1, not a prerequisite to the pilot)
- Expand to three fictional seller profiles described in `docs/PRODUCT-BRIEF.md`, about 150 evaluated companies, and a second independent human labeler.
- Compare eligible search vendors with terms and intended-use rights verified. Exa is a candidate; Tavily and Brave cannot be presumed suitable for cold-outreach-related use merely because of storage provisions. Provider output is transient until storage/display rights are confirmed. Hunter and Apollo are excluded pending separate permissions.
- Strictly separate independent human review from AI-based assistance; do not invent a second labeler or calculate Cohen's kappa without independent labels.

### Proposed gates (not yet approved)
| Metric | Gate |
|---|---|
| Top 20 ICP relevance | >=70% |
| Top 50 ICP relevance | >=60% per ICP (expansion only) |
| Real, reachable company sites | >=95% |
| Duplicates after canonicalization | <=2% |
| Hard exclusion violations | 0 |
| Own-site homepage and secondary page fetchable | >=80% |
| False strong matches | <=15% |
| Human-strong companies marked weak/disqualified | <=20% |
| Supported claim accuracy | >=95% |
| Unsupported factual assertions in unsent drafts | 0 |
| Correct decision-maker, when independently identifiable | >=70% top-1 |
| Wrong-person rate | <=5% |
| Fabricated or falsely verified emails | 0 |
| Human-label agreement (expansion only) | Cohen's kappa >=0.6 with two real independent human labelers |
| Manual reference-list overlap | Report only; reference sets are incomplete |

Report decision-maker coverage and "no person found" cases separately. Include sample denominators, uncertainty and examples of errors; do not claim a pass based on very small samples.

### Proposed budget (NOT APPROVED)
- **Pilot:** $0 paid usage by default. Check whether providers offer legitimate free trial credits for this use case; do not create or consume credentials without the user's instruction.
- **Full VM1:** suggested $10 spending checkpoint; hard ceiling $50 **only if separately authorized**, with real per-job usage accounting and stop limits.
- No subscription purchase and no use of ChatGPT/Claude conversation tokens as a substitute for tracking actual API billing.

### Deliverable from pilot
A reproducible report (no live email sends): ICP, provider or manual sourcing methodology, candidate list with rights-compliant data, top-20 precision, sample evidence and timestamps, scores and explanations, named decision-makers or honest unknowns, unsent draft examples, error cases, time/cost log, and a go/no-go recommendation for expanding VM1.

## Exact authorization questions for the user
1. **Approve architecture A as a design** (with third-party permissions still open)?
2. **Approve VM1 pilot B**: one ICP, 30–40 companies, local scripts, no Gmail, and $0 paid API use?
3. **Optional separately**: approve **up to $50** for *the later expanded VM1*, with $10 checkpoint, only after actual pricing and API accounts are verified? Leave unapproved by default.

If A and B are approved, the next Claude account should begin the no-charge pilot setup and explicitly report any need for provider credentials, terms confirmation or spending before proceeding. Phase 1 remains unapproved.

## No additional architecture review loop
Only re-open architecture decisions for evidence of a specific violation, missing capability, security risk or failed validation outcome. New findings are logged as concrete blockers, not another broad Phase 0 rewrite.
