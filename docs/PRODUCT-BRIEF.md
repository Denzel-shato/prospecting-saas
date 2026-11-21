# Product brief — condensed reconstruction of discussions

> This summarizes the discussion; it is **not** the original full PRD. Add the original as `docs/PRD-original.md` if available.

## Product
Research-first B2B prospecting and outreach SaaS for freelancers, agencies, studios and specialist service businesses. A user describes their offer and ICP; the platform finds businesses, researches traceable evidence, ranks fit with explanations, finds public decision-makers with honest confidence levels, prepares personalized drafts, and eventually supports human-approved sending and pipeline tracking.

## Core principles
- Quality over prospect volume, explain reasons for recommending each company.
- Record claim evidence with sources and dates, separate truth from attribution and inference.
- Never invent contacts, email addresses, buying signals or verification.
- Company activity does not by itself mean purchase intent.
- Keep industry, geography, ICP, roles and scoring configurable.
- Prioritize user control and approval before outbound messages.
- Track costs, errors, and evidence accuracy; enforce tenant isolation when building SaaS.

## Planned customer journey
Seller onboarding -> ICP -> campaign -> discovery -> company research -> evidence and fit scoring -> public decision-maker identification -> outreach draft/editor -> user approval -> sending later -> CRM and outcome tracking.

## Feature candidates
Seller profiles, ICPs and campaigns, search-provider adapters and CSV/URL imports, canonical-domain deduplication, sourced company profiles, deterministic scoring with structured AI rationale and review, decision-maker research, drafts and approval history, Gmail with safeguards, fixed pipeline and usage metering, multitenant access controls and audit logs.

## Deferred
Autonomous sending, LinkedIn automation/scraping, inbox-reading/reply sync, multichannel automation, advanced CRM, vector DB and microservices.

## VM1 hypothesis
Given an ICP with **no company URLs**, the system should discover relevant US companies, back its claims with accurate evidence, rank them usefully, find legitimate public decision-makers where available, and draft outreach containing no unsupported factual assertions.

## Fictional test seller profiles
1. Frontend studio: React/Next.js SaaS dashboards/portals; targets US boutique software agencies (approx. 5–50 staff).
2. Product design studio: UX and SaaS product design; targets early-stage US B2B SaaS companies (approx. 10–75 staff).
3. AI automation consultancy: workflow integrations and customer-operations AI; targets US B2B SaaS firms (approx. 10–100 staff) with observable support operations.

These profiles are testing scenarios, not real businesses or confirmed paying customers.