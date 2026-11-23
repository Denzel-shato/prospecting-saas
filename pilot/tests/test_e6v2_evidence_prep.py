"""Engine #6 V2 evidence preparation: synthetic pages only (fictional people and companies, no network)."""
import ast
import json
import subprocess
import sys
import unittest
from pathlib import Path

from tests.util import snap, team_snap
from vm1.e6v2 import PrepConfig, prepare_evidence, redact_contact_details
from vm1.evidence import PageSnapshot
from vm1.htmlparse import PageData

PKG = Path(__file__).resolve().parent.parent / "vm1"
E6V2 = PKG / "e6v2"

TEAM_HTML = """
<h1>Meet the Team</h1>
<div class="person"><div class="person-info-name">Jane Doe</div>
  <div class="person-info-title">Co-Founder &amp; CEO</div>
  <p>Email jane@acme.example or call +1 (555) 123-4567.</p></div>
<div class="person"><div class="person-info-name">John Roe</div>
  <div class="person-info-title">Head of Engineering</div></div>
<nav><a href="/team">Team</a><a href="/about">About</a></nav>
"""


def passages_text(result):
    return "\n".join(p.text for p in result.passages)


class SelectionAndProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.result = prepare_evidence([team_snap(TEAM_HTML)])

    def test_team_cards_are_selected_with_exact_text_url_and_headings(self):
        text = passages_text(self.result)
        for exact in ("Jane Doe", "Co-Founder & CEO", "John Roe", "Head of Engineering"):
            self.assertIn(exact, text)
        for p in self.result.passages:
            self.assertEqual(p.source_url, "https://x.example/team")
            self.assertEqual(p.page_kind, "team")
            self.assertEqual(p.fetched_at, "2026-11-21T00:00:00+00:00")
            self.assertEqual(p.headings, ("Meet the Team",))   # original casing restored, not the parser's lower-case
            self.assertTrue(p.block_indices)

    def test_name_and_title_of_one_card_stay_together_and_cards_do_not_mix(self):
        card = next(p for p in self.result.passages if "Jane Doe" in p.text)
        self.assertIn("Co-Founder & CEO", card.text)
        self.assertNotIn("John Roe", card.text)
        john = next(p for p in self.result.passages if "John Roe" in p.text)
        self.assertNotIn("Jane Doe", john.text)

    def test_navigation_is_removed(self):
        text = passages_text(self.result)
        self.assertNotIn("About", text.replace("Head of", ""))
        self.assertTrue(all("nav" not in p.context_labels for p in self.result.passages))

    def test_prose_founder_statement_on_about_page_is_selected_with_reasons(self):
        s = snap("<h1>About Us</h1><p>Northwind Studio was founded by Maria Silva in 2011 and builds web products.</p>",
                 "https://x.example/about", home=False)
        p = prepare_evidence([s]).passages[0]
        self.assertIn("founded by Maria Silva in 2011", p.text)
        self.assertIn("role_keyword", p.reasons)
        self.assertEqual(p.page_kind, "about")

    def test_irrelevant_pages_and_content_are_dropped(self):
        services = snap("<h1>Services</h1><p>We design mobile apps and APIs for startups.</p>",
                        "https://x.example/services", home=False)
        home = snap("<p>We ship software.</p><footer><p>© 2026 Acme</p></footer>")
        legal = snap("<p>Our President may amend these terms.</p>", "https://x.example/privacy", home=False)
        careers = snap("<p>We are hiring a Head of Design and a Director of Sales.</p>",
                       "https://x.example/careers", home=False)
        result = prepare_evidence([services, home, legal, careers])
        self.assertEqual(result.passages, ())
        self.assertEqual(result.stats["pages_skipped_by_kind"], {"careers": 1, "legal": 1})

    def test_boilerplate_and_contact_only_blocks_are_not_selected(self):
        s = team_snap("<h2>Our Team</h2><p>Jane Doe</p><p>Founder</p><p>LinkedIn</p><p>jane@acme.example</p>"
                      "<p>Phone: +44 20 7946 0958</p>")
        text = passages_text(prepare_evidence([s]))
        self.assertNotIn("LinkedIn", text)
        self.assertNotIn("Phone", text)
        self.assertIn("Jane Doe", text)

    def test_inputs_are_not_mutated(self):
        s = team_snap(TEAM_HTML)
        before = (list(s.page.blocks), list(s.page.people_blocks), list(s.page.block_section))
        prepare_evidence([s])
        self.assertEqual(before, (s.page.blocks, s.page.people_blocks, s.page.block_section))


