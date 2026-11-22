# Frontend-studio discovery source comparison

Reviewed 2026-11-22. The [Vercel Solution Partners directory](https://vercel.com/partners/solution-partners) is the next manual seed source for the frontend-studio pilot. It gives us agencies and project examples to check against first-party sites. Keep Wikidata available as the automated baseline. The product decision on an automated directory adapter remains open pending a repeatable sample and a supported ingestion route.

## Method and result

Reviewed 12 deliberately selected partner listings across tiers and checked company pages for service and location evidence where available. A plausible lead offers client-facing web or application work and has a documented US presence. Explicit enterprise specialization, a current AI-first positioning, or an incompatible geography counts against this particular outreach campaign. Headcounts and contractor demand were frequently unknown. These are manual outreach judgments, independent of VM1's rank. The selected batch is directional and does not estimate directory-wide precision.

- Vercel directory review: 5 plausible, 4 skip, 3 unresolved. This is 5/12 of the sample or 5/9 among resolved rows.
- Latest Wikidata run `20261122T085458Z-live`: 3 plausible, 13 skip, 4 unresolved in the top 20. This is 3/20 overall or 3/16 among resolved rows.
- The batches used different selection methods. The directory produced more usable candidates in this check. A repeated live comparison is required to claim an automated improvement.

| Candidate | Review | Evidence and decision-maker |
|---|---|---|
| Chapter Three | Plausible | [San Francisco Drupal and Next.js client work](https://www.chapterthree.com/blog/chapter-three-becomes-a-vercel-solutions-provider). [Stephanie Canon, Managing Partner](https://www.chapterthree.com/about/stephanie-canon). |
| Alliance Innovations | Plausible | [Client web and mobile delivery](https://vercel.com/partners/solution-partners/alliance-innovations), [San Diego headquarters](https://www.allianceinnovations.com/contact), [Demetrios Kontizas, CEO](https://www.allianceinnovations.com/about). |
| Big Human | Plausible | [New York-area product design and engineering](https://www.bighuman.com/about). Verify a current decision-maker before outreach. |
| Feels Like | Plausible | [Los Angeles and Barcelona team building apps and platforms](https://www.feelslike.studio/about). Verify a current decision-maker before outreach. |
| Engine Digital | Plausible | [Client digital products and New York presence](https://enginedigital.com/), [Next.js project](https://vercel.com/partners/solution-partners/engine-digital). The company [identified Stephen Beck as Founder and CEO](https://enginedigital.com/perspectives/making-the-investment-case-for-your-enterprise-design-system/) in an older article. Verify his current role before outreach. |
| Monogram | Skip | [Current positioning centers on AI systems and workflows](https://monogram.io/about). |
| Space Dinosaurs | Skip | [Enterprise-focused Next.js delivery](https://vercel.com/partners/solution-partners/space-dinosaurs). |
| Blank Metal | Skip | [AI-native engineering specialization](https://www.blankmetal.ai/). |
| Cone Digital | Skip | [Stockholm-based e-commerce agency](https://vercel.com/partners/solution-partners/cone-digital). |
| Artisan Studios | Unresolved | [US digital innovation consultancy](https://www.artisan-studios.com/about). Fit for frontend overflow remains unverified. |
| Delicious Simplicity | Unresolved | [Design and development client work](https://www.delicious-simplicity.com/). Confirm US location and application work. |
| Gateway Web | Unresolved | [Next.js client work and North American coverage](https://vercel.com/partners/solution-partners/gateway-web). Confirm US location and application work. |

## Use in VM1

Enter verified company names and first-party URLs through the existing `manual_csv` adapter. Use the frontend-studio ICP and retain the public listing and first-party project URLs as review evidence. Manual inputs are excluded from autonomous metrics. A future automated source should be evaluated on a repeatable labeled batch with the same scorer, including companies that fail the relevance check.

## Fixed-order follow-up

Reviewed the first ten visible Silver partners in the directory's displayed order on 2026-11-22, from Aceik through Big Human. This sample overlaps the earlier hand-picked review. It is small and represents one tier.

| Order | Partner | Review | Evidence |
|---|---|---|---|
| 1 | Aceik | Skip | [Australian agency](https://www.aceik.com.au/). |
| 2 | Alliance Innovations | Plausible | [US headquarters](https://www.allianceinnovations.com/contact) and [client application services](https://vercel.com/partners/solution-partners/alliance-innovations). |
| 3 | Alpenite | Skip | [European offices](https://www.alpenite.com/contatti/). |
| 4 | Alpha Solutions | Unresolved | [US office and commerce development](https://www.alpha-solutions.com/en). Frontend overflow fit and size need review. |
| 5 | Apply Digital | Skip | [Global client delivery](https://www.applydigital.com/careers/). Its [historical company deck](https://assets.ctfassets.net/fo9twyrwpveg/yXH576N143M46BQY1iXfu/0440ff8a018ba2c98de328a80bd9b621/Apply_Digital_Deck_for_Contentful_Partnership_Page__1_.pdf) lists 230 employees. |
| 6 | Appnovation | Skip | [Global consultancy with multiple regional teams](https://www.appnovation.com/company/contact). |
| 7 | Artisan Studios | Unresolved | [US digital consultancy](https://www.artisan-studios.com/about). Small-studio frontend fit is unverified. |
| 8 | basement.studio | Skip | [Based in Argentina](https://basement.studio/ai/faq). |
| 9 | Bejamas | Skip | [Poland registration](https://bejamas.com/legal/privacy-policy). US location was not established in this review. |
| 10 | Big Human | Plausible | [New York-area client product engineering](https://www.bighuman.com/about). |

Result: **2 plausible, 6 skips, 2 unresolved**. Keep the directory as a manual seed source with US geography, agency scale, and client application work reviewed before import. This fixed-order check did not establish enough improvement to justify an automated directory integration.

## Drupal.org organization API screen

Tested the [documented public API](https://www.drupal.org/drupalorg/docs/apis/rest-and-other-apis) on 2026-11-22. The [Drupal.org terms](https://www.drupal.org/terms) describe CC BY-SA 2.0 for contributed site content. The test used an identifying User-Agent and kept the source payloads out of the repository.

Fetched two sequential pages from `/api-d7/node.json?type=organization&limit=50&sort=changed&direction=DESC` with page numbers 0 and 1. The response contained 100 unique organization records and 94 distinct linked hostnames after removing the www prefix. The organization content type includes vendors, non-US organizations, and old listings as well as client-service agencies.

Four linked organization profiles mentioned React, Next.js, or TypeScript in their descriptions. Three listed non-US headquarters. The fourth, [FocalGroove](https://www.focalgroove.com/), lists Concord, North Carolina and independently advertises client web app development using Next.js and React. Its [team page](https://www.focalgroove.com/team/) names CEO and co-founder Mark Shropshire, who leads web development and automation. Headcount is unverified.

This was a description screen of recently edited records, not a complete qualification run. Agencies may offer relevant services without naming the stack in Drupal.org. The result demonstrates a technically usable endpoint, but only one verified lead through this screen. Defer implementing an adapter until there is evidence that a more targeted Drupal.org query can supply a viable sample for this ICP.
