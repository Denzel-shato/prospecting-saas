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
