import unittest

import tests.util as u
from vm1.fetch import PoliteFetcher, RawResponse
from vm1.netsafe import UnsafeURL, is_public_ip, validate_url

PUB = u.resolver({"good.example": ["93.184.216.34"], "other.example": ["93.184.216.35"],
                  "evil.example": ["10.0.0.5"], "mixed.example": ["93.184.216.34", "192.168.1.1"],
                  "v6.example": ["2606:2800:220:1:248:1893:25c8:1946"], "v6loop.example": ["::1"],
                  "mapped.example": ["::ffff:127.0.0.1"], "meta.example": ["169.254.169.254"]})


class ScriptedTransport:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def request(self, method, target, headers, body, timeout, max_bytes):
        self.calls.append(target.url)
        r = self.routes.get(target.url)
        if r is None:
            return RawResponse(404, {"content-type": "text/html"}, b"")
        return r


def html(body="<p>hi</p>"):
    return RawResponse(200, {"content-type": "text/html"}, f"<html><body>{body}</body></html>".encode())


def fetcher(routes, **kw):
    t = ScriptedTransport(routes)
    return PoliteFetcher(t, PUB, min_delay=0, sleep=lambda s: None, **kw), t


class SsrfTests(unittest.TestCase):
    def test_rejects_bad_urls(self):
        bad = ["ftp://good.example/", "file:///etc/passwd", "http://127.0.0.1/", "http://[::1]/",
               "http://169.254.169.254/latest/meta-data", "http://user:pw@good.example/",
               "http://good.example:8080/", "http://localhost/", "http://printer.local/", "http://intranet/",
               "javascript:alert(1)", "http://evil.example/", "http://mixed.example/", "http://meta.example/",
               "http://v6loop.example/", "http://mapped.example/", "http://unresolvable.example/",
               "http://2130706433/", "http:///nohost"]
        for url in bad:
            with self.assertRaises(UnsafeURL, msg=url):
                validate_url(url, PUB)

    def test_accepts_public(self):
        t = validate_url("https://good.example/a?b=1#frag", PUB)
        self.assertEqual((t.host, t.port, t.path, t.ips), ("good.example", 443, "/a?b=1", ("93.184.216.34",)))
        self.assertEqual(validate_url("http://v6.example/", PUB).port, 80)

    def test_is_public_ip(self):
        for ip in ("8.8.8.8", "93.184.216.34"):
            self.assertTrue(is_public_ip(ip))
        for ip in ("10.1.1.1", "127.0.0.1", "169.254.1.1", "192.168.0.1", "172.16.0.1", "100.64.0.1",
                   "0.0.0.0", "224.0.0.1", "::1", "fe80::1", "fc00::1", "::ffff:10.0.0.1", "not-an-ip"):
            self.assertFalse(is_public_ip(ip), ip)

    def test_fetch_blocks_redirect_to_private_address(self):
        f, t = fetcher({"https://good.example/": RawResponse(301, {"location": "http://evil.example/"}, b"")})
        r = f.fetch("https://good.example/")
        self.assertFalse(r.ok)
        self.assertTrue(r.error.startswith("unsafe_redirect"), r.error)
        self.assertNotIn("http://evil.example/", t.calls, "must never connect to the private target")

    def test_fetch_blocks_redirect_to_metadata_literal(self):
        f, t = fetcher({"https://good.example/": RawResponse(302, {"location": "http://169.254.169.254/"}, b"")})
        self.assertTrue(f.fetch("https://good.example/").error.startswith("unsafe_redirect"))

    def test_offsite_redirect_refused(self):
        f, t = fetcher({"https://good.example/": RawResponse(301, {"location": "https://other.example/"}, b"")})
        self.assertEqual(f.fetch("https://good.example/").error, "offsite_redirect")

    def test_same_site_redirect_followed(self):
        f, t = fetcher({"https://good.example/": RawResponse(301, {"location": "/home"}, b""),
                        "https://good.example/home": html("<p>welcome</p>")})
        r = f.fetch("https://good.example/")
        self.assertTrue(r.ok)
        self.assertEqual(r.final_url, "https://good.example/home")

    def test_redirect_loop_capped(self):
        f, t = fetcher({"https://good.example/": RawResponse(301, {"location": "/"}, b"")}, max_redirects=3)
        self.assertEqual(f.fetch("https://good.example/").error, "too_many_redirects")


