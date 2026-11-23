"""Decision-maker pattern regressions: names that must be found, wrong-company names that must not, and absences."""

import json
import unittest

from tests.util import snap
from vm1.people import find_decision_makers

TEAM, ABOUT, HOME, BLOG = ("https://acme.example/team", "https://acme.example/about",
                           "https://acme.example/", "https://acme.example/blog/why-we-build")


def dms(html, url=TEAM, home=False):
    return find_decision_makers([snap(html, url, home)], company_key="acme.example", company_name="Acme Studio")


def pairs(html, **kw):
    return [(d.name, d.role_class, d.basis) for d in dms(html, **kw)]


class FoundPatterns(unittest.TestCase):
    def test_prose_self_description_with_matching_company(self):
        self.assertEqual(pairs("<p>Jane Doe is the founder and CEO of Acme Studio.</p>", url=ABOUT),
                         [("Jane Doe", "founder_ceo", "explicit_org_match")])
        self.assertEqual(pairs("<p>Hi, I'm Jane Doe, owner of Acme Studio.</p>", url=ABOUT)[0][:2],
                         ("Jane Doe", "founder_ceo"))

    def test_founded_by(self):
        self.assertEqual(pairs("<p>Acme Studio was founded by Jane Doe in 2015.</p>", url=ABOUT),
                         [("Jane Doe", "founder_ceo", "explicit_org_match")])

    def test_title_block_before_name_block_on_team_page(self):
        self.assertEqual(pairs("<h2>Our team</h2><p>Founder</p><p>Jane Doe</p>")[0][:2], ("Jane Doe", "founder_ceo"))

    def test_accented_and_particle_names(self):
        self.assertEqual(dms("<h2>Team</h2><p>José García, Founder</p>")[0].name, "José García")
        self.assertEqual(dms("<h2>Team</h2><p>Jan van der Berg, Managing Director</p>")[0].name, "Jan van der Berg")

    def test_extra_title_words_and_variants(self):
        self.assertEqual(dms("<h2>Team</h2><p>Jane Doe, Founder &amp; Creative Director</p>")[0].role_class, "founder_ceo")
        for title in ("Chief Executive", "Founding Partner", "Co-Owner"):
            self.assertEqual(dms(f"<h2>Team</h2><p>Jane Doe, {title}</p>")[0].role_class, "founder_ceo", title)

    def test_spaced_co_founder_title_on_about_leadership_page(self):
        html = ('<section><h2>Meet Our Leadership Team</h2>'
                '<div><span>Scott Weisman</span><span>Co Founder &amp; CEO</span></div>'
                '<div><span>Ryan Francis</span><span>Head of Sales</span></div></section>')
        found = dms(html, url=ABOUT)
        self.assertEqual([(p.name, p.role_class) for p in found],
                         [("Scott Weisman", "founder_ceo")])
        self.assertIn("Co Founder", found[0].title)

    def test_developer_and_ceo_title_when_fields_are_adjacent(self):
        html = '<section><h2>Our Team</h2><div><span>Chad Pytel</span><span>Developer and CEO</span></div></section>'
        found = dms(html)
        self.assertEqual([(p.name, p.role_class) for p in found],
                         [("Chad Pytel", "founder_ceo")])

    def test_technical_role_alone_does_not_become_decision_maker(self):
        self.assertEqual(dms('<h2>Team</h2><p>Jane Doe</p><p>Developer</p>'), [])

    def test_partner_first_ceo_title_on_realistic_team_card(self):
        html = (
            '<h2>Our Team of tech strategists, designers, engineers, experts & investors</h2>'
            '<div class="all-team"><div class="team-wrapper">'
            '<div class="team-member" data-name="Kevin Yamazaki1">'
            '<div class="team-img"><img src="/kevin.png" alt="Kevin Yamazaki"/></div>'
            '<p class="emp-name"><span class="first-name">Kevin Yamazaki</span></p>'
            '<span class="job-title">Partner, CEO</span>'
            '</div><div class="team-member"><span>Alex Sample</span>'
            '<span>Senior Architect</span></div></div></div>'
        )
        found = dms(html, url=ABOUT)
        self.assertEqual([(p.name, p.title, p.role_class) for p in found],
                         [("Kevin Yamazaki", "Partner, CEO", "founder_ceo")])

    def test_partner_first_cto_and_no_title_only_partner(self):
        self.assertEqual(dms('<h2>Our Team</h2><p>Jane Doe, Partner, CTO</p>')[0].role_class, "cto_eng")
        self.assertEqual(dms('<h2>Our Team</h2><p>Jane Doe</p><p>Partner</p>'), [])

    def test_jsonld_founder_of_matching_organisation(self):
        ld = {"@type": "Organization", "name": "Acme Studio",
              "founder": {"@type": "Person", "name": "José García", "jobTitle": "Founder"}}
        html = f'<script type="application/ld+json">{json.dumps(ld)}</script><p>Home</p>'
        self.assertEqual([d.name for d in dms(html, url=HOME, home=True)], ["José García"])


class WrongCompanyAndTestimonials(unittest.TestCase):
    def test_other_company_is_never_attributed(self):
        self.assertEqual(dms("<p>Jane Doe is the founder and CEO of Clientco.</p>", url=ABOUT), [])
        self.assertEqual(dms("<p>Clientco was founded by Jane Doe in 2012.</p>", url=ABOUT), [])
        self.assertEqual(dms("<h2>Team</h2><p>Jane Doe, CEO at Other Corp</p>"), [])
        ld = {"@type": "Organization", "name": "Clientco",
              "founder": {"@type": "Person", "name": "Jane Doe", "jobTitle": "Founder"}}
        self.assertEqual(dms(f'<script type="application/ld+json">{json.dumps(ld)}</script>', url=HOME, home=True), [])

    def test_testimonial_blog_and_quote_prose_rejected(self):
        self.assertEqual(dms("<blockquote>Great.</blockquote><p>Jane Doe is the CEO of Acme Studio.</p>", url=HOME, home=True), [])
        self.assertEqual(dms('<div class="testimonial"><p>Jane Doe is the CEO of Acme Studio.</p></div>', url=HOME, home=True), [])
        self.assertEqual(dms("<p>Jane Doe is the founder and CEO of Acme Studio.</p>", url=BLOG), [])

    def test_name_first_card_is_not_stolen_by_reversed_layout(self):
        got = dms("<h3>John Example</h3><p>Co-Founder / Partner</p><h3>Jane Example</h3><p>Partner</p>")
        self.assertEqual([d.name for d in got], ["John Example"])


class NonPersonLabels(unittest.TestCase):
    def test_level_ownership_not_a_person(self):
        self.assertEqual(dms("<h2>Our Team</h2><p>Level Ownership, Founder</p>"), [])
        self.assertEqual(dms("<h2>Our Team</h2><p>Founder</p><p>Level Ownership</p>"), [])

class MissingStaysMissing(unittest.TestCase):
    def test_role_without_company_tie_is_unknown(self):
        self.assertEqual(dms("<p>Jane Doe is the founder.</p>", url=HOME, home=True), [])  # homepage, no org
        self.assertEqual(dms("<p>We are a studio founded in 2015.</p>", url=ABOUT), [])  # no name: nothing invented

    def test_no_contact_details_extracted(self):
        d = dms("<h2>Team</h2><p>Jane Doe, Founder</p><p>jane@acme.example</p>")[0]
        self.assertNotIn("@", d.excerpt + d.name + d.title)


if __name__ == "__main__":
    unittest.main()
