"""Regression tests for GitHub Issue #2 (first live run, `20261121T150320Z-live`).

IMPORTANT: the live page contents were NOT available when these tests were written. Fixtures are
RECONSTRUCTIONS built from the exact fragments quoted in the issue/task ("20-50 people who own
delivery", AdEspresso history, "Clearhaven Partners", "On this day AI", "Homeowners Hub", product
docs listing TypeScript, portals, a bare "Case studies" link). They reproduce the failure PATTERN,
not the real pages. Company names in tests are labels for the pattern, not exclusion rules.
"""

import unittest

import tests.util as u
from vm1.discovery import AUTOMATED, ApiClient, Candidate, DiscoveryBlocked, WikidataAdapter
from vm1.evidence import UNKNOWN, extract_evidence, verify_evidence
from vm1.pipeline import select, select_with_reasons
from vm1.people import find_decision_makers
from vm1.prequalify import coverage, prequalify
from vm1.score import TIER_POSSIBLE, score_company

K = "x.example"


def types(evs):
    return {e.claim_type for e in evs}


def sizes(evs):
    return [e for e in evs if e.claim_type == "size:employees"]


def full(body, name=None, team_body=None):
    snaps = [u.snap(body)]
    if team_body:
        snaps.append(u.team_snap(team_body))
    evs = extract_evidence(K, snaps, company_name=name)
    dms = find_decision_makers(snaps, company_key=K, company_name=name)
    return evs, dms, score_company(evs, dms, homepage_ok=True)


# ------------------------------------------------------------------------------ B. employee size
class EmployeeSizeAttributionTests(unittest.TestCase):
    def test_entromy_range_about_delivery_people_is_not_a_headcount(self):
        for body in (
            "<p>20-50 people who own delivery</p>",
            "<p>20–50 people who own delivery</p>",
            "<p>We assemble 20–50 people who own delivery for your programme.</p>",
            "<p>We have 20-50 people who own delivery.</p>",
            "<p>Our delivery pods are 20 to 50 people who own delivery.</p>",
        ):
            with self.subTest(body=body):
                evs = extract_evidence(K, [u.snap(body)], company_name="Entromy")
                self.assertEqual(sizes(evs), [], "range / process wording must stay unknown")

    def test_adespresso_history_is_not_the_company_headcount(self):
        for body in (
            "<p>AdEspresso grew from 3 to a team of 50 people before the acquisition.</p>",
            "<p>When we started AdEspresso we were a team of 50 people.</p>",
            "<p>We started as a team of 3 and had 50 employees at AdEspresso.</p>",
            "<p>AdEspresso is a team of 50 people.</p>",
        ):
            with self.subTest(body=body):
                evs = extract_evidence(K, [u.snap(body)], company_name="Breadcrumbs")
                self.assertEqual(sizes(evs), [])

    def test_quotes_and_editorial_pages_cannot_supply_a_headcount(self):
        evs = extract_evidence(K, [u.snap("<blockquote><p>We are a team of 50 people.</p></blockquote>")])
        self.assertEqual(sizes(evs), [])
        evs = extract_evidence(K, [u.snap('<div class="testimonial"><p>We have 50 employees.</p></div>')])
        self.assertEqual(sizes(evs), [])
        evs = extract_evidence(K, [u.snap("<p>We are a team of 50 people.</p>", "https://x.example/blog/story", home=False)])
        self.assertEqual(sizes(evs), [])
        evs = extract_evidence(K, [u.snap("<p>We are a team of 50 people.</p>", "https://x.example/case-studies/acme", home=False)])
        self.assertEqual(sizes(evs), [])

    def test_clear_self_referential_present_tense_sizes_are_accepted(self):
        for body, n in (("<p>We are a team of 14 engineers and designers.</p>", 14),
                        ("<p>We're a small studio of 9.</p>", 9),
                        ("<p>Our team has 22 people.</p>", 22),
                        ("<p>We currently have 30 engineers.</p>", 30),
                        ("<p>Founded in 2015, we are a team of 12.</p>", 12)):
            with self.subTest(body=body):
                s = sizes(extract_evidence(K, [u.snap(body)]))
                self.assertEqual([(e.level, e.value) for e in s], [("source_supported", n)])

    def test_company_name_anchored_statement_is_accepted_only_with_that_name(self):
        body = "<p>Breadcrumbs has 12 employees.</p>"
        self.assertEqual(sizes(extract_evidence(K, [u.snap(body)], company_name="Entromy")), [])
        s = sizes(extract_evidence(K, [u.snap(body)], company_name="Breadcrumbs, Inc."))
        self.assertEqual([e.value for e in s], [12])

    def test_bare_fragment_without_a_subject_is_unknown(self):
        self.assertEqual(sizes(extract_evidence(K, [u.snap("<p>A team of 80.</p>")])), [])

    def test_ambiguous_size_never_scores_and_stays_listed_as_unknown(self):
        _, _, r = full("<p>Software studio building React apps. Austin, TX 78701.</p>"
                       "<p>20-50 people who own delivery</p>")
        self.assertFalse([c for c in r.components if c["rule"].startswith("size")])
        self.assertTrue(any(x.startswith("size") for x in r.unknowns))

    def test_accepted_size_excerpt_still_verifies_verbatim(self):
        s = u.snap("<p>We are a team of 14 engineers and designers.</p>")
        for e in extract_evidence(K, [s]):
            self.assertTrue(verify_evidence(e, {s.url: s.page}), e.claim_type)


