# VM1 live-run quality remediation (Issue #2)

Branch `vm1-pilot`. Scope: targeted fixes to the existing stdlib-only VM1 prototype. No redesign, no Phase 1,
no paid APIs, no browser automation, no sending, Overpass still off unless `--ack-overpass-terms`.

## 0. What was and was not verified

| Item | Status |
|---|---|
| Offline test suite | **124 tests pass** (82 original, 6 of them deliberately updated, + 42 new regression tests) |
| Baseline live run `20261121T150320Z-live` artifacts (`companies.json`, `report.md`, labels) | **Not available** in the environment where this was written. Nothing here was tested against them, and no contents are invented. |
| Live network re-run | **Not done.** The workspace blocks outbound HTTPS (proxy returns 403 to `query.wikidata.org`). No live result is claimed. |
| Identities of GitLab, Okta, Breadcrumbs, Entromy, Probo, EngineAwesome | **Not independently verified.** Only the fragments quoted in Issue #2 were used. |
| Enriched Wikidata query (`schema:description`, P414, `ORDER BY`) | **Never executed against Wikidata.** It has a visible fallback to the original query on HTTP 400. |
| Precision / relevance | **Still unmeasured.** There are no human labels. Unit tests passing does not establish precision. |

The before/after evidence below comes from **reconstructed pages** that reproduce the failure *patterns* quoted in the
issue. It is not a replay of the live pages. Reproduce it with `scripts/issue2_before_after.py`
(optionally pointing at a checkout of the old commit `9a9a8e0`).

## 1. Root causes (from reading the code at `9a9a8e0` and reproducing each pattern)

1. **Discovery ignored the ICP.** `WikidataAdapter.build_query()` selects every US `software company`;
   `pipeline.select()` then samples 40 by hash. Nothing prefers agencies, so product vendors and large companies enter.
2. **No company-type concept.** `score.py` added points for US location (+20), size (+15) and a named person (+5)
   independent of what the company is. Reproduced: a page with only a US address, "20-50 people" and a misattributed
   executive scored **40 = `possible`** with zero studio/agency evidence (20+15+5). A US address + a size + a "Case studies"
   nav link did the same (20+15+5).
3. **Identity and services matched keywords anywhere.** `ENTITY_RE`, `SERVICE_PATTERNS` and `PORTFOLIO_RE` took the first
   match on any fetched page, any block: product docs ("supports ... TypeScript"), testimonials, client case studies,
   nav labels. A match proved the *words* appeared, not that the company *offers* the service.
4. **Size regex had no subject, tense or range handling.** `\d+ (people|employees...)` matched the tail of the range
   "20-50 people" and any sentence about another organisation ("AdEspresso's team had 50 people").
5. **Decision-maker parser accepted any "Name, Title" block on any fetched page.** It dropped the "at <organisation>"
   part of the title, never checked whether a two-capitalised-word "name" was an organisation ("Homeowners Hub"),
   and ignored testimonial/client/partner/blog structure.

## 2. What changed

