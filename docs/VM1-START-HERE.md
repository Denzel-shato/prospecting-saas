# VM1 — execution-ready decision sheet (2026-11-21)

> **STATUS (2026-11-21): ARCHITECTURE APPROVED AS DESIGN; INITIAL VM1 PILOT AUTHORIZED.** User approved one ICP, 30–40 companies, local prototype, no Gmail, **$0 paid-API use**. The later expanded VM1, any spending limit above $0, Phase 1 and sending are **not approved**. See `docs/DECISIONS.md`.

## Approval A — architecture (APPROVED AS DESIGN)

Recommend accepting Phase 0 v2's broad architecture **conditionally**: Next.js/TypeScript modular monolith, Postgres with tenant isolation, durable external jobs, evidence levels (`source_supported`, `corroborated`, `user_verified`, `inferred`, `unknown`), and future at-most-once Gmail `gmail.send` with an explicit `unknown` outcome and no blind retry. Human-approved outreach, send eligibility and company research are separate. This accepts a *design*, not immediate implementation.

**External blockers remain:** written provider permissions (storage, use, display, resale), legal review for outreach, and Gmail OAuth verification before release. Do not interpret architecture approval as vendor authorization.

## Approval B — initial VM1 pilot (AUTHORIZED, $0 paid API use)

### Immediate scope: cheap disposable pilot *before* Phase 1
- Local scripts; no dashboard, production auth, multitenancy, payments, CRM, or Gmail.
- **One ICP first:** hypothetical frontend/Next.js service studio seeking independent US software agencies with approx. 5–50 employees and potential client delivery/overflow needs. Exclude staffing/recruiting agencies, unrelated industries, non-US firms and inaccessible/fictional websites. Signals such as hiring or client delivery are **not** evidence of purchase intent.
- Given the ICP and **no URLs**, discover ~30–40 candidate companies, independently fetch their own websites (respect robots.txt, site terms, and SSRF limits), extract verifiable source-supported evidence, assess suitability, identify named business decision-makers only when public evidence exists, and draft **unsent** outreach.
- Label results manually, record costs and errors. No fake contact details or fabricated source claims. No autonomous sending.
- **User authorized this initial pilot on 2026-11-21.** Work may begin. No paid API calls, charges, or subscriptions without a *new* explicit budget approval.

### Expansion (later VM1, not a prerequisite to the pilot)
- Expand to three fictional seller profiles described in `docs/PRODUCT-BRIEF.md`, about 150 evaluated companies, and a second independent human labeler.
- Compare eligible search vendors with terms and intended-use rights verified. Exa is a candidate; Tavily and Brave cannot be presumed suitable for cold-outreach-related use merely because of storage provisions. Provider output is transient until storage/display rights are confirmed. Hunter and Apollo are excluded pending separate permissions.
- Strictly separate independent human review from AI-based assistance; do not invent a second labeler or calculate Cohen's kappa without independent labels.

### Proposed gates (reference benchmarks, not yet final acceptance thresholds)
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

### Approved zero-paid-API limit and later budget proposal
- **Pilot:** $0 paid API usage authorized; do not activate billing, purchase subscriptions, or incur any external API charges. Free tools must still be permitted for the intended usage, and real provider credentials must come from the user.
- **Full VM1:** suggested $10 spending checkpoint; hard ceiling $50 **only if separately authorized**, with real per-job usage accounting and stop limits.
- No subscription purchase and no use of ChatGPT/Claude conversation tokens as a substitute for tracking actual API billing.

### Deliverable from pilot
A reproducible report (no live email sends): ICP, provider or manual sourcing methodology, candidate list with rights-compliant data, top-20 precision, sample evidence and timestamps, scores and explanations, named decision-makers or honest unknowns, unsent draft examples, error cases, time/cost log, and a go/no-go recommendation for expanding VM1.

## Authorization recorded (2026-11-21)
1. **Architecture A:** approved as a design.
2. **Initial VM1 pilot B:** authorized at **$0 paid API spending**, one ICP, 30–40 companies, no Gmail.
3. **Expanded VM1 or any $50 limit:** not approved. Request authorization separately.

Begin local pilot work now. If automated discovery has no permitted zero-cost method or requires user-provided credentials, document the blocker explicitly instead of silently switching to hand-curated URLs or violating providers' terms. Phase 1 remains unapproved.

## No additional architecture review loop
Only re-open architecture decisions for evidence of a specific violation, missing capability, security risk or failed validation outcome. New findings are logged as concrete blockers, not another broad Phase 0 rewrite.
