# Issue #3 — Evidence-extraction fixes (branch `vm1-pilot-issue3`, base `4e67181`)

**Status: offline fixes only. No live improvement is claimed.** The last live run (`20261121T183844Z-live`: top-20 relevance 5/18 = 28%, 4/5 relevant classed weak) has NOT been re-run. A fresh run on a networked machine is required before any improvement claim.

## Honesty limits
- The real fetched pages for teloslabs.co, epicdesignlabs.com, interline.io and velvetdisruption.com were not available. Only the excerpts quoted in Issue #3 are treated as facts; all other scaffolding is `[ASSUMED]` and does not describe the real sites.
- Sandbox has no outbound network to Wikidata/Overpass/target sites, so no live validation was possible.
- Synthetic fixtures show how code treats *patterns*, not precision/recall.

## Root causes found and fixes
| Cause | Fix |
|---|---|
| `customers_at_scale` fired on generic "Trusted by teams shipping to production" | Now requires a scale quantifier (digits/thousands/millions/hundreds) or worldwide/globally qualifier |
| `our_platform` fired on "It's not the platform." (bare "the … platform") | Pattern needs "our … platform" / "all-in-one platform" etc. |
| Negated vendor cues counted ("No free trial needed") | `_negated()` skips matches negated earlier in the same sentence |
| "Custom storefronts … headless on Next.js" only a mention | Offering recognition: custom-build wording without second-person words (`CUSTOM_BUILD_RE`); heading/lead-in context (`What we build`, "We design and build:") via adjacent-block/section lookup; delivery-model words (fixed-price, retainers, commissioned development, project delivery) need a first-person subject. Product-feature veto, third-party/docs/testimonial/bio rejection unchanged |
| Firm's own consulting engagements ("Drew manages the firm's consulting engagements and product development") gave no identity | New *weak* identity `entity_type:consulting_engagements`; extra agency noun phrases (e.g. "software consulting firm", "ecommerce agency", "design and development studio") and client-partnership service wording |
| Weak identity must not shield product vendors | `classify_company`: saas_vendor/enterprise exclusions apply unless identity is *strong* |
| Page selection too narrow | Secondary keywords widened (capabilities/expertise/what-we-build/approach…); `rank_secondary`; per-site limit (4), robots and budget unchanged; run records now store `secondary_candidates` and `homepage_text_blocks` so "page not fetched" vs "no evidence" vs "extractor rejected" can be told apart next run |

Gates intentionally unchanged: agency_studio still requires independent identity AND offered services; strong still needs US + in-band size + ≥2 services; hard exclusions, provenance verification, exec attribution, no-email/no-send untouched.

## Before / after (reconstructed pages; `scripts/issue3_before_after.py`)
| Case | Before (4e67181) | After |
|---|---|---|
| Telos (excerpt + address) | weak 20, unclear, false `customers_at_scale` | weak 20, unclear, no false signal |
| Epic, no identity sentence | weak 20, unclear; Next.js only a mention; false `our_platform` | weak 26, unclear; `service:nextjs`; no false signal; flagged manual review |
| Epic + ASSUMED identity sentence | weak 39, unclear | **possible 46, agency_studio** |
| Interline bio only | weak 20, unclear | weak 36, agency_studio (weak identity + custom_software) |
| Interline + ASSUMED trial/demo/login | excluded saas_vendor | excluded saas_vendor (unchanged) |

## Three outcomes (kept separate)
1. **Correctly recovered (pattern level, offline):** Epic (conditional on an independent identity sentence existing on the real site — unknown), Interline (to weak agency_studio). Not confirmed on real pages.
2. **False-positive regressions among product companies:** none in the negative controls — vendor with "custom dashboards for your team", vendor + consulting wording, docs-page SDK/Next.js, testimonial, team bio, vague marketing, negated vendor cue. Vendors stay excluded; the rest stay weak/non-promoted. Real-world false positives remain possible and are unmeasured.
3. **Still unresolved (insufficient evidence):** **Telos** (no agency identity demonstrable from the excerpt; remains unclear — correct under the gate). **Velvet Disruption** (no excerpt; cause unknown among absent evidence / page selection / extractor rejection). **Epic's** real identity text unknown. Interline's real product/platform signals could still exclude it; that is intended.

## Limitations
- Weak-identity and heading-context rules widen recall and may add false positives; thresholds remain uncalibrated.
- Stored run artifacts hold excerpts, not full pages, so re-extraction against stored runs was not feasible; no original artifacts or labels were altered.
- Interline stays tier weak (36), not a prospect, under current thresholds.

## Tests
Full suite: 148 tests OK (124 existing unchanged, none of their assertions altered + 24 new in `pilot/tests/test_issue3_regressions.py`).

## Next steps (Mac)
Run the VM1 pilot per `docs/VM1-QUALITY-REMEDIATION.md` on a networked machine (Overpass only with `--ack-overpass-terms`), then inspect `secondary_candidates`/`homepage_text_blocks` for Velvet and Telos, and human-label the top 20 as before.

## Applying without direct push
`git fetch origin vm1-pilot-issue3 && git checkout vm1-pilot-issue3`, or apply the patch: `git format-patch -1 <sha>`.
