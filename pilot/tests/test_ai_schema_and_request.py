"""AI provider foundation: schema subset, request validation, JSON parsing, response building."""
import unittest

from vm1.ai import AIConfigError, AIResponseError, StructuredRequest
from vm1.ai.request import build_response, parse_json_object
from vm1.ai.schema import SchemaViolation, check_schema, validate

SCHEMA = {
    "type": "object",
    "required": ["name", "score"],
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "score": {"type": "integer", "minimum": 0, "maximum": 10},
        "tags": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 2},
        "kind": {"enum": ["a", "b"]},
    },
    "additionalProperties": False,
}


class SchemaValidationTests(unittest.TestCase):
    def violation(self, value, schema=SCHEMA):
        with self.assertRaises(SchemaViolation) as cm:
            validate(value, schema)
        return str(cm.exception)

    def test_valid_instance_passes(self):
        validate({"name": "x", "score": 3, "tags": ["t"], "kind": "a"}, SCHEMA)

    def test_missing_required_and_extra_property(self):
        self.assertIn("missing required property 'score'", self.violation({"name": "x"}))
        self.assertIn("unexpected property 'zzz'", self.violation({"name": "x", "score": 1, "zzz": 1}))

    def test_bool_is_not_an_integer_or_number(self):
        self.assertIn("$.score", self.violation({"name": "x", "score": True}))
        self.violation(True, {"type": "number"})

    def test_bounds_enum_and_array_constraints(self):
        base = {"name": "x", "score": 1}
        self.assertIn("above maximum", self.violation({**base, "score": 11}))
        self.assertIn("below minimum", self.violation({**base, "score": -1}))
        self.assertIn("not in enum", self.violation({**base, "kind": "c"}))
        self.assertIn("fewer than 1", self.violation({**base, "tags": []}))
        self.assertIn("more than 2", self.violation({**base, "tags": ["a", "b", "c"]}))
        self.assertIn("$.tags[1]", self.violation({**base, "tags": ["a", 5]}))
        self.assertIn("shorter than 1", self.violation({"name": "", "score": 1}))

    def test_type_list_allows_null(self):
        validate(None, {"type": ["string", "null"]})
        self.violation(5, {"type": ["string", "null"]})

    def test_check_schema_rejects_unsupported_or_malformed_keywords(self):
        for bad in (
            {"type": "object", "oneOf": []},
            {"type": "object", "$ref": "#/x"},
            {"type": "string", "pattern": "^a"},
            {"type": "weird"},
            {"type": "object", "additionalProperties": {"type": "string"}},
            {"type": "object", "required": "name"},
            {"type": "array", "minItems": -1},
            {"enum": []},
            {"type": "object", "properties": {"a": {"type": "object", "allOf": []}}},
            "not a mapping",
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                check_schema(bad)

    def test_annotations_are_allowed(self):
        check_schema({"type": "object", "title": "T", "description": "d", "$schema": "x", "default": {}})

    def test_excessive_nesting_is_rejected(self):
        schema = {"type": "object"}
        for _ in range(40):
            schema = {"type": "object", "properties": {"a": schema}}
        with self.assertRaises(ValueError):
            check_schema(schema)


class StructuredRequestTests(unittest.TestCase):
    def make(self, **kw):
        args = {"prompt": "p", "schema": {"type": "object"}}
        args.update(kw)
        return StructuredRequest(**args)

    def test_defaults_are_valid(self):
        r = self.make()
        self.assertEqual((r.max_tokens, r.temperature, r.timeout), (1024, 0.0, 30.0))

    def test_invalid_requests_raise_config_error(self):
        for kw in (
            {"prompt": ""}, {"prompt": "   "}, {"prompt": 5}, {"system": 5},
            {"schema": {"type": "array"}}, {"schema": {}}, {"schema": {"type": "object", "oneOf": []}},
            {"max_tokens": 0}, {"max_tokens": True}, {"max_tokens": 1.5},
            {"temperature": -0.1}, {"temperature": 2.1}, {"temperature": "hot"},
            {"timeout": 0}, {"timeout": -1}, {"timeout": float("inf")}, {"timeout": float("nan")},
            {"timeout": True},
        ):
            with self.subTest(kw=kw), self.assertRaises(AIConfigError):
                self.make(**kw)


class ParseJsonObjectTests(unittest.TestCase):
    def parse(self, text):
        return parse_json_object(text, provider="t")

    def test_plain_and_fenced_objects(self):
        self.assertEqual(self.parse(' {"a": 1} '), {"a": 1})
        self.assertEqual(self.parse('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(self.parse('```\n{"a": 1}\n```'), {"a": 1})

    def test_unusable_text_raises_response_error_with_snippet(self):
        for text in ("", "   ", "```\n```", "not json", '{"a": 1', 'Sure! {"a": 1}', '{"a": 1} trailing',
                     "[1, 2]", '"str"', "42", "null", '{"a": NaN}', '{"a": Infinity}'):
            with self.subTest(text=text), self.assertRaises(AIResponseError) as cm:
                self.parse(text)
            self.assertEqual(cm.exception.provider, "t")

    def test_snippet_is_bounded_and_single_line(self):
        with self.assertRaises(AIResponseError) as cm:
            self.parse("bad\n" * 500)
        self.assertLessEqual(len(cm.exception.snippet), 200)
        self.assertNotIn("\n", cm.exception.snippet)


class BuildResponseTests(unittest.TestCase):
    REQ = StructuredRequest(prompt="p", schema=SCHEMA)

    def build(self, content):
        return build_response(content, self.REQ, provider="t", model="m", usage={"total_tokens": 3})

    def test_text_and_object_content(self):
        from_text = self.build('{"name": "x", "score": 2}')
        from_obj = self.build({"name": "x", "score": 2})
        self.assertEqual(from_text.data, from_obj.data)
        self.assertEqual((from_text.provider, from_text.model, from_text.usage), ("t", "m", {"total_tokens": 3}))

    def test_schema_violation_is_a_response_error(self):
        with self.assertRaisesRegex(AIResponseError, "violates schema"):
            self.build('{"name": "x", "score": 99}')
        with self.assertRaisesRegex(AIResponseError, "violates schema"):
            self.build({"name": "x"})

    def test_unsupported_content_types(self):
        for content in (None, 5, ["a"], b"bytes"):
            with self.subTest(content=content), self.assertRaises(AIResponseError):
                self.build(content)

    def test_non_serializable_object_is_a_response_error(self):
        with self.assertRaisesRegex(AIResponseError, "serializable"):
            self.build({"name": "x", "score": 1, "extra": {1, 2}})


if __name__ == "__main__":
    unittest.main()
