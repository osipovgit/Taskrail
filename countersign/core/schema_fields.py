"""Addressed validation diagnostics for the supported schema vocabulary."""


class ContractError(ValueError):
    """A stable error code and JSON pointer for an addressed model correction."""

    def __init__(self, code, path, message):
        self.code = code
        self.path = path or "/"
        self.detail = message
        super().__init__(f"{code} at {self.path}: {message}")


def require(condition, code, path, message):
    """Reject a field without asking the model to rediscover its location."""
    if not condition:
        raise ContractError(code, path, message)


def pointer(path, name):
    """Escape one JSON pointer component without changing the source field name."""
    escaped = name.replace("~", "~0").replace("/", "~1")
    return f"{path}/{escaped}"


def object_fields(payload, specification, path):
    """Require declared keys while preserving optional authored fields."""
    fields = specification["properties"]
    required = specification.get("required", fields)
    missing = sorted(set(required) - set(payload))
    unknown = sorted(set(payload) - set(fields))
    require(
        not missing and not unknown,
        "FIELD_KEYS",
        path,
        f"Missing fields: {missing}; unknown fields: {unknown}",
    )
    return fields


def array(payload, specification, path, visitor):
    """Bound lists before visiting each addressed member."""
    maximum = specification.get("maxItems")
    bounded = maximum is None or len(payload) <= maximum
    require(bounded, "FIELD_SIZE", path, "Too many items")
    for index, entry in enumerate(payload):
        visitor(entry, specification["items"], f"{path}/{index}")
