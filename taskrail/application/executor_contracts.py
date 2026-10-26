"""Publish executor response alternatives alongside the final stage contract."""

from taskrail.executor import action_schema

TYPE = "type"
STRING = "string"
REASON = "reason"


def text_schema():
    """A nonempty string."""
    return {TYPE: STRING, "minLength": 1}


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
    text = text_schema()
    return request_schema(
        "GIT_REQUEST",
        {
            "root": text,
            "argv": {TYPE: "array", "minItems": 1, "items": text},
            REASON: text,
        },
    )


def ssh_schema():
    """Approval and inventory authorization remain server-side checks."""
    text = text_schema()
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
            REASON: text,
            "files": {TYPE: "object", "additionalProperties": {TYPE: "string"}},
            "timeout_seconds": {
                TYPE: "integer",
                "minimum": 1,
                "maximum": action_schema.MAX_TIMEOUT,
            },
        }
    )
    return request_schema("ACTION_REQUEST", {"action": action})


def jenkins_schema():
    """Server, job and parameter allowlists remain executor-side checks."""
    text = text_schema()
    request = object_schema(
        {
            "server": text,
            "job": text,
            "operation": {"enum": ["status", "console", "tests", "build"]},
            "build": {"oneOf": [{"enum": ["last", "new"]}, {TYPE: "integer", "minimum": 1}]},
            "parameters": {TYPE: "object", "additionalProperties": {TYPE: STRING}},
            REASON: text,
            "timeout_seconds": {
                TYPE: "integer",
                "minimum": 1,
                "maximum": action_schema.MAX_TIMEOUT,
            },
        }
    )
    return request_schema("JENKINS_REQUEST", {"jenkins": request})


def local_schema():
    """Local argv is reviewed by the operator before any process starts."""
    text = text_schema()
    return request_schema(
        "LOCAL_REQUEST",
        {
            "cwd": text,
            "argv": {TYPE: "array", "minItems": 1, "items": text},
            REASON: text,
        },
    )
