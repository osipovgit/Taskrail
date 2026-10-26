"""Deterministic check assessments from explicit output formats, never keyword counts."""

import json

from countersign.application import check_lint, check_reports

MAX_REPORT = 2 * 1024 * 1024
MAX_DIAGNOSTICS = 100
ERROR = "error"
PARSE_ERRORS = (ValueError, TypeError, KeyError)


def assess(adapter, outcome):
    """A missing or malformed report cannot become a successful verification."""
    if outcome.get("status") not in {"SUCCEEDED", "FAILED"}:
        return unknown(adapter, "Execution did not produce a known result")
    try:
        parsed = parse(adapter, outcome)
    except PARSE_ERRORS:
        return unknown(adapter, "Invalid or incomplete structured check output")
    failed = bool(parsed["counts"].get("failed", 0))
    failed = failed or outcome.get("exit_code", 0) != 0
    status = "failed" if failed or outcome["status"] == "FAILED" else "passed"
    return dict(parsed, status=status, adapter=adapter)


def unknown(adapter, detail):
    """Unknown is separate from a failed assertion and a failed transport."""
    return dict(
        status="unknown", adapter=adapter, detail=detail, counts={}, diagnostics=[], omitted=0
    )


def parse(adapter, outcome):
    """Only the server recipe chooses an adapter; no output-based autodetection."""
    if adapter != "jenkins":
        validate_exit(outcome)
    if adapter == "exit-code":
        return summarized([], {})
    if adapter == "jenkins":
        return summarized(*check_reports.jenkins(outcome))
    text = outcome.get("stdout", "")
    if len(text.encode("utf-8")) > MAX_REPORT:
        raise ValueError("Structured report exceeds limit")
    if adapter == "junit":
        return summarized(*check_reports.junit(text))
    entries = json.loads(text)
    if not isinstance(entries, list):
        raise ValueError("Diagnostic report must be a list")
    diagnostics = check_lint.parse(adapter, entries)
    failed = sum(entry["severity"] == ERROR for entry in diagnostics)
    counts = dict(failed=failed)
    return summarized(diagnostics, counts)


def validate_exit(outcome):
    """A successful transport without an observed process code is not a passed check."""
    code = outcome.get("exit_code")
    if not isinstance(code, int) or isinstance(code, bool):
        raise ValueError("Missing process exit code")


def summarized(diagnostics, counts):
    """Stable ordering and explicit omission counts bound model-facing output."""
    unique = {json.dumps(entry, sort_keys=True): entry for entry in diagnostics}
    ordered = [unique[key] for key in sorted(unique)]
    return dict(
        counts=counts,
        diagnostics=ordered[:MAX_DIAGNOSTICS],
        omitted=max(0, len(ordered) - MAX_DIAGNOSTICS),
    )
