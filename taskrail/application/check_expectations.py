"""Check a program's exit code and optional diagnostic counts against its reviewed assertions."""

import json
from collections import Counter

from taskrail.application import check_diagnostics, check_reports
from taskrail.core import schema

EXIT = "exit_code"
COUNTS = "json_counts"
FIELD = "field"
ADAPTER = "plan-command"
MAX_EXIT = 255
REPORT_ERRORS = (*check_diagnostics.PARSE_ERRORS, RecursionError)


def validate(expect):
    """An exit defaults to zero. Expected category counts cover the complete JSON array."""
    schema.require(
        isinstance(expect, dict) and expect.keys() <= {EXIT, COUNTS},
        "Invalid Verify run expectation",
    )
    code = expect.get(EXIT, 0)
    schema.require(
        check_reports.valid_count(code) and code <= MAX_EXIT,
        "Expected exit code must be an integer from 0 to 255",
    )
    if COUNTS in expect:
        validate_counts(expect.get(COUNTS))
    return dict(expect, exit_code=code)


def validate_counts(counts):
    schema.require(
        isinstance(counts, dict) and set(counts) == {FIELD, "equals"},
        "json_counts needs field and equals",
    )
    field = counts[FIELD]
    schema.require(isinstance(field, str) and bool(field), "json_counts field must be a name")
    expected = counts["equals"]
    schema.require(
        isinstance(expected, dict) and all(map(positive_count, expected.values())),
        "Expected counts must be positive integers",
    )


def positive_count(amount):
    return check_reports.valid_count(amount) and amount > 0


def assess(expect, outcome):
    """Distinguish execution, an observed mismatch and an unreadable report."""
    if outcome.get("status") not in {"SUCCEEDED", "FAILED"}:
        return check_diagnostics.unknown(ADAPTER, "No completed process")
    try:
        return compare(expect, outcome)
    except REPORT_ERRORS as error:
        return check_diagnostics.unknown(ADAPTER, str(error))


def compare(expect, outcome):
    check_diagnostics.validate_exit(outcome)
    observed = outcome[EXIT]
    passed = observed == expect[EXIT]
    report = dict(adapter=ADAPTER, expected=expect, exit_code=observed)
    wanted = expect.get(COUNTS)
    if not passed:
        report["detail"] = f"Expected exit {expect[EXIT]}, observed {observed}"
    elif wanted:
        counts = categories(outcome.get("stdout", ""), wanted[FIELD])
        report[COUNTS] = counts
        passed = counts == wanted["equals"]
        if not passed:
            report["detail"] = "Diagnostic counts differ from the reviewed expectation"
    report.update(
        status="passed" if passed else "failed",
        counts=dict(failed=int(not passed)),
        diagnostics=[],
        omitted=0,
    )
    return report


def categories(text, field):
    schema.require(
        len(text.encode()) <= check_diagnostics.MAX_REPORT, "Structured report exceeds limit"
    )
    rows = json.loads(text, object_pairs_hook=schema.unique_fields)
    schema.require(isinstance(rows, list), "Expected a complete JSON array")
    counts = Counter()
    for row in rows:
        schema.require(
            isinstance(row, dict) and isinstance(row.get(field), str), "Missing diagnostic category"
        )
        counts[row[field]] += 1
    return dict(counts)
