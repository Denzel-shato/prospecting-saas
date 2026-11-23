# Issue #5 — Configurable ICP foundation (VM1 experimental)

**Status: multi-industry policy implementation is experimental. It is not a production SaaS or an independent lead-quality pass.** Within the approved local VM1 pilot only: $0 paid APIs, no email sending, no billing or auth, no Phase 1.

## Core separation

1. Discovery and discovery-record prequalification (vm1/discovery.py and prequalify.py): use permitted sources and order the candidate pool by the selected policy's positive/negative description terms and size range. No claim that a prequalified record is a real lead.
2. First-party fetching (fetch.py, pipeline.py, pageselect.py): robots, SSRF protections, TLS verification, same-site and canonical dedup are universal. Policy-configurable keywords, page synonyms and slot order choose among safe secondary pages within the same four-page budget.
3. Universal evidence (facts.py, evidence.py): independently of any customer's policy, record the company's on-site statements as claim types, cited short excerpts, levels and URLs. Source-supported means the page STATES something; it does not prove truth or purchasing intent.
4. Qualification and scores (score.py, policy.py): policies specify the target company type and minimum distinct identity signals, required capabilities, vendor/competitor exclusions, size, geography, role classes, weights and strong/possible thresholds. Missing facts are unknown, never invented.
5. Reporting and experiment commands (report.py, cli.py, requalify.py, snapshot.py): show policy id/version/content digest, cited criteria and explicit non-independent status for replay or offline requalification.

## Example ICPs

- pilot/icp/frontend-studio.json: previous US software studio pilot (5-50 band, agency identity gate, technology service evidence), compatibility baseline, existing UN-SENT draft templates only.
- pilot/icp/ai-automation-service-businesses.json: hypothetical AI automation consultant targeting US service firms with multiple public on-site local-service signals and intake capabilities. Drafts DISABLED.
- pilot/icp/ecommerce-marketing-agency.json: hypothetical marketing agency targeting US ecommerce storefronts with at least two distinct store signals and online marketing capabilities. Drafts DISABLED.

These examples do not imply that businesses with intake forms or online shopping features need, want or are ready to buy the seller's services.

## Policy schema v1

Validated by load_policy() in vm1/policy.py. Mandatory: schema_version, id, policy_version, name, description, geography, size, target_type, screens, type_profiles, decision_makers, tiers, strong_requirements, prequalify, page_selection. Optional: seller, notes, bonuses, penalties, drafts.

- geography.countries: currently [] or ["US"] only (the extractor cannot reliably classify arbitrary countries); geography.points scores supported presence.
- size: band and hard_max, plus in-band/above-band/below-band weights.
- target_type: id, identity rules with distinct claim values, capability claim types and weights, minimum capabilities, cap, text for explainable reasons. Fact names must exist in vm1.facts.CLAIM_TYPES.
- screens / type_profiles: hard screens and conflicting companies, including configurable minimum distinct signals and optional strong-identity shielding.
- decision_makers.role_classes: founder_ceo, cto_eng, other_leader (limited by the current underlying title extractor).
- tiers and strong_requirements: numeric thresholds plus optional location/size/capability conditions.
- prequalify: positive_terms and negative_terms matching discovery descriptions; a final asterisk means word continuation. This only changes prioritization, not fit scoring.
  Optional ordering vocabulary (all default empty = legacy ordering, other ICPs unaffected): `generic_terms` (subset of
  positive_terms: broad labels counted once in total), `ambiguous_negative_terms` (subset of negative_terms read in context:
  neutral when the text says what a studio builds, e.g. "SaaS product development studio"; penalised when it says what the
  company sells) and `service_context_terms` (words that mark a services provider; required with ambiguous terms).
- page_selection: relevance_tokens, extra_segments, slot_order, optional service_slug; no override can bypass shared page safety exclusions.
- drafts.enabled: false until that policy's outreach language is separately validated.

## Mac CLI (from pilot/)

    python3 -m unittest discover -s tests -t .
    python3 -m vm1 validate-icp icp/frontend-studio.json
    python3 -m vm1 validate-icp icp/ai-automation-service-businesses.json
    python3 -m vm1 validate-icp icp/ecommerce-marketing-agency.json

    # Fictional fixture, NOT evidence of lead quality:
    python3 -m vm1 synthetic --icp icp/ecommerce-marketing-agency.json --out runs

    # Existing approved free discovery, requires network and permitted website access:
    python3 -m vm1 run --icp icp/frontend-studio.json --sources wikidata

    # A live snapshot capture can be replayed without network:
    python3 -m vm1 capture --icp icp/frontend-studio.json --from-run runs/<old-run-id> --out snapshots/six --capture-pages 8
    python3 -m vm1 replay --icp icp/frontend-studio.json --snapshots snapshots/six --out runs

    # Reuse already-stored evidence under another policy, no fetching or discovery:
    python3 -m vm1 requalify --from-run runs/<existing-run-id> --icp icp/ecommerce-marketing-agency.json --out runs

The requalify command does NOT re-extract website claims or fetch more pages. Previously captured evidence may be incomplete for a new ICP. It does not generate email drafts, and its report is expressly NOT a fresh relevance measurement. Original discovery counts are historical provenance only; new policy fit requires independent human review for that ICP. Never reuse the developer-studio relevance labels to claim ecommerce prospect accuracy.

## Compatibility and evidence strength

Frozen pre-Issue-#5 modules are in pilot/tests/reference/legacy_*_516c9f4.py. Baseline differential tests and fictional multi-ICP fixtures check behaviour; keep the frozen files unchanged.

Historical top-20 relevance: 5/18 (28%) human-labeled for the software studio pilot. No live quality improvement has yet been independently shown. Wikidata's candidate pool is poorly suited to small studios and may be even less suited to other customer types.

Other limitations: incomplete language/industry coverage; only US/non-US location evidence; homepage-link-limited crawling; four secondary pages; possible own-product/service misattribution; narrow leadership title recognition; incomplete evidence saved by an older crawler; no calibrated scores. Most example matches are illustrative. No paid contact data, guessed emails or automated sending. Local redacted snapshots remain git-ignored and should not be shared or retained contrary to provider rights.

## Adding another ICP

Add or verify the required factual claim detectors first (without making the extractor depend on a customer). Copy a valid JSON policy with a new id/version, conservative exclusions, and drafts disabled. Validate it, run the synthetic and snapshot test paths, then collect independently human-labeled live results from permitted industry-appropriate discovery sources. Multi-customer SaaS features and paid/sending integrations remain separate milestone decisions.
