"""Regression tests for mixed DNS histories in offline snapshot replay.

A host may resolve successfully for an HTTP request, then fail DNS later in the
same capture. A host-wide failure marker must not erase the saved HTTP response.
"""

import tempfile
import unittest

from vm1.snapshot import ReplayFetcher, SnapshotMissing, SnapshotStore


class TransientDnsReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = SnapshotStore(self.temp.name)
        self.host = "studio.example"
        self.home = f"https://{self.host}/"
        self.store.write_manifest({
            "started_at": "2026-11-23T10:00:00+00:00",
            "unresolvable_hosts": [self.host],
        })

    def tearDown(self):
        self.temp.cleanup()

    def save(self, url, *, status=200, error=None, body=b"", content_type="text/html"):
        self.store.put({
            "method": "GET",
            "url": url,
            "captured_at": "2026-11-23T10:00:01+00:00",
            "status": status,
            "headers": {"content-type": content_type},
            "truncated": False,
            "error": error,
            "redacted": True,
        }, body)

    def test_late_host_dns_failure_does_not_hide_successful_saved_homepage(self):
        self.save(f"https://{self.host}/robots.txt", status=404, content_type="text/plain")
        self.save(self.home, body=b"<html><body>Saved homepage</body></html>")

        fetcher = ReplayFetcher(self.store, strict=True)
        result = fetcher.fetch(self.home)

        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.status, 200)
        self.assertIn("Saved homepage", result.text)
        self.assertEqual(fetcher.missing, [])

    def test_uncaptured_page_on_same_host_still_fails_closed(self):
        self.save(f"https://{self.host}/robots.txt", status=404, content_type="text/plain")
        self.save(self.home, body=b"<html>Recorded</html>")

        fetcher = ReplayFetcher(self.store, strict=True)
        with self.assertRaises(SnapshotMissing):
            fetcher.fetch(f"https://{self.host}/not-captured")
        self.assertEqual(fetcher.missing, [f"https://{self.host}/not-captured"])

    def test_page_dns_failure_is_replayed_from_capture_manifest(self):
        self.save(f"https://{self.host}/robots.txt", status=404, content_type="text/plain")
        self.save(self.home, body=b"<html>Saved homepage</html>")
        missing_page = f"https://{self.host}/about-us/"
        manifest = self.store.read_manifest()
        manifest["companies"] = [{
            "homepage": self.home,
            "homepage_error": None,
            "page_errors": {missing_page: "unsafe_url: host did not resolve"},
        }]
        self.store.write_manifest(manifest)

        fetcher = ReplayFetcher(self.store, strict=True)
        self.assertTrue(fetcher.fetch(self.home).ok)
        failure = fetcher.fetch(missing_page)
        self.assertFalse(failure.ok)
        self.assertEqual(failure.error, "unsafe_url: host did not resolve")
        self.assertEqual(failure.fetched_at, manifest["started_at"])
        self.assertEqual(fetcher.missing, [])

    def test_saved_http_response_wins_over_conflicting_page_dns_failure(self):
        self.save(f"https://{self.host}/robots.txt", status=404, content_type="text/plain")
        self.save(self.home, body=b"<html>Saved homepage</html>")
        manifest = self.store.read_manifest()
        manifest["companies"] = [{
            "homepage": self.home,
            "homepage_error": "unsafe_url: host did not resolve",
            "page_errors": {},
        }]
        self.store.write_manifest(manifest)

        result = ReplayFetcher(self.store, strict=True).fetch(self.home)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.status, 200)

    def test_dns_failure_with_no_saved_http_response_remains_unreachable(self):
        # A transport-level failure with status=None is not evidence of HTTP success.
        self.save(self.home, status=None, error={"type": "gaierror"})
        fetcher = ReplayFetcher(self.store, strict=False)

        result = fetcher.fetch(self.home)

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "unsafe_url: host did not resolve")
        self.assertEqual(fetcher.missing, [])


if __name__ == "__main__":
    unittest.main()
