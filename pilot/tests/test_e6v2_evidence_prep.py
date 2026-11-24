"""HTML semantic context classification regressions (synthetic markup only)."""
import unittest

from vm1.htmlparse import parse_html


def context_for(html, url, needle):
    page = parse_html(html, url)
    for i, text in enumerate(page.blocks):
        if needle in text:
            return page.ctx_at(i)
    raise AssertionError(f"no block containing {needle!r}: {page.blocks!r}")


class ArticleSemanticsTests(unittest.TestCase):
    def test_wordpress_static_page_article_wrappers_are_not_editorial(self):
        fixtures = (
            ('<article class="post-type-page" id="post-697"><p>Andrew Ajoodha</p></article>',
             "https://wirebox.example/about-us/", "Andrew Ajoodha"),
            ('<article class="post-2265 page type-page status-publish ast-article-single" '
             'itemtype="https://schema.org/CreativeWork"><p>Gregory Cerallo</p></article>',
             "https://sidekick.example/conference/", "Gregory Cerallo"),
        )
        for html, url, needle in fixtures:
            with self.subTest(url=url):
                ctx = context_for(html, url, needle)
                self.assertNotIn("editorial", ctx)
                self.assertNotIn("client", ctx)

    def test_numeric_wordpress_post_id_is_not_editorial_evidence(self):
        html = '<article class="post-2265"><p>Jane Doe</p></article>'
        self.assertNotIn("editorial", context_for(html, "https://x.example/about/", "Jane Doe"))

    def test_generic_article_is_not_automatically_editorial(self):
        html = '<article><p>Jane Doe, Founder</p></article>'
        self.assertNotIn("editorial", context_for(html, "https://x.example/about/", "Jane Doe"))

    def test_blog_path_and_explicit_post_class_remain_editorial(self):
        self.assertIn("editorial", context_for(
            "<article><p>By Jane Doe</p></article>", "https://x.example/blog/launch/", "Jane Doe"))
        self.assertIn("editorial", context_for(
            '<article class="post type-post"><p>By Jane Doe</p></article>',
            "https://x.example/updates/", "Jane Doe"))

    def test_schema_article_is_editorial_but_generic_creative_work_is_not(self):
        article = '<article itemtype="https://schema.org/BlogPosting"><p>By Jane Doe</p></article>'
        creative = '<article itemtype="https://schema.org/CreativeWork"><p>Jane Doe</p></article>'
        self.assertIn("editorial", context_for(article, "https://x.example/page/", "Jane Doe"))
        self.assertNotIn("editorial", context_for(creative, "https://x.example/page/", "Jane Doe"))

    def test_page_level_open_graph_and_jsonld_article_metadata_are_honoured(self):
        og = ('<head><meta property="og:type" content="article"></head><body><p>Jane Doe</p></body>')
        self.assertIn("editorial", context_for(og, "https://x.example/updates/", "Jane Doe"))
        ld = ('<script type="application/ld+json">{"@context":"https://schema.org",'
              '"@type":"Article","headline":"News"}</script><p>Jane Doe</p>')
        self.assertIn("editorial", context_for(ld, "https://x.example/page/", "Jane Doe"))
        generic = ('<script type="application/ld+json">{"@type":"CreativeWork","name":"Work"}</script>'
                   '<p>Jane Doe</p>')
        self.assertNotIn("editorial", context_for(generic, "https://x.example/page/", "Jane Doe"))


class ClientBrandSemanticsTests(unittest.TestCase):
    def test_brand_colour_utility_is_not_client_context(self):
        html = '<section class="relative bg-brand-white"><p>Agustin Guerra</p></section>'
        self.assertNotIn("client", context_for(html, "https://x.example/about/", "Agustin Guerra"))

    def test_site_logo_classes_are_not_client_context(self):
        html = ('<body class="wp-custom-logo"><header class="site-logo custom-logo">'
                '<p>Acme Studio</p></header></body>')
        self.assertNotIn("client", context_for(html, "https://x.example/", "Acme Studio"))

    def test_semantic_client_logo_collections_remain_flagged(self):
        for cls in ("client-logos", "customer-logo-grid", "partner-grid", "brand-grid", "logo-wall"):
            with self.subTest(cls=cls):
                html = f'<section class="{cls}"><p>Jane Doe, CEO of Acme</p></section>'
                self.assertIn("client", context_for(html, "https://x.example/about/", "Jane Doe"))


class ConferenceSpeakerBoundaryTests(unittest.TestCase):
    def test_static_wordpress_conference_page_keeps_speaker_context(self):
        html = (
            '<body class="wp-singular page-template-default page page-id-2265 wp-custom-logo '
            'wp-embed-responsive wp-theme-astra wp-child-theme-astra-child ast-desktop" '
            'itemtype="https://schema.org/WebPage">'
            '<article class="post-2265 page type-page status-publish ast-article-single" '
            'itemtype="https://schema.org/CreativeWork">'
            '<div class="speaker-profile"><p>Gregory Cerallo</p><p>Founder and CEO</p></div>'
            '</article></body>'
        )
        ctx = context_for(html, "https://x.example/conference/", "Gregory Cerallo")
        self.assertIn("editorial", ctx)
        self.assertNotIn("client", ctx)


if __name__ == "__main__":
    unittest.main()