class RedactionTests(unittest.TestCase):
    def test_emails_and_phones_are_removed_from_passages(self):
        result = prepare_evidence([team_snap(TEAM_HTML)])
        text = passages_text(result)
        for leaked in ("jane@acme.example", "555", "123-4567"):
            self.assertNotIn(leaked, text)
        self.assertEqual((result.stats["redacted_emails"], result.stats["redacted_phones"]), (1, 1))

    def test_redaction_forms(self):
        cases = {
            "Write to jane.doe+x@sub.acme.example today": "Write to [email removed] today",
            "jane [at] acme [dot] example": "[email removed]",
            "mailto:jane@acme.example": "[email removed]",
            "tel:+15551234567": "[phone removed]",
            "Call 020 7946 0958 now": "Call [phone removed] now",
            "Call +44 (0)20 7946 0958": "Call [phone removed]",
            "ID [redacted-email] here": "ID [email removed] here",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(redact_contact_details(raw), expected)

    def test_ordinary_numbers_and_years_are_not_phones(self):
        for text in ("Founded 2015-2020 with 120 people", "Raised $2,500,000 in 2019", "Team of 12 since 2011"):
            self.assertEqual(redact_contact_details(text), text)


class ThirdPartyContextTests(unittest.TestCase):
    def test_testimonial_attribution_is_kept_and_flagged(self):
        s = snap("<h2>What our clients say</h2><blockquote>They rebuilt our app.</blockquote>"
                 "<p>Sam Lee, CEO of Clientco</p>")
        result = prepare_evidence([s])
        p = next(p for p in result.passages if "Sam Lee" in p.text)
        self.assertIn("section:third_party", p.risk_flags)
        self.assertIn("adjacent_quote", p.risk_flags)
        self.assertGreaterEqual(result.stats["flagged_third_party"], 1)

    def test_blockquote_labels_are_visible_on_the_passage(self):
        s = snap("<blockquote><p>As CEO of Clientco I recommend them.</p></blockquote>")
        p = prepare_evidence([s]).passages[0]
        self.assertIn("quote", p.context_labels)
        self.assertIn("ctx:quote", p.risk_flags)

    def test_client_logo_grid_is_labelled(self):
        s = snap('<div class="client-logos"><p>Pat Kim, Founder of Logo Corp</p></div>')
        p = prepare_evidence([s]).passages[0]
        self.assertIn("client", p.context_labels)
        self.assertIn("ctx:client", p.risk_flags)

    def test_editorial_page_and_article_are_flagged(self):
        s = snap("<article><p>By Alex Poe, Founder of Blogco</p></article>", "https://x.example/blog/post-1", home=False)
        p = prepare_evidence([s]).passages[0]
        self.assertIn("page:editorial", p.risk_flags)
        self.assertIn("ctx:editorial", p.risk_flags)

    def test_clean_team_passage_has_no_risk_flags(self):
        p = prepare_evidence([team_snap("<h2>Our Team</h2><p>Jane Doe</p><p>Founder</p>")]).passages[0]
        self.assertEqual(p.risk_flags, ())

    def test_flat_adjacent_hits_do_not_share_context(self):
        s = snap("<p>Jane Doe</p><p>CEO</p><p>John Roe</p><p>CTO</p>")
        texts = [p.text for p in prepare_evidence([s]).passages]
        self.assertTrue(any("Jane Doe" in t and "CEO" in t for t in texts), texts)
        self.assertFalse(any("Jane Doe" in t and "John Roe" in t for t in texts), texts)

    def test_team_card_is_never_merged_with_following_testimonial(self):
        s = team_snap("<h2>Our Team</h2><p>Jane Doe, Founder</p><blockquote>Brilliant studio.</blockquote>")
        for p in prepare_evidence([s]).passages:
            self.assertFalse("Jane Doe" in p.text and "Brilliant studio" in p.text, p.text)

    def test_footer_is_kept_only_on_explicit_role_statement_and_is_flagged(self):
        s = snap("<footer><p>All rights reserved.</p><p>Built by Lee Wu, CTO of Webco</p></footer>")
        result = prepare_evidence([s])
        self.assertEqual(len(result.passages), 1)
        self.assertIn("ctx:footer", result.passages[0].risk_flags)

    def test_hand_built_page_without_context_is_flagged_unknown_not_clean(self):
        page = PageData(url="https://x.example/team", blocks=["Jane Doe", "Founder and CEO"])
        s = PageSnapshot(url=page.url, fetched_at="t0", page=page)
        result = prepare_evidence([s])
        self.assertTrue(result.passages)
        for p in result.passages:
            self.assertIn("context_unknown", p.risk_flags)


class PassageIdTests(unittest.TestCase):
    def test_ids_are_stable_unique_and_order_independent(self):
        a = team_snap(TEAM_HTML)
        b = snap("<h1>About</h1><p>Acme was founded by Maria Silva in 2011 and builds products.</p>",
                 "https://x.example/about", home=False)
        one = prepare_evidence([a, b])
        two = prepare_evidence([b, a])
        again = prepare_evidence([team_snap(TEAM_HTML), b])
        ids = [p.passage_id for p in one.passages]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {p.passage_id for p in two.passages})
        self.assertEqual(ids, [p.passage_id for p in again.passages])
        self.assertTrue(all(i.startswith("ps_") for i in ids))

    def test_id_depends_on_page_and_text_not_on_block_position(self):
        text = "<h2>Our Team</h2><p>Jane Doe</p><p>Founder</p>"
        def jane(result):
            return next(p for p in result.passages if "Jane Doe" in p.text)
        plain = jane(prepare_evidence([team_snap(text)]))
        shifted = jane(prepare_evidence([team_snap("<p>Welcome to our studio page.</p>" + text)]))
        other_page = jane(prepare_evidence([team_snap(text, "https://x.example/leadership")]))
        self.assertEqual(plain.passage_id, shifted.passage_id)
        self.assertNotEqual(plain.block_indices, shifted.block_indices)
        self.assertNotEqual(plain.passage_id, other_page.passage_id)

    def test_url_variants_of_the_same_page_share_an_id(self):
        text = "<h2>Our Team</h2><p>Jane Doe</p><p>Founder</p>"
        a = prepare_evidence([team_snap(text, "https://www.x.example/team/")]).passages[0]
        b = prepare_evidence([team_snap(text, "https://x.example/team")]).passages[0]
        self.assertEqual(a.passage_id, b.passage_id)


