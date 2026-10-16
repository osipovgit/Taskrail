"""Publish executor response alternatives alongside the final stage contract."""

from countersign.executor import action_schema

TYPE = "type"
STRING = "string"


def object_schema(properties):
    """All executor fields are mandatory and unknown fields are rejected."""
    return {
        TYPE: "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


def request_schema(status, fields):
    """Intermediate responses share the final contract's explicit version."""
    return object_schema({"schema_version": {"const": 1}, "status": {"const": status}, **fields})


def git_schema():
    """The command executor additionally validates argv, scope and role permissions."""
    text = {TYPE: STRING, "minLength": 1}
    return request_schema(
        "GIT_REQUEST",
        {
            "root": text,
            "argv": {TYPE: "array", "minItems": 1, "items": text},
            "reason": text,
        },
    )


def ssh_schema():
    """Approval and inventory authorization remain server-side checks."""
    text = {TYPE: STRING, "minLength": 1}
    action = object_schema(
        {
            "targets": {
                TYPE: "array",
                "minItems": 1,
                "maxItems": action_schema.MAX_TARGETS,
                "uniqueItems": True,
                "items": text,
            },
            "script": text,
            "reason": text,
            "files": {TYPE: "object", "additionalProperties": {TYPE: "string"}},
            "timeout_seconds": {
                TYPE: "integer",
                "minimum": 1,
                "maximum": action_schema.MAX_TIMEOUT,
            },
        }
    )
    return request_schema("ACTION_REQUEST", {"action": action})


def local_schema():
    """Local argv is reviewed by the operator before any process starts."""
    text = {TYPE: STRING, "minLength": 1}
    return request_schema(
        "LOCAL_REQUEST",
        {
            "cwd": text,
            "argv": {TYPE: "array", "minItems": 1, "items": text},
            "reason": text,
        },
    )
