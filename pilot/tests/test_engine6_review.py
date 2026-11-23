"""Fictional regressions, not measured live coverage."""
import unittest
import json
from types import SimpleNamespace
from vm1.evidence import verify_excerpt_parts
from vm1.pipeline import fetch_secondary_pages
from vm1.pageselect import rank_candidates
from vm1.policy import load_policy
from tests.util import snap
from vm1.people import find_decision_makers
from vm1.pageselect import classify_link

def people(body):
    return find_decision_makers([snap(body, 'https://acme.example/team', False)],
                                company_key='acme.example', company_name='Acme Studio')

class Engine6Review(unittest.TestCase):
    def test_adjacent_cards_do_not_exchange_titles(self):
        self.assertEqual(people('<div><span>Jane Doe</span></div><div><span>CEO</span></div>'), [])
    def test_inline_card_fields(self):
        self.assertEqual(people('<div><span>Jane Doe</span><span>CEO</span></div>')[0].name, 'Jane Doe')

    def test_realistic_nested_person_card_keeps_name_and_title_together(self):
        # Reconstructed from a live first-party team page. The photo field,
        # separate name/title divs and social links must not hide a known CEO.
        html = (
            '<div class="basic-grid__4-col person">'
            '<div class="person-photo-frame"><img alt="Chad Pytel" src="/image.png"></div>'
            '<div class="person-info-name">Chad Pytel</div>'
            '<div class="person-info-title">Developer and CEO</div>'
            '<div class="social-links"><a href="/social">GitHub</a></div>'
            '</div>'
        )
        found = people(html)
        self.assertEqual([(p.name, p.title, p.basis) for p in found],
                         [('Chad Pytel', 'Developer and CEO', 'team_page')])
        self.assertTrue(all(verify_excerpt_parts(p.excerpt_parts, snap(html, 'https://acme.example/team').page)
                            for p in found))

    def test_semantic_fields_in_separate_person_cards_are_not_paired(self):
        html = (
            '<div class="person"><div class="person-info-name">Jane Doe</div></div>'
            '<div class="person"><div class="person-info-title">CEO</div></div>'
        )
        self.assertEqual(people(html), [])

    def test_semantic_fields_without_person_card_are_not_paired(self):
        html = (
            '<div class="person-info-name">Jane Doe</div>'
            '<div class="person-info-title">CEO</div>'
        )
        self.assertEqual(people(html), [])

    def test_semantic_person_card_in_testimonial_is_rejected(self):
        html = (
            '<div class="testimonial"><div class="person">'
            '<div class="person-info-name">Jane Doe</div>'
            '<div class="person-info-title">CEO</div>'
            '</div></div>'
        )
        self.assertEqual(people(html), [])

    def test_semantic_person_card_in_editorial_is_rejected(self):
        html = (
            '<div class="blog"><div class="person">'
            '<div class="person-info-name">Jane Doe</div>'
            '<div class="person-info-title">CEO</div>'
            '</div></div>'
        )
        self.assertEqual(people(html), [])

    def test_person_article_and_editorial_veto(self):
        body = '<article itemtype="https://schema.org/Person"><h3>Jane Doe</h3><p>CEO</p></article>'
        self.assertEqual(people(body)[0].name, 'Jane Doe')
        self.assertEqual(people('<div class="testimonial">'+body+'</div>'), [])
        self.assertEqual(people(body.replace('<article ', '<article class="blog" ')), [])
        self.assertEqual(people(body.replace('<article ', '<article id="blog" ')), [])
        self.assertEqual(people(body.replace('<article ', '<article itemprop="author" ')), [])
        self.assertEqual(people('<article><h3>Jane Doe</h3><p>CEO</p></article>'), [])

    def test_team_list_article_with_nested_fields_recovers_executive(self):
        # Reconstructed from Happy Cog's captured About page structure.
        html = (
            '<h2>Team</h2><ul><li><article class="grid gap-5 group">'
            '<div><p>Lee Goldberg</p></div>'
            '<div><p>Co-Founder and President, Marketing &amp; Strategy</p></div>'
            '</article></li></ul>'
        )
        found = people(html)
        self.assertEqual([(p.name, p.title) for p in found],
                         [('Lee Goldberg', 'Co-Founder and President, Marketing & Strategy')])
        self.assertTrue(verify_excerpt_parts(found[0].excerpt_parts,
                                              snap(html, 'https://acme.example/team').page))

    def test_generic_article_without_team_list_stays_rejected(self):
        self.assertEqual(people('<h2>Team</h2><article>'
                                '<div>Jane Doe</div><div>CEO</div></article>'), [])
        self.assertEqual(people('<h2>Company</h2><ul><li><article>'
                                '<div>Jane Doe</div><div>CEO</div></article></li></ul>'), [])

    def test_team_list_article_editorial_and_testimonial_are_still_rejected(self):
        for kind in ('blog', 'testimonial', 'client', 'author'):
            html = ('<h2>Team</h2><ul><li><article class="' + kind + '">'
                    '<div><p>Jane Doe</p></div><div><p>CEO</p></div>'
                    '</article></li></ul>')
            self.assertEqual(people(html), [], kind)

    def test_team_list_articles_keep_separate_person_boundaries(self):
        html = (
            '<h2>Team</h2><ul>'
            '<li><article><div><p>Jane Doe</p></div></article></li>'
            '<li><article><div><p>CEO</p></div></article></li>'
            '</ul>'
        )
        self.assertEqual(people(html), [])

    def test_team_list_article_in_client_subsection_stays_rejected(self):
        html = (
            '<h2>Team</h2><h3>Our Clients</h3>'
            '<ul><li><article><div><p>Jane Doe</p></div>'
            '<div><p>CEO</p></div></article></li></ul>'
        )
        self.assertEqual(people(html), [])

    def test_wordpress_structural_classes_do_not_veto_own_team_bio(self):
        # MindSea's captured body and content wrapper used these two WP classes.
        html = (
            '<body class="wp-singular page-template-default wp-custom-logo wp-theme-mindsea">'
            '<div class="entry-content wp-block-post-content is-layout-flow">'
            '<h2>Meet the Team</h2><h3>Leadership</h3>'
            '<h4>Reuben Hall</h4>'
            '<p>Chief Executive Officer • Halifax, NS</p>'
            '<p>Reuben Hall is the CEO of Acme Studio, a digital product agency.</p>'
            '</div></body>'
        )
        self.assertEqual([(p.name, p.title) for p in people(html)],
                         [('Reuben Hall', 'CEO')])

    def test_actual_testimonial_and_post_author_classes_still_veto(self):
        for kind in ('client-logo', 'post-author', 'testimonial'):
            html = ('<h2>Team</h2><div class="' + kind + '">'
                    '<p>Jane Doe is the CEO of Acme Studio.</p></div>')
            self.assertEqual(people(html), [], kind)

    def test_graph_affiliation_and_reference_cycles(self):
        graph = {'@graph': [
            {'@id': '#org', '@type': 'Organization', 'name': 'Acme Studio', 'employee': {'@id':'#person'}},
            {'@id': '#person', '@type': 'Person', 'name':'Jane Doe', 'jobTitle':'CEO', 'worksFor':{'@id':'#org'}}]}
        self.assertEqual([p.name for p in people('<script type="application/ld+json">'+json.dumps(graph)+'</script>')], ['Jane Doe'])
        graph['@graph'][0]['name'] = 'Other Studio'
        self.assertEqual(people('<script type="application/ld+json">'+json.dumps(graph)+'</script>'), [])

    def test_unresolved_and_conflicting_graph_ids_are_unknown(self):
        graph = {'@graph': [
            {'@id':'#p', '@type':'Person', 'name':'Jane Doe', 'jobTitle':'CEO', 'worksFor':{'@id':'#org'}},
            {'@id':'#org', '@type':'Organization', 'name':'Acme Studio'},
            {'@id':'#org', '@type':'Organization', 'name':'Other Studio'}]}
        self.assertEqual(people('<script type="application/ld+json">'+json.dumps(graph)+'</script>'), [])

    def test_unicode_structured_evidence_survives_verification(self):
        data = {'@type': 'Organization', 'name': 'Acme Studio',
                'founder': {'@type': 'Person', 'name': 'José García', 'jobTitle': 'Founder'}}
        page = snap('<script type="application/ld+json">' + json.dumps(data) + '</script>')
        found = find_decision_makers([page], company_key='acme.example', company_name='Acme Studio')
        self.assertEqual(len(found), 1)
        self.assertTrue(verify_excerpt_parts(found[0].excerpt_parts, page.page))

    def test_explicit_other_employer_overrides_parent(self):
        data = {'@type': 'Organization', 'name': 'Acme Studio',
                'employee': {'@type': 'Person', 'name': 'Jane Doe', 'jobTitle': 'CEO',
                             'worksFor': {'name': 'Other Studio'}}}
        self.assertEqual(people('<script type="application/ld+json">' + json.dumps(data) + '</script>'), [])

    def test_about_link_followed_inside_budget(self):
        home = 'https://acme.example/'
        calls = []
        class Fetcher:
            def fetch(self, url):
                calls.append(url)
                return SimpleNamespace(ok=True, final_url=url, text='<a href="/about/team">Team</a>')
        policy = load_policy('icp/frontend-studio-worldwide.json').page_selection
        ranked = rank_candidates([(home+'about', 'About'), (home+'services', 'Services')], home, policy)
        list(fetch_secondary_pages(Fetcher(), home, ranked, 3, policy))
        self.assertEqual(calls, [home+'services', home+'about', home+'about/team'])
        calls.clear()
        ranked = rank_candidates([(home+'about', 'About'), (home+'services', 'Services')], home, policy)
        list(fetch_secondary_pages(Fetcher(), home, ranked, 2, policy))
        self.assertEqual(len(calls), 2)

    def test_prefix_is_not_company_identity(self):
        self.assertEqual(people('<p>Jane Doe, CEO at Acme Capital</p>'), [])

    def test_engineering_vp_is_not_ceo(self):
        self.assertEqual(people('<p>Jane Doe, Vice President of Engineering</p>')[0].role_class, 'cto_eng')

    def test_shorter_founder_title_wins(self):
        self.assertEqual(people('<p>Jane Doe, Head of Engineering</p><p>Jane Doe, Founder</p>')[0].title, 'Founder')

    def test_malformed_schema_type_is_ignored(self):
        self.assertEqual(people('<script type="application/ld+json">{"@type":[{}]}</script>'), [])

    def test_nested_leadership_is_team(self):
        self.assertEqual(classify_link('https://acme.example/about/team', 'Team')[0], 'team')

    def test_testimonials_still_rejected(self):
        self.assertEqual(people('<div class="testimonial"><p>Jane Doe, CEO</p></div>'), [])
