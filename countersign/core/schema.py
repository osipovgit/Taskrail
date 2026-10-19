"""Validate the small, closed JSON schema vocabulary used by stage contracts."""

import json
from pathlib import Path
from types import MappingProxyType

from countersign.core.json_response import extract

KINDS = MappingProxyType(
    {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}
)
CONTRACT_VERSION = 1
SCHEMAS = json.loads(Path(__file__).with_name("result-schemas.json").read_text())


def require(condition, message):
    """Reject contract violations without converting values or dropping fields."""
    if not condition:
        raise ValueError(message)


def validate(payload, specification):
    """Recursively enforce types, exact keys, scalar bounds and enum values."""
    expected = KINDS[specification["type"]]
    require(isinstance(payload, expected), "Invalid JSON field type")
    require(expected is not int or not isinstance(payload, bool), "Boolean is not an integer")
    choices = specification.get("enum")
    if choices is not None:
        require(payload in choices, "Invalid enum value")
    if isinstance(payload, dict):
        validate_object(payload, specification)
    elif isinstance(payload, list):
        for entry in payload:
            validate(entry, specification["items"])
    else:
        validate_scalar(payload, specification)


def validate_object(payload, specification):
    """Require all declared keys; reject unknown keys instead of ignoring them."""
    fields = specification["properties"]
    missing = sorted(set(fields) - set(payload))
    unknown = sorted(set(payload) - set(fields))
    require(not missing and not unknown, f"Missing fields: {missing}; unknown fields: {unknown}")
    for name, entry in payload.items():
        validate(entry, fields[name])


def validate_scalar(payload, specification):
    """Reject blank text and invalid source line numbers."""
    if "minLength" in specification:
        require(bool(payload.strip()), "Empty text field")
    minimum = specification.get("minimum")
    if minimum is not None:
        require(payload >= minimum, "Number below minimum")


def decode(response, role):
    """Decode one unambiguous object; semantic and evidence gates remain strict."""
    require(bool(response.strip()), "Empty final response; no JSON object received")
    payload = extract(response, unique_fields)
    validate(payload, SCHEMAS[role])
    return payload


def unique_fields(pairs):
    """Duplicate JSON keys must not silently replace conflicting model claims."""
    fields = dict(pairs)
    require(len(fields) == len(pairs), "Duplicate JSON field")
    return fields


def contract_version(version):
    """Reject missing or unknown contracts before execution."""
    supported = isinstance(version, int) and not isinstance(version, bool)
    require(supported and version == CONTRACT_VERSION, "Unsupported contract version")
    return version
