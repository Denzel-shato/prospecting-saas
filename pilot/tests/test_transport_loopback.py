"""Exercises the REAL socket transport against a loopback server (no internet).

validate_url (tested elsewhere) would reject 127.0.0.1, so these tests build a Target by hand to
check only the transport mechanics: pinned-IP connect, size cap, headers, redirects not followed.
"""
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import tests.util  # noqa: F401
from vm1.fetch import PinnedTransport
from vm1.netsafe import Target

SEEN = {}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        SEEN["ua"] = self.headers.get("User-Agent")
        SEEN["host"] = self.headers.get("Host")
        SEEN["cookie"] = self.headers.get("Cookie")
        if self.path == "/big":
            body = b"x" * 5000
        elif self.path == "/redir":
            self.send_response(301)
            self.send_header("Location", "http://127.0.0.1:1/")
            self.end_headers()
            return
        else:
            body = b"<html><body>ok</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class LoopbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), H)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def target(self, path):
        return Target("http", "site.example", self.port, path, ("127.0.0.1",))

    def test_connects_to_pinned_ip_and_sends_logical_host(self):
        r = PinnedTransport().request("GET", self.target("/"), {"User-Agent": "ua-test"}, None, 5, 10_000)
        self.assertEqual((r.status, r.truncated), (200, False))
        self.assertIn(b"ok", r.body)
        self.assertEqual(SEEN["ua"], "ua-test")
        self.assertTrue(SEEN["host"].startswith("site.example"))
        self.assertIsNone(SEEN["cookie"])

    def test_size_cap_truncates(self):
        r = PinnedTransport().request("GET", self.target("/big"), {}, None, 5, 1000)
        self.assertTrue(r.truncated)
        self.assertEqual(len(r.body), 1000)

    def test_redirect_is_returned_not_followed(self):
        r = PinnedTransport().request("GET", self.target("/redir"), {}, None, 5, 1000)
        self.assertEqual(r.status, 301)


if __name__ == "__main__":
    unittest.main()