# ------------------------------------------------------------------------- C. decision makers
class DecisionMakerAttributionTests(unittest.TestCase):
    def dms(self, body, url="https://x.example/team", home=False, name="Entromy"):
        return find_decision_makers([u.snap(body, url, home=home)], company_key="entromy.com", company_name=name)

    def test_title_at_another_organisation_is_not_attributed(self):
        # Entromy / Clearhaven Partners pattern
        self.assertEqual(self.dms("<p>Michelle Noon, Managing Partner &amp; Co-Founder at Clearhaven Partners</p>"), [])
        self.assertEqual(self.dms("<div><h3>Michelle Noon</h3><p>Managing Partner &amp; Co-Founder at Clearhaven Partners</p></div>"), [])
        # Probo / "On this day AI" pattern
        self.assertEqual(self.dms("<p>Anthony Hall, CEO at On this day AI</p>", name="Probo"), [])
        self.assertEqual(self.dms("<p>Anthony Hall - CEO at On this day AI</p>", url="https://x.example/", home=True, name="Probo"), [])

    def test_organisation_name_is_not_a_person_name(self):
        # EngineAwesome / "Homeowners Hub" pattern: a brand heading above "Co-Founder / CEO"
        self.assertEqual(self.dms("<div><h3>Homeowners Hub</h3><p>Co-Founder / CEO</p></div>", name="EngineAwesome"), [])
        body = '<div class="testimonial"><h3>Homeowners Hub</h3><p>Co-Founder / CEO</p></div>'
        self.assertEqual(self.dms(body, url="https://x.example/", home=True, name="EngineAwesome"), [])

    def test_testimonials_clients_partners_authors_are_not_company_leadership(self):
        cases = {
            "blockquote": "<blockquote>Great partner, would hire again and again.</blockquote><p>Jane Roe, CEO</p>",
            "testimonial_class": '<div class="testimonial-card"><p>Jane Roe, CEO</p></div>',
            "client_logo_grid": '<div class="client-logos"><h3>Jane Roe</h3><p>Founder</p></div>',
            "heading_clients": "<h2>What our clients say</h2><p>Jane Roe, CEO</p>",
            "heading_partners": "<h2>Our partners</h2><div><h3>Jane Roe</h3><p>CEO</p></div>",
            "heading_case_study": "<h2>Case study: Acme</h2><p>Jane Roe, CTO</p>",
            "quote_marks": "<p>“We shipped in half the time and the team was superb throughout.”</p><p>Jane Roe, CEO</p>",
            "speaker_heading": "<h2>Speakers</h2><p>Jane Roe, CTO</p>",
        }
        for label, body in cases.items():
            with self.subTest(label):
                self.assertEqual(self.dms(body, url="https://x.example/", home=True), [])
                self.assertEqual(self.dms(body), [], "even on a /team URL, third-party structure rejects")

    def test_blog_docs_case_study_and_careers_pages_never_name_decision_makers(self):
        for path in ("/blog/launch-post", "/docs/guide", "/case-studies/acme", "/work/acme", "/careers/engineer"):
            with self.subTest(path):
                self.assertEqual(self.dms("<p>Jane Roe, CEO</p>", url=f"https://x.example{path}"), [])

    def test_bare_name_title_on_homepage_without_team_context_is_unknown(self):
        self.assertEqual(self.dms("<p>Jane Roe, CEO</p>", url="https://x.example/", home=True), [])

    def test_credible_context_is_attributed_with_a_reason(self):
        d = self.dms("<p>Maya Okafor, Founder</p>")
        self.assertEqual((d[0].name, d[0].basis), ("Maya Okafor", "team_page"))
        d = self.dms("<h2>Meet the team</h2><div><h3>Maya Okafor</h3><p>CEO</p></div>", url="https://x.example/", home=True)
        self.assertEqual((d[0].name, d[0].basis), ("Maya Okafor", "team_section"))
        d = self.dms("<p>Maya Okafor, CEO at Entromy</p>", url="https://x.example/", home=True)
        self.assertEqual((d[0].name, d[0].basis), ("Maya Okafor", "explicit_org_match"))

    def test_jsonld_requires_affiliation_with_the_target_organisation(self):
        def page(ld):
            return u.snap(f'<script type="application/ld+json">{ld}</script><p>Welcome</p>')
        ok = ('{"@type":"Organization","name":"Brightlane Studio","founder":'
              '{"@type":"Person","name":"Maya Okafor","jobTitle":"Founder"}}')
        other = ('{"@type":"Organization","name":"Clearhaven Partners","founder":'
                 '{"@type":"Person","name":"Michelle Noon","jobTitle":"Founder"}}')
        author = ('{"@type":"Article","author":{"@type":"Person","name":"Sam Lee","jobTitle":"CTO"}}')
        review = ('{"@type":"Organization","name":"Brightlane Studio","review":{"@type":"Review","author":'
                  '{"@type":"Person","name":"Jane Roe","jobTitle":"CEO"}}}')
        names = lambda ld: [d.name for d in find_decision_makers(  # noqa: E731
            [page(ld)], company_key="brightlane.example", company_name="Brightlane Studio")]
        self.assertEqual(names(ok), ["Maya Okafor"])
        self.assertEqual(names(other), [])
        self.assertEqual(names(author), [])
        self.assertEqual(names(review), [])

    def test_no_email_or_contact_fields_exist(self):
        for d in self.dms("<p>Maya Okafor, Founder</p>"):
            self.assertFalse(hasattr(d, "email"))

    def test_decision_maker_points_only_for_attributed_people(self):
        body = "<p>Software studio building React apps. Austin, TX 78701.</p>"
        _, dms, r = full(body, name="Entromy", team_body="<p>Michelle Noon, Managing Partner at Clearhaven Partners</p>")
        self.assertEqual(dms, [])
        self.assertFalse([c for c in r.components if c["rule"].startswith("decision-maker")])


