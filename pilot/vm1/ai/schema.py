"""A deliberately small JSON-Schema subset validator (standard library only).

Providers cannot be trusted to honour a schema (Cloudflare's docs say it cannot
guarantee schema conformance), so every provider result is re-validated locally.

Supported keywords: type, enum, required, properties, additionalProperties (bool),
items, minItems, maxItems, minLength, maxLength, minimum, maximum.
Annotation keywords (title, description, default, examples, $schema) are ignored.
Any other keyword raises ``ValueError`` when the schema is checked, so a caller can
never believe a constraint is enforced when it is silently skipped.
"""

from __future__ import annotations

from typing import Any, Mapping

_TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}
_ANNOTATIONS = {"title", "description", "default", "examples", "$schema"}
_SUPPORTED = {
    "type", "enum", "required", "properties", "additionalProperties", "items",
    "minItems", "maxItems", "minLength", "maxLength", "minimum", "maximum",
}
MAX_DEPTH = 32


class SchemaViolation(ValueError):
    """The instance does not satisfy the schema. ``str()`` names the failing path."""


def check_schema(schema: Any, path: str = "$", depth: int = 0) -> None:
    """Raise ValueError unless ``schema`` uses only supported, well-formed keywords."""
    if depth > MAX_DEPTH:
        raise ValueError(f"{path}: schema nested deeper than {MAX_DEPTH}")
    if not isinstance(schema, Mapping):
        raise ValueError(f"{path}: schema must be an object")
    unknown = set(schema) - _SUPPORTED - _ANNOTATIONS
    if unknown:
        raise ValueError(f"{path}: unsupported schema keyword(s) {sorted(unknown)}")
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not types or not all(isinstance(t, str) and t in _TYPES for t in types):
            raise ValueError(f"{path}: invalid 'type'")
    if "enum" in schema and not (isinstance(schema["enum"], list) and schema["enum"]):
        raise ValueError(f"{path}: 'enum' must be a non-empty list")
    if "required" in schema and not (
        isinstance(schema["required"], list) and all(isinstance(k, str) for k in schema["required"])
    ):
        raise ValueError(f"{path}: 'required' must be a list of strings")
    if "additionalProperties" in schema and not isinstance(schema["additionalProperties"], bool):
        raise ValueError(f"{path}: 'additionalProperties' must be a boolean")
    for key in ("minItems", "maxItems", "minLength", "maxLength"):
        if key in schema and not (isinstance(schema[key], int) and not isinstance(schema[key], bool)
                                  and schema[key] >= 0):
            raise ValueError(f"{path}: '{key}' must be a non-negative integer")
    for key in ("minimum", "maximum"):
        if key in schema and (isinstance(schema[key], bool) or not isinstance(schema[key], (int, float))):
            raise ValueError(f"{path}: '{key}' must be a number")
    if "properties" in schema:
        props = schema["properties"]
        if not isinstance(props, Mapping):
            raise ValueError(f"{path}: 'properties' must be an object")
        for name, sub in props.items():
            check_schema(sub, f"{path}.{name}", depth + 1)
    if "items" in schema:
        check_schema(schema["items"], f"{path}[]", depth + 1)


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return False


def validate(value: Any, schema: Mapping[str, Any], path: str = "$") -> None:
    """Raise SchemaViolation if ``value`` does not satisfy ``schema`` (already checked)."""
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(value, t) for t in types):
            raise SchemaViolation(f"{path}: expected {'/'.join(types)}, got {type(value).__name__}")
    if "enum" in schema and value not in schema["enum"]:
        raise SchemaViolation(f"{path}: value not in enum")
    if isinstance(value, dict):
        for name in schema.get("required", ()):
            if name not in value:
                raise SchemaViolation(f"{path}: missing required property '{name}'")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(props))
            if extra:
                raise SchemaViolation(f"{path}: unexpected property '{extra[0]}'")
        for name, sub in props.items():
            if name in value:
                validate(value[name], sub, f"{path}.{name}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise SchemaViolation(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise SchemaViolation(f"{path}: more than {schema['maxItems']} items")
        if "items" in schema:
            for i, item in enumerate(value):
                validate(item, schema["items"], f"{path}[{i}]")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise SchemaViolation(f"{path}: shorter than {schema['minLength']} characters")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise SchemaViolation(f"{path}: longer than {schema['maxLength']} characters")
    if _type_ok(value, "number"):
        if "minimum" in schema and value < schema["minimum"]:
            raise SchemaViolation(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise SchemaViolation(f"{path}: above maximum {schema['maximum']}")
