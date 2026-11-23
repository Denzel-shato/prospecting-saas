"""Mock, Cloudflare and Groq adapters with a fake transport. Real network access is blocked."""
import json
import socket
import unittest
from unittest import mock

from vm1.ai import (
    AIConfigError, AIHTTPError, AIProvider, AIResponseError, AITimeoutError, AITransportError,
    CloudflareWorkersAIProvider, GroqProvider, HttpResponse, MockProvider, StructuredRequest,
)

SCHEMA = {
    "type": "object",
    "required": ["name", "score"],
    "properties": {"name": {"type": "string"}, "score": {"type": "integer", "minimum": 0, "maximum": 10}},
    "additionalProperties": False,
}
GOOD = {"name": "x", "score": 4}
KEY = "sekrit-key-XYZ"
ACCOUNT = "acc123"
CF_MODEL = "@cf/test/model-1"
REQ = StructuredRequest(prompt="Rate it.", schema=SCHEMA, system="Be terse.", max_tokens=77,
                        temperature=0.5, timeout=9.0)


def ok(obj, status=200):
    return HttpResponse(status, {}, json.dumps(obj).encode())


def raw(body, status=200):
    return HttpResponse(status, {}, body if isinstance(body, bytes) else body.encode())


class FakeTransport:
    def __init__(self, *items):
        self.items, self.calls = list(items), []

    def post_json(self, url, headers, payload, timeout, max_bytes):
        self.calls.append({"url": url, "headers": dict(headers), "payload": payload,
                           "timeout": timeout, "max_bytes": max_bytes})
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class NoNetwork(unittest.TestCase):
    """Any real socket use during these tests is a bug: fail loudly."""

    def setUp(self):
        for target in ("socket.socket.connect", "socket.getaddrinfo", "socket.create_connection"):
            p = mock.patch(target, side_effect=AssertionError("network attempted"))
            p.start()
            self.addCleanup(p.stop)


def cloudflare(*items, **kw):
    t = FakeTransport(*items)
    return CloudflareWorkersAIProvider(account_id=ACCOUNT, api_token=KEY, model=CF_MODEL, transport=t, **kw), t


def groq(*items, **kw):
    t = FakeTransport(*items)
    return GroqProvider(api_key=KEY, model="test-model", transport=t, **kw), t


def cf_result(response, **extra):
    return {"result": {"response": response, **extra}, "success": True, "errors": [], "messages": []}