# --------------------------------------------------------------------------- D. service attribution
class ServiceAttributionTests(unittest.TestCase):
    def ev(self, body, url="https://x.example/", home=True):
        return extract_evidence(K, [u.snap(body, url, home=home)])

    def test_supported_programming_languages_in_a_product_is_not_a_service(self):
        # GitLab pattern
        evs = self.ev("<p>Our platform supports many programming languages including TypeScript, Ruby and Go.</p>")
        self.assertNotIn("service:typescript", types(evs))
        self.assertIn("mention:typescript", types(evs))  # kept for transparency, weight 0
        evs = self.ev("<li>TypeScript</li>", "https://x.example/docs/languages", home=False)
        self.assertNotIn("service:typescript", types(evs))

    def test_customer_portals_in_a_product_are_not_a_service(self):
        # Okta pattern
        for body in ("<p>Customers can log in to the customer portal to manage billing and invoices.</p>",
                     "<p>Give users a self-service portal and admin panels with single sign-on.</p>",
                     "<p>Our customer portal lets you manage your subscription.</p>"):
            self.assertNotIn("service:web_app", types(self.ev(body)), body)

    def test_bare_case_studies_label_is_not_client_work(self):
        # Breadcrumbs pattern
        self.assertNotIn("signal:client_work", types(self.ev('<nav><a href="/customers">Case studies</a></nav>')))
        self.assertNotIn("signal:client_work", types(self.ev('<footer><a href="/cs">Case studies</a></footer>')))
        self.assertNotIn("signal:client_work", types(self.ev('<div class="testimonial"><p>See how Acme grew with our case studies and tools.</p></div>')))

    def test_testimonials_blog_docs_and_client_tech_are_not_services(self):
        cases = {
            "testimonial": ("<blockquote>They built our React dashboards in six weeks.</blockquote>", "https://x.example/", True),
            "blog": ("<p>We build React apps and share tips for Next.js developers.</p>", "https://x.example/blog/react-tips", False),
            "docs": ("<p>We build with Next.js and React.</p>", "https://x.example/docs/setup", False),
            "client_work_page": ("<p>Built with React and Next.js for Acme Logistics.</p>", "https://x.example/work/acme", False),
            "generic_marketing": ("<p>Modern SaaS dashboards, React, TypeScript.</p>", "https://x.example/", True),
        }
        for label, (body, url, home) in cases.items():
            with self.subTest(label):
                got = {t for t in types(self.ev(body, url, home)) if t.startswith("service:")}
                self.assertEqual(got, set())

    def test_offered_services_are_attributed_with_verified_excerpts(self):
        s = u.snap("<p>We build React and Next.js web applications for startups.</p>")
        evs = extract_evidence(K, [s])
        self.assertTrue({"service:react", "service:nextjs", "service:web_app"} <= types(evs))
        for e in evs:
            self.assertTrue(verify_evidence(e, {s.url: s.page}), e.claim_type)
            self.assertTrue(e.source_url and e.excerpt)

    def test_services_page_list_item_counts_as_offering(self):
        evs = self.ev("<ul><li>React development</li><li>Admin panels</li></ul>", "https://x.example/services", home=False)
        self.assertIn("service:react", types(evs))

    def test_agency_self_description_sentence_counts_for_its_own_tech(self):
        evs = self.ev("<h1>Northwind UI is a frontend agency</h1>")
        self.assertIn("service:frontend", types(evs))
        self.assertIn("entity_type:studio_or_agency", types(evs))