class DedupeTests(unittest.TestCase):
    def test_identical_text_on_two_pages_is_kept_once_on_the_preferred_page(self):
        block = "<h2>Our Team</h2><p>Jane Doe</p><p>Founder and CEO</p>"
        home = snap(block)
        team = team_snap(block)
        result = prepare_evidence([home, team])
        self.assertEqual(len(result.passages), 1)
        p = result.passages[0]
        self.assertEqual(p.source_url, "https://x.example/team")
        self.assertEqual(p.also_seen_at, ("https://x.example/",))
        self.assertGreaterEqual(result.stats["duplicates_removed"], 1)

    def test_repeated_cards_on_one_page_collapse(self):
        card = "<div class='person'><p>Jane Doe</p><p>Founder</p></div>"
        result = prepare_evidence([team_snap("<h2>Team</h2>" + card + card + card)])
        self.assertEqual(sum("Jane Doe" in p.text for p in result.passages), 1)

    def test_prose_view_and_card_view_of_the_same_text_are_not_both_emitted(self):
        result = prepare_evidence([team_snap(TEAM_HTML)])
        self.assertEqual(sum("Jane Doe" in p.text for p in result.passages), 1)


class SizeLimitTests(unittest.TestCase):
    LONG = ("Our studio has delivered many projects across industries and continents with a focus on craft. " * 8
            + "The company was founded by Maria Silva in 2011.")

    def test_long_block_is_split_without_losing_the_founder_sentence(self):
        s = snap(f"<h1>About us</h1><p>{self.LONG}</p>", "https://x.example/about", home=False)
        cfg = PrepConfig(max_passage_chars=300, max_passages_per_page=50, max_passages=50, max_total_chars=50_000)
        result = prepare_evidence([s], cfg)
        self.assertTrue(all(len(p.text) <= 300 for p in result.passages))
        hit = [p for p in result.passages if "founded by Maria Silva in 2011." in p.text]
        self.assertEqual(len(hit), 1)
        self.assertIn("role_keyword", hit[0].reasons)

    def test_every_passage_respects_max_passage_chars(self):
        cfg = PrepConfig(max_passage_chars=120, max_passages_per_page=99, max_passages=99, max_total_chars=99_999)
        result = prepare_evidence([team_snap(f"<h2>Team</h2><p>{self.LONG}</p><p>Jane Doe</p><p>Founder</p>")], cfg)
        self.assertTrue(result.passages)
        self.assertTrue(all(len(p.text) <= 120 for p in result.passages))

    def test_unbreakable_token_is_hard_split(self):
        cfg = PrepConfig(max_passage_chars=60, max_passages_per_page=99, max_passages=99, max_total_chars=99_999)
        token = "".join(chr(97 + i % 26) + chr(65 + i % 7) for i in range(100))   # 200 chars, no repeated chunks
        result = prepare_evidence([team_snap("<p>Founder " + token + "</p>")], cfg)
        self.assertTrue(all(len(p.text) <= 60 for p in result.passages))
        self.assertEqual("".join(p.text for p in result.passages).replace("Founder", "").replace(" ", ""), token)

    def cards(self, n):
        return "<h2>Team</h2>" + "".join(f"<div class='person'><p>Person Number{i}</p><p>Director of Ops</p></div>"
                                          for i in range(n))

    def test_per_page_limit_and_stats(self):
        cfg = PrepConfig(max_passages_per_page=3, context_before=0, context_after=0)
        result = prepare_evidence([team_snap(self.cards(10))], cfg)
        self.assertEqual(len(result.passages), 3)
        self.assertGreater(result.stats["dropped_by_limit"]["per_page"], 0)

    def test_total_passage_limit(self):
        cfg = PrepConfig(max_passages=2, max_passages_per_page=10, context_before=0, context_after=0)
        pages = [team_snap(self.cards(4), f"https://x.example/team-{i}") for i in range(3)]
        result = prepare_evidence(pages, cfg)
        self.assertEqual(len(result.passages), 2)
        self.assertGreater(result.stats["dropped_by_limit"]["total_passages"], 0)

    def test_total_char_limit(self):
        cfg = PrepConfig(max_total_chars=120, max_passages_per_page=50, max_passages=50, context_before=0,
                         context_after=0)
        result = prepare_evidence([team_snap(self.cards(10))], cfg)
        self.assertLessEqual(result.stats["total_chars"], 120)
        self.assertGreater(result.stats["dropped_by_limit"]["total_chars"], 0)

    def test_clean_passages_survive_limits_before_third_party_ones(self):
        s = team_snap("<h2>Our Team</h2><p>Jane Doe</p><p>Founder</p>"
                      "<h2>Clients</h2><p>Ann Gray, CEO of Bigco</p>")
        result = prepare_evidence([s], PrepConfig(max_passages=1))
        self.assertEqual(len(result.passages), 1)
        self.assertEqual(result.passages[0].risk_flags, ())

    def test_config_validation(self):
        for bad in ({"max_passage_chars": 0}, {"max_passages": -1}, {"max_total_chars": True},
                    {"max_passage_chars": 10}, {"context_before": -1}, {"max_passages_per_page": 1.5}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                PrepConfig(**bad)

    def test_excluded_page_kinds_is_configurable(self):
        careers = snap("<p>Our CEO, Jane Doe, leads hiring.</p>", "https://x.example/careers", home=False)
        self.assertEqual(prepare_evidence([careers]).passages, ())
        allowed = prepare_evidence([careers], PrepConfig(excluded_page_kinds=frozenset()))
        self.assertEqual(len(allowed.passages), 1)


class OutputShapeAndIsolationTests(unittest.TestCase):
    def test_result_is_json_serialisable_and_deterministic(self):
        pages = [team_snap(TEAM_HTML), snap("<p>Founded by Eve Lin.</p>")]
        first = json.dumps(prepare_evidence(pages).to_dict(), sort_keys=True)
        second = json.dumps(prepare_evidence(pages).to_dict(), sort_keys=True)
        self.assertEqual(first, second)

    def test_empty_input(self):
        result = prepare_evidence([])
        self.assertEqual(result.passages, ())
        self.assertEqual(result.stats["pages_seen"], 0)

    def test_package_is_stdlib_plus_existing_read_only_modules_only(self):
        allowed_vm1 = {"context", "evidence", "htmlparse", "pageselect", "evidence_prep"}
        for path in E6V2.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertIn(alias.name.split(".")[0], sys.stdlib_module_names, (path.name, alias.name))
                elif isinstance(node, ast.ImportFrom):
                    if node.level == 0:
                        self.assertIn((node.module or "").split(".")[0], sys.stdlib_module_names, path.name)
                    elif node.level == 2:
                        self.assertIn((node.module or "").split(".")[0], allowed_vm1, (path.name, node.module))
                    else:
                        self.assertIn((node.module or "").split(".")[0], {"evidence_prep"}, path.name)

    def test_no_ai_or_network_code_in_package(self):
        for path in E6V2.glob("*.py"):
            src = path.read_text(encoding="utf-8")
            for token in ("urllib.request", "http.client", "socket", "vm1.ai", "..ai", "os.environ", "open("):
                self.assertNotIn(token, src, f"{path.name} contains {token}")

    def test_existing_modules_do_not_import_the_package(self):
        for path in sorted(PKG.glob("*.py")):
            src = path.read_text(encoding="utf-8")
            self.assertNotIn("e6v2", src, f"{path.name} references e6v2")

    def test_import_and_run_do_no_network_io_in_a_fresh_interpreter(self):
        code = (
            "import socket, sys\n"
            "def boom(*a, **k): raise AssertionError('network attempted')\n"
            "socket.socket.connect = boom; socket.getaddrinfo = boom; socket.create_connection = boom\n"
            f"sys.path.insert(0, {str(PKG.parent)!r})\n"
            "from vm1.e6v2 import prepare_evidence\n"
            "from vm1.evidence import PageSnapshot\n"
            "from vm1.htmlparse import parse_html\n"
            "page = parse_html('<h1>Team</h1><p>Jane Doe</p><p>Founder</p>', 'https://x.example/team')\n"
            "r = prepare_evidence([PageSnapshot(url=page.url, fetched_at='t', page=page)])\n"
            "print('ok', len(r.passages))\n"
        )
        proc = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("ok 1", proc.stdout)


if __name__ == "__main__":
    unittest.main()