def groq_choice(content, finish="stop", **extra):
    return {"choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                         "finish_reason": finish}], **extra}


class MockProviderTests(NoNetwork):
    def test_satisfies_protocol_and_needs_no_key(self):
        m = MockProvider([GOOD])
        self.assertIsInstance(m, AIProvider)
        r = m.generate_structured(REQ)
        self.assertEqual((r.data, r.provider, r.model), (GOOD, "mock", "mock-1"))
        self.assertEqual(m.calls, [REQ])

    def test_script_items_are_consumed_in_order(self):
        m = MockProvider([GOOD, '```json\n{"name": "y", "score": 1}\n```', lambda req: {"name": req.prompt, "score": 0}])
        self.assertEqual(m.generate_structured(REQ).data["name"], "x")
        self.assertEqual(m.generate_structured(REQ).data["name"], "y")
        self.assertEqual(m.generate_structured(REQ).data["name"], "Rate it.")

    def test_scripted_failures_are_raised(self):
        m = MockProvider([AITimeoutError("t"), AIHTTPError(429, "slow"), RuntimeError("boom")])
        with self.assertRaises(AITimeoutError):
            m.generate_structured(REQ)
        with self.assertRaises(AIHTTPError):
            m.generate_structured(REQ)
        with self.assertRaises(RuntimeError):
            m.generate_structured(REQ)
        self.assertEqual(len(m.calls), 3)

    def test_mock_output_is_validated_like_a_real_provider(self):
        m = MockProvider(["not json", {"name": "x", "score": 99}, ["list"]])
        for _ in range(3):
            with self.assertRaises(AIResponseError):
                m.generate_structured(REQ)

    def test_default_repeats_and_exhaustion_is_an_error(self):
        d = MockProvider(default=GOOD)
        self.assertEqual([d.generate_structured(REQ).data for _ in range(3)], [GOOD] * 3)
        with self.assertRaisesRegex(AIConfigError, "no scripted response left"):
            MockProvider().generate_structured(REQ)

    def test_rejects_non_request(self):
        with self.assertRaises(AIConfigError):
            MockProvider(default=GOOD).generate_structured({"prompt": "x"})


class CloudflareAdapterTests(NoNetwork):
    def test_request_shape(self):
        p, t = cloudflare(ok(cf_result(GOOD)))
        p.generate_structured(REQ)
        (call,) = t.calls
        self.assertEqual(call["url"], f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/ai/run/{CF_MODEL}")
        self.assertEqual(call["headers"], {"Authorization": f"Bearer {KEY}"})
        self.assertEqual((call["timeout"], call["max_bytes"]), (9.0, 1_000_000))
        body = call["payload"]
        self.assertEqual((body["max_tokens"], body["temperature"]), (77, 0.5))
        self.assertEqual(body["response_format"], {"type": "json_schema", "json_schema": SCHEMA})
        system, user = body["messages"]
        self.assertEqual((system["role"], user), ("system", {"role": "user", "content": "Rate it."}))
        self.assertTrue(system["content"].startswith("Be terse."))
        self.assertIn(json.dumps(SCHEMA, sort_keys=True), system["content"])
        self.assertNotIn(KEY, json.dumps(body))

    def test_string_and_object_responses_and_usage(self):
        usage = {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7, "junk": 1}
        p, _ = cloudflare(ok(cf_result(json.dumps(GOOD), usage=usage)), ok(cf_result(GOOD)), ok({"response": GOOD}))
        a, b, c = (p.generate_structured(REQ) for _ in range(3))
        self.assertEqual((a.data, b.data, c.data), (GOOD, GOOD, GOOD))
        self.assertEqual(a.usage, {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7})
        self.assertEqual((a.provider, a.model), ("cloudflare", CF_MODEL))

    def test_unusable_envelopes_are_response_errors(self):
        for body in (
            {"result": {}}, {"result": "str"}, {"success": True}, cf_result(None), cf_result("  "),
            cf_result("not json"), cf_result([1]), cf_result({"name": "x", "score": 99}),
            {"success": False, "errors": [{"code": 1, "message": "JSON Mode couldn't be met"}]},
            [1, 2],
        ):
            p, _ = cloudflare(ok(body))
            with self.subTest(body=body), self.assertRaises(AIResponseError) as cm:
                p.generate_structured(REQ)
            self.assertEqual(cm.exception.provider, "cloudflare")

    def test_failure_message_surfaces_cloudflare_detail(self):
        p, _ = cloudflare(ok({"success": False, "errors": [{"message": "JSON Mode couldn't be met"}]}))
        with self.assertRaisesRegex(AIResponseError, "JSON Mode couldn't be met"):
            p.generate_structured(REQ)

    def test_invalid_configuration(self):
        t = FakeTransport()
        good = {"api_token": KEY, "model": CF_MODEL, "transport": t}
        for kw in (
            {"account_id": ""}, {"account_id": "a/b"}, {"account_id": "a b"},
            {"account_id": ACCOUNT, "model": "../x"}, {"account_id": ACCOUNT, "model": "a//b"},
            {"account_id": ACCOUNT, "model": "/abs"}, {"account_id": ACCOUNT, "model": "has space"},
            {"account_id": ACCOUNT, "api_token": ""}, {"account_id": ACCOUNT, "api_token": "a\nb"},
            {"account_id": ACCOUNT, "base_url": "http://api.example.test"},
            {"account_id": ACCOUNT, "base_url": "https://u:p@api.example.test"},
            {"account_id": ACCOUNT, "max_response_bytes": 0},
        ):
            with self.subTest(kw=kw), self.assertRaises(AIConfigError):
                CloudflareWorkersAIProvider(**{**good, **kw})

    def test_base_url_override(self):
        p, t = cloudflare(ok(cf_result(GOOD)), base_url="https://gateway.example.test/cf/")
        p.generate_structured(REQ)
        self.assertEqual(t.calls[0]["url"], f"https://gateway.example.test/cf/accounts/{ACCOUNT}/ai/run/{CF_MODEL}")


class GroqAdapterTests(NoNetwork):
    def test_default_request_shape_is_json_object(self):
        p, t = groq(ok(groq_choice(json.dumps(GOOD))))
        p.generate_structured(REQ)
        (call,) = t.calls
        self.assertEqual(call["url"], "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(call["headers"], {"Authorization": f"Bearer {KEY}"})
        body = call["payload"]
        self.assertEqual(body["model"], "test-model")
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual((body["max_completion_tokens"], body["temperature"]), (77, 0.5))
        self.assertNotIn("max_tokens", body)
        self.assertIn("JSON", body["messages"][0]["content"])
        self.assertIn(json.dumps(SCHEMA, sort_keys=True), body["messages"][0]["content"])

    def test_json_schema_mode_payload(self):
        for strict in (False, True):
            p, t = groq(ok(groq_choice(json.dumps(GOOD))), response_mode="json_schema", strict_schema=strict)
            p.generate_structured(REQ)
            self.assertEqual(t.calls[0]["payload"]["response_format"],
                             {"type": "json_schema", "json_schema": {"name": "response", "strict": strict, "schema": SCHEMA}})

    def test_success_fenced_content_and_usage(self):
        usage = {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7, "queue_time": 0.1}
        p, _ = groq(ok(groq_choice('```json\n{"name": "x", "score": 4}\n```', usage=usage)))
        r = p.generate_structured(REQ)
        self.assertEqual((r.data, r.provider, r.model), (GOOD, "groq", "test-model"))
        self.assertEqual(r.usage, {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7})

    def test_unusable_envelopes_are_response_errors(self):
        for body in (
            {}, {"choices": []}, {"choices": ["x"]}, {"choices": [{}]}, {"choices": [{"message": "m"}]},
            groq_choice(None), groq_choice("  "), groq_choice("Sure, here you go"),
            groq_choice('{"name": "x", "score": 99}'), groq_choice('["a"]'),
            groq_choice('{"name": "x", "sc', finish="length"), [1],
        ):
            p, _ = groq(ok(body))
            with self.subTest(body=body), self.assertRaises(AIResponseError) as cm:
                p.generate_structured(REQ)
            self.assertEqual(cm.exception.provider, "groq")

    def test_truncation_is_reported_as_such(self):
        p, _ = groq(ok(groq_choice(json.dumps(GOOD), finish="length")))
        with self.assertRaisesRegex(AIResponseError, "token limit"):
            p.generate_structured(REQ)

    def test_invalid_configuration(self):
        for kw in ({"response_mode": "xml"}, {"strict_schema": "yes"}, {"api_key": ""}, {"model": ""},
                   {"base_url": "http://api.example.test"}):
            with self.subTest(kw=kw), self.assertRaises(AIConfigError):
                GroqProvider(**{"api_key": KEY, "model": "m", **kw})


class SharedFailureHandlingTests(NoNetwork):
    BUILDERS = (("cloudflare", cloudflare), ("groq", groq))

    def each(self, *items):
        for name, build in self.BUILDERS:
            p, t = build(*items)
            yield name, p, t

    def test_http_errors_carry_status_and_retryability(self):
        for status, retryable in ((400, False), (401, False), (403, False), (404, False), (302, False),
                                  (408, True), (429, True), (500, True), (503, True)):
            for name, p, _ in self.each(raw("{}", status)):
                with self.subTest(provider=name, status=status), self.assertRaises(AIHTTPError) as cm:
                    p.generate_structured(REQ)
                self.assertEqual((cm.exception.status, cm.exception.retryable, cm.exception.provider),
                                 (status, retryable, name))

    def test_http_error_detail_is_extracted_when_present(self):
        bodies = (
            json.dumps({"error": {"message": "rate limited", "type": "x"}}),
            json.dumps({"errors": [{"code": 1, "message": "rate limited"}]}),
            json.dumps({"error": "rate limited"}),
        )
        for body in bodies:
            for name, p, _ in self.each(raw(body, 429)):
                with self.subTest(provider=name, body=body), self.assertRaisesRegex(AIHTTPError, "429: rate limited$"):
                    p.generate_structured(REQ)

    def test_non_json_error_bodies_are_bounded(self):
        for name, p, _ in self.each(raw("<html>" + "x" * 5000 + "</html>", 502)):
            with self.subTest(provider=name), self.assertRaises(AIHTTPError) as cm:
                p.generate_structured(REQ)
            self.assertLess(len(str(cm.exception)), 260)

    def test_secrets_are_redacted_everywhere(self):
        leak = json.dumps({"error": {"message": f"Invalid API key {KEY}"}})
        leaky_content = json.dumps({"name": KEY, "score": 99})  # schema-invalid and echoes the key
        for name, p, _ in self.each(raw(leak, 401)):
            with self.subTest(provider=name, where="http error"), self.assertRaises(AIHTTPError) as cm:
                p.generate_structured(REQ)
            self.assertNotIn(KEY, str(cm.exception))
            self.assertIn("[redacted]", str(cm.exception))
        for name, p, _ in self.each(raw(f"<html>{KEY}</html>")):
            with self.subTest(provider=name, where="bad body"), self.assertRaises(AIResponseError) as cm:
                p.generate_structured(REQ)
            self.assertNotIn(KEY, cm.exception.snippet + str(cm.exception))
        for name, p, _ in (("cloudflare", *cloudflare(ok(cf_result(leaky_content)))),
                           ("groq", *groq(ok(groq_choice(leaky_content))))):
            with self.subTest(provider=name, where="bad output"), self.assertRaises(AIResponseError) as cm:
                p.generate_structured(REQ)
            self.assertNotIn(KEY, cm.exception.snippet + str(cm.exception))

    def test_non_json_2xx_bodies_are_response_errors(self):
        for body in (b"", b"<html>oops</html>", b"\xff\xfe", b"[1]", b'"s"'):
            for name, p, _ in self.each(raw(body)):
                with self.subTest(provider=name, body=body), self.assertRaises(AIResponseError):
                    p.generate_structured(REQ)

    def test_transport_failures_are_wrapped_and_attributed(self):
        cases = (
            (lambda: AITimeoutError("t"), AITimeoutError), (lambda: AITransportError("c"), AITransportError),
            (TimeoutError, AITimeoutError), (ConnectionResetError, AITransportError),
            (lambda: OSError("x"), AITransportError),
        )
        for make_exc, expected in cases:
            for name, build in self.BUILDERS:  # fresh exception per provider: attribution mutates it
                p, _ = build(make_exc())
                with self.subTest(provider=name, exc=expected.__name__), self.assertRaises(expected) as cm:
                    p.generate_structured(REQ)
                self.assertEqual(cm.exception.provider, name)
                self.assertTrue(cm.exception.retryable)

    def test_unexpected_exceptions_are_not_swallowed(self):
        for _, p, _ in self.each(RuntimeError("bug")):
            with self.assertRaises(RuntimeError):
                p.generate_structured(REQ)

    def test_request_timeout_and_size_cap_reach_the_transport(self):
        for name, p, t in self.each(raw("{}", 500)):
            with self.assertRaises(AIHTTPError):
                p.generate_structured(StructuredRequest(prompt="p", schema=SCHEMA, timeout=1.5))
            self.assertEqual((t.calls[0]["timeout"], t.calls[0]["max_bytes"]), (1.5, 1_000_000))
        p, t = groq(raw("{}", 500), max_response_bytes=123)
        with self.assertRaises(AIHTTPError):
            p.generate_structured(REQ)
        self.assertEqual(t.calls[0]["max_bytes"], 123)

    def test_provider_reprs_never_contain_the_key(self):
        for _, build in self.BUILDERS:
            p, _ = build()
            self.assertNotIn(KEY, repr(p))
            self.assertNotIn(KEY, str(vars(p).get("model")))

    def test_providers_reject_non_requests(self):
        for _, p, _ in self.each():
            with self.assertRaises(AIConfigError):
                p.generate_structured("hello")

    def test_adapters_satisfy_the_provider_protocol(self):
        for _, build in self.BUILDERS:
            self.assertIsInstance(build()[0], AIProvider)


if __name__ == "__main__":
    unittest.main()