# --------------------------------------------------------------------------- A/E. qualification
SAAS_VENDOR_PAGE = (
    '<nav><a href="/pricing">Pricing</a><a href="/login">Log in</a><a href="/docs">Documentation</a>'
    '<a href="/trial">Start free trial</a><a href="/demo">Request a demo</a></nav>'
    "<h1>The all-in-one DevOps platform</h1>"
    "<p>Our platform supports many programming languages including TypeScript, Ruby and Go.</p>"
    "<p>Trusted by thousands of teams worldwide.</p>"
    "<p>HQ: 1 Market St, San Francisco, CA 94105.</p><p>We are a team of 40 people.</p>")


class QualificationGateTests(unittest.TestCase):
    def test_saas_vendor_with_every_generic_signal_is_excluded_not_possible(self):
        evs, dms, r = full(SAAS_VENDOR_PAGE, team_body="<p>Maya Okafor, CEO</p>")
        self.assertEqual(r.company_type, "saas_vendor")
        self.assertEqual(r.tier, "excluded")
        self.assertIsNone(r.total)
        self.assertIn("saas_vendor", [e["rule"] for e in r.hard_exclusions])
        self.assertTrue(r.hard_exclusions[0]["evidence_ids"])

    def test_enterprise_corporation_is_excluded(self):
        body = ("<h1>Acme Software</h1><p>NASDAQ: ACME. Offices in 30 countries.</p>"
                "<p>HQ: 1 Plaza, Chicago, IL 60601.</p>")
        _, _, r = full(body)
        self.assertEqual((r.company_type, r.tier), ("enterprise_software", "excluded"))

    def test_staffing_remains_excluded(self):
        _, _, r = full("<h1>We are an IT staffing agency</h1><p>Austin, TX 78701. React.</p>")
        self.assertEqual((r.company_type, r.tier), ("staffing", "excluded"))

    def test_strong_secondary_signals_cannot_promote_an_unverified_agency_identity(self):
        # US address + explicit in-band size + tech terms + client work + named exec, but NO
        # evidence that this is a client-services studio/agency.
        body = ("<p>We build React and Next.js web applications and TypeScript tools.</p>"
                "<p>We are a team of 14 engineers and designers.</p>"
                "<p>HQ: 400 W Madison St, Chicago, IL 60601.</p>"
                '<h2>Our work</h2><p>We have built dashboards and portals for many clients.</p>')
        _, dms, r = full(body, team_body="<p>Maya Okafor, CEO</p>")
        self.assertTrue(dms)
        self.assertEqual(r.company_type, "unclear")
        self.assertEqual(r.tier, "weak")
        self.assertLessEqual(r.total, TIER_POSSIBLE - 1)
        self.assertTrue(any("manual_review" in f for f in r.flags))
        self.assertEqual(r.total, sum(c["points"] for c in r.components), "gate stays explainable")
        self.assertTrue(any(c["rule"].startswith("qualification gate") for c in r.components))

    def test_technology_mentions_alone_do_not_qualify(self):
        body = ("<p>Our platform supports React, Next.js, TypeScript and frontend frameworks.</p>"
                "<p>Customer portals and dashboards are included in every plan.</p>"
                "<p>Austin, TX 78701. We are a team of 12.</p>")
        _, _, r = full(body)
        self.assertNotIn(r.tier, ("possible", "strong"))

    def test_mixed_agency_and_vendor_wording_goes_to_manual_review(self):
        body = ("<h1>Acme is a software studio</h1><p>We build React web applications for startups.</p>"
                '<nav><a href="/pricing">Pricing</a><a href="/login">Log in</a><a href="/trial">Start free trial</a>'
                '<a href="/demo">Request a demo</a></nav>'
                "<p>Austin, TX 78701.</p>")
        _, _, r = full(body)
        self.assertEqual(r.company_type, "unclear")
        self.assertEqual(r.tier, "weak")

    def test_verified_agency_reaches_possible_and_strong_only_with_supporting_signals(self):
        base = ("<h1>Acme is a software studio</h1><p>We build React and Next.js web applications for startups.</p>"
                "<p>Austin, TX 78701.</p>")
        _, _, r = full(base)
        self.assertEqual((r.company_type, r.tier), ("agency_studio", "possible"))  # size unknown: stays possible
        _, _, r = full(base + "<p>We are a team of 14 engineers and designers.</p>")
        self.assertEqual((r.company_type, r.tier), ("agency_studio", "strong"))
        # same score but missing US evidence -> held at possible by the strong gate
        no_us = ("<h1>Acme is a software studio</h1><p>We build React and Next.js web applications for startups.</p>"
                 "<p>We are a team of 14 engineers and designers.</p><p>Maya Okafor, CEO</p>")
        _, _, r = full(no_us, team_body="<p>Maya Okafor, CEO</p>")
        self.assertLess(r.total, 65 + 100)
        self.assertNotEqual(r.tier, "strong")

    def test_build_for_clients_wording_counts_as_identity_with_fewer_points(self):
        body = "<p>We build React web applications for our clients.</p><p>Austin, TX 78701.</p>"
        _, _, r = full(body)
        self.assertEqual(r.company_type, "agency_studio")
        self.assertTrue(any("builds-for-clients" in c["rule"] for c in r.components))

    def test_unknowns_remain_unknown_not_positive(self):
        _, _, r = full("<p>Coming soon.</p>")
        self.assertEqual(r.tier, "weak")
        self.assertEqual(r.total, 0)
        self.assertTrue(r.unknowns)

    def test_scoring_is_deterministic(self):
        a = full(SAAS_VENDOR_PAGE)[2].to_dict()
        b = full(SAAS_VENDOR_PAGE)[2].to_dict()
        self.assertEqual(a, b)