class RobotsTests(unittest.TestCase):
    ROBOTS = "https://good.example/robots.txt"

    def robots(self, text, status=200):
        return RawResponse(status, {"content-type": "text/plain"}, text.encode())

    def test_disallow_all_blocks_without_fetching_page(self):
        f, t = fetcher({self.ROBOTS: self.robots("User-agent: *\nDisallow: /"), "https://good.example/": html()})
        r = f.fetch("https://good.example/")
        self.assertEqual((r.ok, r.robots_allowed), (False, False))
        self.assertNotIn("https://good.example/", t.calls)

    def test_path_specific_disallow(self):
        f, t = fetcher({self.ROBOTS: self.robots("User-agent: *\nDisallow: /team"),
                        "https://good.example/": html(), "https://good.example/team": html()})
        self.assertTrue(f.fetch("https://good.example/").ok)
        self.assertFalse(f.fetch("https://good.example/team").ok)

    def test_named_agent_group_is_honoured(self):
        txt = "User-agent: prospecting-saas-vm1-pilot\nDisallow: /\n\nUser-agent: *\nAllow: /"
        f, _ = fetcher({self.ROBOTS: self.robots(txt), "https://good.example/": html()})
        self.assertFalse(f.fetch("https://good.example/").ok)

    def test_missing_robots_means_allowed(self):
        f, _ = fetcher({"https://good.example/": html()})  # robots -> 404
        self.assertTrue(f.fetch("https://good.example/").ok)

    def test_robots_5xx_fails_closed(self):
        f, t = fetcher({self.ROBOTS: self.robots("", 503), "https://good.example/": html()})
        r = f.fetch("https://good.example/")
        self.assertFalse(r.ok)
        self.assertNotIn("https://good.example/", t.calls)

    def test_excessive_crawl_delay_skips_site(self):
        f, _ = fetcher({self.ROBOTS: self.robots("User-agent: *\nCrawl-delay: 120"), "https://good.example/": html()})
        self.assertIn("crawl_delay", f.fetch("https://good.example/").error)

    def test_rate_limit_waits_between_requests(self):
        sleeps, now = [], [0.0]
        t = ScriptedTransport({"https://good.example/": html(), "https://good.example/a": html()})
        f = PoliteFetcher(t, PUB, min_delay=2.0, clock=lambda: now[0], sleep=lambda s: sleeps.append(s))
        f.fetch("https://good.example/")
        f.fetch("https://good.example/a")
        self.assertTrue(sleeps and max(sleeps) > 0, "second request to same host must wait")


class ResponseHandlingTests(unittest.TestCase):
    def test_non_html_and_errors_and_truncation(self):
        f, _ = fetcher({
            "https://good.example/pdf": RawResponse(200, {"content-type": "application/pdf"}, b"%PDF"),
            "https://good.example/big": RawResponse(200, {"content-type": "text/html"}, b"x", truncated=True),
            "https://good.example/err": RawResponse(500, {"content-type": "text/html"}, b"oops"),
        })
        self.assertTrue(f.fetch("https://good.example/pdf").error.startswith("non_html"))
        self.assertEqual(f.fetch("https://good.example/big").error, "too_large")
        self.assertEqual(f.fetch("https://good.example/err").error, "http_500")

    def test_user_agent_identifies_prototype(self):
        seen = {}

        class T:
            def request(self, method, target, headers, body, timeout, max_bytes):
                seen.update(headers)
                return html()

        PoliteFetcher(T(), PUB, min_delay=0, sleep=lambda s: None).fetch("https://good.example/")
        self.assertIn("prospecting-saas-vm1-pilot", seen["User-Agent"])
        self.assertNotIn("Cookie", seen)
        self.assertNotIn("Authorization", seen)


if __name__ == "__main__":
    unittest.main()
