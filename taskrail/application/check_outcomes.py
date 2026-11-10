"""Gate outcomes shared by stage routing, repair feedback and retry detection."""

from types import MappingProxyType

STATUS_BY_ASSESSMENT = MappingProxyType(dict(passed="PASS", failed="FAIL", unknown="UNVERIFIED"))
BLOCKING = frozenset(("FAIL", "UNVERIFIED"))


def blocks(check):
    """An inconclusive mandatory check needs resolution before review."""
    return check.get("status") in BLOCKING