# ----------------------------------------------------------------------------------- discovery
class DiscoveryPrioritisationTests(unittest.TestCase):
    def cand(self, name, **attrs):
        return Candidate(name, f"https://{name}.example", AUTOMATED, "wikidata", attrs=dict(attrs))

    def test_wikidata_parse_captures_description_and_listing_flag(self):
        data = {"results": {"bindings": [
            {"item": {"value": "http://www.wikidata.org/entity/Q1"}, "itemLabel": {"value": "Foo"},
             "website": {"value": "https://foo.example"}, "desc": {"value": "web development agency"},
             "listed": {"value": "false"}},
            {"item": {"value": "http://www.wikidata.org/entity/Q2"}, "itemLabel": {"value": "Bar"},
             "website": {"value": "https://bar.example"}, "listed": {"value": "true"}}]}}
        a, b = WikidataAdapter(ApiClient(transport=object()), limit=5).parse(data, "t")
        self.assertEqual(a.attrs["description"], "web development agency")
        self.assertNotIn("listed_on_exchange", a.attrs)
        self.assertTrue(b.attrs["listed_on_exchange"])

    def test_query_is_deterministic_and_stays_keyless_and_narrow(self):
        q = WikidataAdapter(ApiClient(transport=object()), limit=500).build_query()
        self.assertIn("ORDER BY ?item", q)
        self.assertIn("LIMIT 500", q)
        self.assertIn("schema:description", q)

    def test_enriched_query_rejection_falls_back_visibly_but_429_never_does(self):
        ok_ids = {"results": {"bindings": [
            {"q": {"value": "http://www.wikidata.org/entity/Q1058914"}, "l": {"value": "software company"}},
            {"q": {"value": "http://www.wikidata.org/entity/Q30"}, "l": {"value": "United States"}}]}}
        rows = {"results": {"bindings": [{"item": {"value": "http://www.wikidata.org/entity/Q9"},
                                           "itemLabel": {"value": "Foo"}, "website": {"value": "https://foo.example"}}]}}

        class Client:
            def __init__(self, fail):
                self.fail, self.queries = fail, []

            def request_json(self, method, url, form=None, accept=""):
                from urllib.parse import parse_qs, urlsplit
                q = parse_qs(urlsplit(url).query)["query"][0]
                self.queries.append(q)
                if "VALUES" in q:
                    return ok_ids
                if "schema:description" in q:
                    raise DiscoveryBlocked(self.fail)
                return rows

        c = Client("query.wikidata.org: HTTP 400 (no retry)")
        ad = WikidataAdapter(c, limit=5)
        self.assertEqual([x.name for x in ad.discover()], ["Foo"])
        self.assertIn("fell back", ad.run_note)
        c = Client("query.wikidata.org: HTTP 429 (no retry; respect rate controls)")
        with self.assertRaises(DiscoveryBlocked):
            WikidataAdapter(c, limit=5).discover()
        self.assertEqual(sum("schema:description" in q for q in c.queries), 1, "no second attempt on 429")

    def test_agency_like_records_are_researched_before_vendor_like_ones(self):
        pool = [self.cand(f"vendor{i}", description="cloud platform for enterprise teams", listed_on_exchange=True)
                for i in range(6)]
        pool += [self.cand("studio1", description="web development agency", employees=12),
                 self.cand("studio2", description="software consultancy")]
        chosen, info = select_with_reasons(pool, 2, "seed")
        self.assertEqual({c.name for c in chosen}, {"studio1", "studio2"})
        self.assertTrue(all(info[c.domain]["priority"] > 0 and info[c.domain]["reasons"] for c in chosen))

    def test_no_record_signals_keeps_the_original_seeded_hash_order(self):
        import hashlib
        pool = [Candidate(f"c{i}", f"https://c{i}.example", "manual", "manual_csv") for i in range(30)]
        expected = sorted(pool, key=lambda c: hashlib.sha256(f"s|{c.domain}".encode()).hexdigest())[:10]
        self.assertEqual([c.domain for c in select(pool, 10, "s")], [c.domain for c in expected])

    def test_prequalification_never_drops_when_pool_fits_the_cap(self):
        pool = [self.cand("a", description="cloud platform"), self.cand("b")]
        self.assertEqual(len(select(pool, 40, "s")), 2)

    def test_priority_uses_only_record_fields_and_is_explained(self):
        pri, why = prequalify({"description": "cloud platform", "employees": 5000, "listed_on_exchange": True})
        self.assertLess(pri, 0)
        self.assertEqual(len(why), 3)
        self.assertEqual(prequalify({}), (0, []))

    def test_coverage_counts_are_reported_not_assumed(self):
        pool = [self.cand("a", description="web development agency"), self.cand("b", description="cloud platform"),
                self.cand("c")]
        cov = coverage(pool)
        self.assertEqual((cov["pool"], cov["with_record_description"], cov["agency_like_description"],
                          cov["vendor_like_description"]), (3, 2, 1, 1))


if __name__ == "__main__":
    unittest.main()
