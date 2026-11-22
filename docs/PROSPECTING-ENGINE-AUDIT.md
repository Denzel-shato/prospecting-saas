# Prospecting engine audit

## Scope

This audit covers discovery, candidate parsing and deduplication, prequalification, page selection, first-party evidence, scoring, public decision-makers, weekly review output, and snapshot provenance. It uses the committed code, available local run artifacts, synthetic fixtures, and a fixed HTML regression corpus. No new live crawl was used.

## Confirmed software defects

| Severity | Area | Root cause and impact | Remediation |
|---|---|---|---|
| High | Project evidence | The crawler selected service/about pages while a first-party work index or case page contained the strongest client-application proof. The scorer therefore saw no project evidence even when a published case was fetched. | Project collection and detail URLs are selected within the existing secondary-page budget. Client-application evidence is a separate capability claim and is never reused as geography, size, identity, or purchase intent. |
| High | Evidence attribution | Content inside work/case pages could be treated as if it described the provider. Customer locations, client headcount, public-company labels, staffing wording, and client product signals could leak into the studio record. | Work pages are excluded from provider identity, location, size, vendor, staffing, and service extraction. A dedicated project extractor requires a delivery relationship and an application artefact. |
| High | Decision makers | Name/title parsing accepted organisation-like labels and testimonial/client context. This produced false people such as “Level Ownership”. | Organisation stopwords, first-party context gates, quote/client exclusion, title validation, and source excerpt verification remain mandatory. |
| Medium | Discovery ranking | When directory records lacked descriptions, selection was almost entirely a seeded hash. That is deterministic but gives no quality signal. | Discovery metadata is retained and used only for pre-research ordering. Missing metadata remains unknown. Hash ordering remains only the final tie-breaker, never qualification evidence. |
| Medium | Provenance | Manual CSV and replay inputs can be mistaken for autonomous discovery if records are copied into a new CSV. | Candidate records retain discovery method, source, source ID, source URL, license, and retrieval timestamp. Snapshot replay is labelled separately and excluded from fresh-discovery metrics. |
| Medium | Operational feedback | A 403 or robots/DNS failure could be confused with a poor-fit company in aggregate review. | Research artifacts preserve homepage status, error, robots result, secondary status, and not-researchable handling. |

## Source and data limitations

Wikidata, Drupal.org, and similar free directories do not guarantee complete coverage of independent studios, current headcount, or decision-makers. A 403 remains an inaccessible site. Directory descriptions and employee counts are discovery hints, not first-party qualification. These limitations cannot be fixed by changing a score threshold.

## Quality interpretation

The engine can now distinguish a company with an attributed first-party client-application case from a company with only a service claim. It still cannot claim 150–200 high-fit prospects from the current free sources. That requires a larger permitted discovery pool and human review of the final contact-ready queue. The minimum useful live validation is one normal worldwide run on the updated policy, followed by review of the top 20 and comparison against the saved pre-fix run. A manual CSV batch cannot measure autonomous-discovery performance.