| Area | Change | Files |
|---|---|---|
| Context | The HTML parser now records, per text block, the structural context (blockquote, testimonial/client/partner/logo/blog/author/nav/footer by tag, class or id) and the heading chain above it. `context.py` adds URL page-kind and sentence helpers. Verification still uses the unchanged `blocks`. | `htmlparse.py`, `context.py` |
| Company type | `score.classify_company()` derives `agency_studio / saas_vendor / enterprise_software / staffing / unclear` **from evidence only** (no company list). | `score.py` |
| Identity | Studio/agency wording must be self-referential ("X is a software studio", "We're a product studio"), not a client, partner, integration or directory listing. Second route: "we build ... for clients/startups..." (worth fewer points). | `evidence.py` |
| Vendor / enterprise signals | New zero-weight evidence: trial, demo, account, pricing, docs/integrations, "our platform", customers-at-scale; listed-company, global-scale, enterprise positioning. Anchor labels count. Thresholds: ≥3 vendor categories or ≥2 enterprise categories (or listed) with no agency identity => **excluded**. Agency wording alongside them => `unclear` (manual review). | `evidence.py`, `score.py` |
| Services | A service counts only with offering context ("we build/design/specialise in...", "our services include...", a services-page list item, the company's own agency sentence), outside quote/client/editorial/docs/legal/careers/pricing/work pages, and without product-feature wording (supports, integrates, SDK, "our platform", ...). Otherwise recorded as `mention:<tag>` (weight 0, visible in the evidence). | `evidence.py` |
| Client work | `signal:client_work` no longer fires on a bare nav/footer "Case studies" label. +5 only if the company is `agency_studio`. | `evidence.py`, `score.py` |
| Employee size | Accepted only for self-referential present-tense wording ("We are a team of 14", "Our team has 22 people", "<Company> has 12 employees"). Ranges, historical wording ("started as", "grew", "had"), clauses about clients/others, quotes, client/editorial structure and blog/case-study/docs/careers pages => `unknown`. Conflicts => `unknown` as before. | `evidence.py` |
| Decision-makers | Attributed only with credible context: explicit matching "at <org>", team/leadership/about page, team-style heading, or JSON-LD founder/employee of a matching Organization. Rejected: other organisations, organisation-like "names", testimonial/quote/client/partner/author/speaker structure and attribution lines under quotes, blog/docs/case-study/careers pages. Each person records a `basis`. | `people.py` |
| Gate | Only `agency_studio` can reach `possible`. Other types are capped at `weak` (explicit `qualification gate` component keeps the score explainable) and flagged `manual_review`. `strong` also needs US evidence, an explicit in-band headcount and ≥2 offered target services, else it is held at `possible`. | `score.py` |
| Discovery | Pre-research prioritisation uses only fields already in the discovery record (English description, listed-on-exchange flag, headcount); ties keep the seeded hash order, so with no record signals the order is unchanged. The manifest records `selection_priorities` and `discovery_coverage` (how many pool records carry any agency-like description), and the report prints them. | `prequalify.py`, `discovery.py`, `pipeline.py`, `report.py` |

Untouched: `netsafe.py`, `fetch.py`, `guard.py` (SSRF, DNS pinning, TLS verification, robots, spend guard),
evidence re-verification, no-send architecture, adapter allow-list, manual/synthetic labelling.

## 3. Before / after (reconstructed failure patterns, same input to both code versions)

| Pattern | Before (`9a9a8e0`) | After |
|---|---|---|
| Entromy: "20-50 people who own delivery" + exec "at Clearhaven Partners" | `possible` 40; size **50**; DM Michelle Noon | `weak` 20; size **unknown**; DM **unknown** |
| Breadcrumbs: AdEspresso history + "Case studies" nav link | `possible` 40; size **50**; client_work true | `weak` 20; size **unknown**; client_work **false** |
| Probo: "CEO at On this day AI" | `weak`; DM Anthony Hall | DM **unknown** |
| EngineAwesome: "Homeowners Hub" / "Co-Founder / CEO" in a testimonial | DM "Homeowners Hub" | DM **unknown** |
| GitLab-style: product docs listing TypeScript, trial/demo/pricing/login | `weak` 39; **service:typescript** | **excluded** (`saas_vendor`); no service |
| Okta-style: customer portal + sign-on + demo/pricing | service:web_app (excluded only by size 400) | **excluded** (`saas_vendor`); no service |
| Control: fictional studio with identity, services, US, size 14, team page | `strong` 81 | `strong` 81 (unchanged) |

## 4. Remaining discovery limitation (unresolved)

Wikidata cannot be assumed to supply 30–40 relevant agencies. This is a **reasoned expectation, not a measurement**:
Wikidata only covers notable entities, which skews to vendors and larger companies, and small independent studios are
rarely modelled; there is no agency-specific class that was verified. `prequalify` only reorders what Wikidata returns.
The next live run will measure this through `discovery_coverage` in the manifest/report. If it shows few agency-like
descriptions, the honest conclusion is that this source is inadequate for the wedge. Approved alternatives are a user-supplied
`--manual-csv` (labelled `manual`, excluded from autonomous metrics) or Overpass after you acknowledge its terms.
Nothing was added that fabricates a pass.

## 5. Remaining risks and false-positive / false-negative scenarios

False positives (could still reach `possible`):
- A vendor or non-development agency (marketing/web agency) that calls itself a "digital agency / software studio", uses an offering verb with a target service, and shows fewer than 3 vendor CTAs.
- A consultancy with studio-like wording whose "clients" are internal or whose services are not outsourced frontend work.
- A name collision that passes `org_matches` (prefix rule: "Acme Labs" matches company "Acme").
- Stale or wrong page statements: a page saying "We are a team of 14" is attribution, not truth.

False negatives (true agencies held at `weak`/`unclear`/`excluded`):
- Bare noun-phrase pages ("Next.js & TypeScript web applications" with no "we build"): recorded as `mention`, not a service. The fictional PixelForge fixture drops to `weak` for this reason.
- Studios that also sell a product with trial/demo/login/pricing CTAs.
- JS-rendered sites (no server-side text), team pages with unusual markup, titles written "CEO, Acme" (unmatched => unknown), headcounts written as "founded in 2015, we have..." variants, and sizes only in images.
- Only up to 4 secondary pages are fetched; a services page may not be among them.

Other:
- All thresholds (≥3 vendor, ≥2 enterprise, point values, strong gate) are **uncalibrated** starting points.
- Reachability gap from Issue #2 item 6 (33/40 homepages, 30/40 home+secondary) is **not addressed** here.
- The enriched SPARQL query is unverified live.

## 6. Procedure: label the baseline top 20 (do this BEFORE rerunning)

1. Preserve the original run read-only: `cp -R runs/20261121T150320Z-live runs/_baseline-20261121T150320Z-live && chmod -R a-w runs/_baseline-20261121T150320Z-live`.
   Never edit or regenerate files inside the original directory.
2. Open `runs/_baseline-.../labels_template.csv`. Rows are in rank order; label the **first 20**. Columns: `domain, relevant, us_based, decision_maker_correct, notes`.
3. Label blind: use only the company's own site and your own judgement. Do **not** look at the tier, score or evidence first.
   - `relevant` = `y` if it is an independent, US-based software/product/web studio or agency that takes client work and could plausibly buy outsourced React/Next.js/TypeScript/frontend/dashboard help; `n` if it is a SaaS vendor, enterprise, staffing firm, non-US, unrelated or dead; `unsure` otherwise (unsure rows are excluded from the metric).
   - `us_based` = `y` / `n` / `unsure`.
   - `decision_maker_correct`: only if the report named someone. `y` only if that person leads **that** company; `n` otherwise. Leave blank if none was named.
4. Save as `runs/labels-baseline.csv`. If you can, have a second person label the same rows independently and compare.
5. Compute baseline metrics on the **copy**: `python3 -m vm1 report --run runs/_baseline-20261121T150320Z-live --labels runs/labels-baseline.csv`
   (this rewrites `report.md` and the template inside the copy only). The "Top-20 relevance" row is y/(y+n).
6. After the new run, label its top 20 the same way (labels are keyed by domain, so overlapping domains reuse your earlier answers; new domains need new labels).
7. To test recall of the gate, put 5–10 agencies you already know are relevant into a CSV (`name,url`) and run once with `--manual-csv`.
   They stay labelled `manual`; check that they land in `possible`/`strong`, and read why for any that do not.

## 7. Procedure: run the updated pilot on your Mac

```
cd /path/to/prospecting-saas
git fetch origin && git checkout vm1-pilot && git pull
cd pilot
python3 --version                                   # 3.11+; nothing to install
python3 -m unittest discover -s tests -t .          # expect: Ran 124 tests ... OK
python3 -m vm1 synthetic                            # offline, FICTIONAL data, pipeline check only
python3 scripts/issue2_before_after.py              # reconstructed failure patterns (offline)

# after labelling the baseline (section 6):
python3 -m vm1 run --sources wikidata               # live, keyless, $0; new run id, original untouched
open runs/<new_run_id>/report.md                    # check "Discovery status" (query note) and the coverage line
python3 -m vm1 report --run runs/<new_run_id> --labels runs/labels-new.csv
```
Do not enable Overpass unless you have read its usage policy and pass `--ack-overpass-terms` yourself.
Interpret the first live report as: company type and attribution quality (read the evidence, the flags and the `mention:*` items),
discovery coverage, and `weak`/`unclear` volume. A small number of defensible `possible` rows is the expected and acceptable outcome.
