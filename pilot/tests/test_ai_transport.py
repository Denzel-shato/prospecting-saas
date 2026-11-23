"""StdlibHttpsTransport against fake connections only: no sockets, no network."""
import http.client
import json
import ssl
import unittest
from unittest import mock

from vm1.ai import (
    AIConfigError, AIResponseError, AITimeoutError, AITransportError, StdlibHttpsTransport,
)
from vm1.ai import transport as transport_module

URL = "https://api.example.test/v1/run?x=1"


class FakeResp:
    def __init__(self, status=200, chunks=(b'{"ok": true}',), headers=(("Content-Type", "application/json"),),
                 on_read=None):
        self.status, self._chunks, self._headers, self._on_read = status, list(chunks), headers, on_read

    def read(self, n=-1):
        if self._on_read:
            self._on_read()
        return self._chunks.pop(0) if self._chunks else b""

    def getheaders(self):
        return list(self._headers)


class FakeConn:
    def __init__(self, resp=None, request_exc=None, response_exc=None):
        self.resp, self.request_exc, self.response_exc = resp or FakeResp(), request_exc, response_exc
        self.closed = False
        self.sent = None

    def request(self, method, target, body=None, headers=None):
        if self.request_exc:
            raise self.request_exc
        self.sent = (method, target, body, headers)

    def getresponse(self):
        if self.response_exc:
            raise self.response_exc
        return self.resp

    def close(self):
        self.closed = True


def make(conn):
    seen = {}

    def factory(host, port, timeout):
        seen.update(host=host, port=port, timeout=timeout)
        return conn

    return StdlibHttpsTransport(factory), seen


class TransportTests(unittest.TestCase):
    def post(self, conn, url=URL, timeout=5.0, max_bytes=1000):
        t, seen = make(conn)
        return t.post_json(url, {"Authorization": "Bearer k"}, {"a": 1}, timeout, max_bytes), seen

    def test_success_sends_json_post_and_returns_body(self):
        conn = FakeConn(FakeResp(201, [b'{"ok":', b' true}']))
        resp, seen = self.post(conn)
        self.assertEqual((resp.status, resp.body), (201, b'{"ok": true}'))
        self.assertEqual(resp.headers["content-type"], "application/json")
        method, target, body, headers = conn.sent
        self.assertEqual((method, target), ("POST", "/v1/run?x=1"))
        self.assertEqual(json.loads(body), {"a": 1})
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["Authorization"], "Bearer k")
        self.assertEqual((seen["host"], seen["port"], seen["timeout"]), ("api.example.test", None, 5.0))
        self.assertTrue(conn.closed)

    def test_redirect_is_returned_not_followed(self):
        resp, _ = self.post(FakeConn(FakeResp(302, [b""], (("Location", "https://evil.example/"),))))
        self.assertEqual(resp.status, 302)

    def test_only_plain_https_urls_are_accepted(self):
        for url in ("http://api.example.test/x", "ftp://api.example.test/x", "https:///x",
                    "https://user:pw@api.example.test/x", "api.example.test/x"):
            with self.subTest(url=url), self.assertRaises(AIConfigError):
                self.post(FakeConn(), url=url)

    def test_timeouts_map_to_ai_timeout_error(self):
        for conn in (FakeConn(response_exc=TimeoutError()), FakeConn(request_exc=TimeoutError())):
            with self.subTest(conn=conn), self.assertRaises(AITimeoutError) as cm:
                self.post(conn)
            self.assertTrue(cm.exception.retryable)
            self.assertTrue(conn.closed)

    def test_connection_failures_map_to_transport_error(self):
        for exc in (ConnectionRefusedError("no"), ssl.SSLError("bad cert"), OSError("dns"),
                    http.client.BadStatusLine("junk"), http.client.IncompleteRead(b"x")):
            conn = FakeConn(response_exc=exc)
            with self.subTest(exc=type(exc).__name__), self.assertRaises(AITransportError) as cm:
                self.post(conn)
            self.assertTrue(cm.exception.retryable)
            self.assertTrue(conn.closed)

    def test_transport_error_text_has_no_exception_details(self):
        with self.assertRaises(AITransportError) as cm:
            self.post(FakeConn(response_exc=OSError("secret-host-detail")))
        self.assertNotIn("secret-host-detail", str(cm.exception))

    def test_oversize_body_is_rejected(self):
        conn = FakeConn(FakeResp(200, [b"x" * 600, b"x" * 600]))
        with self.assertRaisesRegex(AIResponseError, "exceeds 1000 bytes"):
            self.post(conn, max_bytes=1000)
        self.assertTrue(conn.closed)

    def test_slow_drip_response_hits_the_wall_clock_deadline(self):
        now = [100.0]

        def tick():
            now[0] += 2.0

        conn = FakeConn(FakeResp(200, [b"a"] * 10, on_read=tick))
        with mock.patch.object(transport_module.time, "monotonic", lambda: now[0]):
            with self.assertRaisesRegex(AITimeoutError, "within 5s"):
                self.post(conn, timeout=5.0)
        self.assertTrue(conn.closed)


if __name__ == "__main__":
    unittest.main()
