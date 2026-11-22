# Frontend-studio source pool

Use this pool in the weekly VM1 workflow. These are human-reviewed discovery sources. A directory listing gives us a company to investigate. Qualification still requires an independent US studio in the target size band, first-party client application evidence, relevant frontend work, a verified decision-maker, and a specific outreach angle.

| Source label | Directory | Intake focus |
|---|---|---|
| netlify | [Agency Directory](https://www.netlify.com/agency-directory/) | Start with Development, North America, and React or Next.js. Confirm US location on the agency site. |
| sanity | [Agency Partners](https://www.sanity.io/agency-partners) | Client builds that include application engineering. Screen out marketing-site-only studios. |
| contentful | [Solution Partners](https://www.contentful.com/partners/solutions/) | Headless frontend implementation. Screen out large enterprise consultancies. |
| strapi | [Community Partners](https://community.strapi.io/partners) | Client portals or web apps backed by a headless CMS. Confirm location and size independently. |
| supabase | [Partner Catalog](https://supabase.com/partners/catalog) | Service providers with client SaaS, internal tools, or dashboards. Skip extensions and product listings. |
| bigcommerce | [Partner Directory](https://partners.bigcommerce.com/directory/) | Application development, UI development, integrations, and headless storefronts. Use North America to narrow the search and confirm a US base. |
| shopify | [Partner Directory](https://www.shopify.com/partners/directory) | Custom application development or headless commerce, supported by relevant first-party client work. |
| wpengine | [Agency Partner Directory](https://wpengine.com/agency-directory) | Start with Application Development or Headless. Review portfolio evidence for actual frontend engineering. |
| webflow | [Certified Partners](https://webflow.com/certified-partners/browse) | Secondary source. Include only studios with relevant custom web application work outside visual site building. |
| vercel | [Solution Partners](https://vercel.com/partners/solution-partners) | Existing manual source. Screen for studio size and client application work before intake. |

## First comparison batch

Review up to 20 listings each from Netlify, Sanity, Contentful, Strapi, and Supabase, using a consistent filter and ordering per source. Keep shortfalls visible when a source has fewer listings in scope. Preserve the company URL and directory listing link in local review notes. Use one manual CSV run per source and combine the resulting runs with `python3 -m vm1.weekly`, using the source labels above. Rotate in the other directories as batches run dry or repeatedly produce weak fit.

Record the directory filter, order, date, listings screened, and review time. Weekly VM1 counts start at researched companies, so keep the initial listings-screened count as well. Measure strong qualified leads per 100 listings screened and per hour, along with repeated domains. Across sources, first-party evidence establishes qualification and only one source gets credit for a duplicate. A directory listing, affiliate status, or working search filter does not establish buying intent or strong fit.

The target remains 150–200 high-fit leads per week. This source pool has been identified and the directory pages checked, but its weekly qualified throughput is unmeasured. Evaluate a documented or explicitly permitted programmatic intake route only for sources that repeatedly produce good leads.
