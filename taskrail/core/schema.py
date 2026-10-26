"""Validate the small, closed JSON schema vocabulary used by stage contracts."""

import json
from pathlib import Path
from types import MappingProxyType

from taskrail.core import schema_fields
from taskrail.core.schema_fields import ContractError as ContractError

KINDS = MappingProxyType(
    {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}
)
CONTRACT_VERSION = 1
SCHEMAS = json.loads(Path(__file__).with_name("result-schemas.json").read_text())


def require(condition, message):
    """Reject contract violations without converting values or dropping fields."""
    if not condition:
        raise ValueError(message)


def validate(payload, specification, path=""):
    """Recursively enforce types, exact keys, scalar bounds and enum values."""
    expected = KINDS[specification["type"]]
    valid = isinstance(payload, expected)
    valid = valid and (expected is not int or not isinstance(payload, bool))
    message = "Invalid JSON field type: expected {type}".format(**specification)
    schema_fields.require(valid, "FIELD_TYPE", path, message)
    choices = specification.get("enum")
    if choices is not None:
        schema_fields.require(
            payload in choices, "FIELD_ENUM", path, f"Invalid enum value; expected {choices}"
        )
    if isinstance(payload, dict):
        validate_object(payload, specification, path)
    elif isinstance(payload, list):
        schema_fields.array(payload, specification, path, validate)
    else:
        validate_scalar(payload, specification, path)


def validate_object(payload, specification, path=""):
    """Require all declared keys; reject unknown keys instead of ignoring them."""
    fields = schema_fields.object_fields(payload, specification, path)
    for name, entry in payload.items():
        validate(entry, fields[name], schema_fields.pointer(path, name))


def validate_scalar(payload, specification, path=""):
    """Reject blank text and invalid source line numbers."""
    if "minLength" in specification:
        schema_fields.require(bool(payload.strip()), "FIELD_EMPTY", path, "Empty text field")
    maximum = specification.get("maxLength")
    schema_fields.require(
        maximum is None or len(payload) <= maximum, "FIELD_SIZE", path, "Text is too long"
    )
    minimum = specification.get("minimum")
    if minimum is not None:
        schema_fields.require(payload >= minimum, "FIELD_MINIMUM", path, "Number below minimum")


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
