"""Keyless API retries only transient DNS lookup failures (SSRF stays strict)."""
import unittest
from vm1.discovery import ApiClient, DiscoveryBlocked
from vm1.fetch import RawResponse

URL = "https://www.pickanagency.com/api/v1/search?q=agency"

class Transport:
    def __init__(self, status=200):
        self.status = status
        self.calls = []
    def request(self, method, target, headers, body, timeout, max_bytes):
        self.calls.append(target)
        return RawResponse(self.status, {}, b'{"results":[]}')

class ApiDnsRetryTests(unittest.TestCase):
    def test_retry_dns_miss_then_pin_fresh_public_ip(self):
        resolutions, pauses = [], []
        def resolve(host):
            resolutions.append(host)
            return [] if len(resolutions) == 1 else ["93.184.216.34"]
        t = Transport()
        c = ApiClient(transport=t, resolver=resolve, sleeper=pauses.append)
        self.assertEqual(c.request_json("GET", URL), {"results":[]})
        self.assertEqual(len(resolutions), 2)
        self.assertEqual(pauses, [0.75])
        self.assertEqual(c.calls, 1)
        self.assertEqual(t.calls[0].ips, ("93.184.216.34",))
    def test_persistent_dns_miss_stops_before_request(self):
        t, pauses, calls = Transport(), [], []
        def resolve(host):
            calls.append(host)
            return []
        c=ApiClient(transport=t, resolver=resolve, sleeper=pauses.append)
        with self.assertRaisesRegex(DiscoveryBlocked, "host did not resolve"):
            c.request_json("GET", URL)
        self.assertEqual(len(calls), 2)
        self.assertEqual(pauses, [0.75])
        self.assertEqual(t.calls, [])
    def test_private_dns_ip_fails_immediately(self):
        t, pauses = Transport(), []
        c=ApiClient(transport=t, resolver=lambda host: ["127.0.0.1"], sleeper=pauses.append)
        with self.assertRaisesRegex(DiscoveryBlocked, "non-public"):
            c.request_json("GET", URL)
        self.assertEqual(pauses, [])
        self.assertEqual(t.calls, [])
    def test_private_ip_after_retry_still_fails(self):
        t, calls = Transport(), []
        def resolve(host):
            calls.append(host)
            return [] if len(calls)==1 else ["10.0.0.1"]
        c=ApiClient(transport=t, resolver=resolve, sleeper=lambda _: None)
        with self.assertRaisesRegex(DiscoveryBlocked, "non-public"):
            c.request_json("GET", URL)
        self.assertEqual(len(calls), 2)
        self.assertEqual(t.calls, [])
    def test_http_429_never_retried(self):
        t, pauses=Transport(429), []
        c=ApiClient(transport=t, resolver=lambda host: ["93.184.216.34"], sleeper=pauses.append)
        with self.assertRaisesRegex(DiscoveryBlocked, "429"):
            c.request_json("GET", URL)
        self.assertEqual(len(t.calls), 1)
        self.assertEqual(pauses, [])
    def test_unapproved_host_does_not_attempt_dns(self):
        t=Transport()
        c=ApiClient(transport=t, resolver=lambda host: self.fail("unexpected DNS"))
        with self.assertRaisesRegex(DiscoveryBlocked, "not an approved"):
            c.request_json("GET", "https://evil.example/a")
        self.assertEqual(t.calls, [])

if __name__=="__main__": unittest.main()
