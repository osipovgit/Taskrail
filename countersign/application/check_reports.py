"""Structured test report parsing, separate from execution and model verdicts."""

from types import MappingProxyType
from xml.etree import ElementTree

COUNTS = MappingProxyType(dict(passed="passCount", failed="failCount", skipped="skipCount"))
BUILD_RESULTS = frozenset(("SUCCESS", "FAILURE", "UNSTABLE", "ABORTED", "NOT_BUILT"))


def junit(text):
    """Parse test cases without accepting DTDs or externally defined entities."""
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("DTD is not a test report")
    document = ElementTree.fromstring(text)
    if document.tag not in {"testsuite", "testsuites"}:
        raise ValueError("Expected JUnit report")
    cases = list(document.iter("testcase"))
    if not cases:
        raise ValueError("JUnit verification did not report any test cases")
    failed = [case for case in cases if failed_case(case)]
    diagnostics = [
        dict(
            test=case.get("name", ""),
            suite=case.get("classname", ""),
            message="\n".join(case.itertext()),
        )
        for case in failed
    ]
    return diagnostics, case_counts(cases, failed)


def jenkins(outcome):
    """A completed build and its test report must refer to the same pinned build."""
    build = outcome["build"]
    completed_build(build)
    if outcome.get("tests_status") != "available":
        raise ValueError("Missing Jenkins test report")
    tests = outcome["tests"]
    counts = {name: tests[field] for name, field in COUNTS.items()}
    if any(not valid_count(number) for number in counts.values()):
        raise ValueError("Invalid Jenkins test counts")
    if not counts["passed"] + counts["failed"]:
        raise ValueError("Jenkins verification did not execute any test cases")
    return tests["failed_cases"], counts


def completed_build(build):
    """Only a pinned, terminal Jenkins build can substantiate runtime acceptance."""
    number = build.get("number")
    if not valid_count(number) or not number:
        raise ValueError("Missing pinned Jenkins build")
    if build.get("building") is not False or build.get("result") not in BUILD_RESULTS:
        raise ValueError("Incomplete Jenkins verification")


def failed_case(case):
    """An explicit JUnit failure or error marks a failed case."""
    return case.find("failure") is not None or case.find("error") is not None


def valid_count(number):
    """Report counts are nonnegative integers, never booleans."""
    return isinstance(number, int) and not isinstance(number, bool) and number >= 0


def case_counts(cases, failed):
    """Count actual case outcomes rather than trusting suite summary attributes."""
    if any(case.find("skipped") is not None for case in failed):
        raise ValueError("A failed JUnit case cannot also be skipped")
    skipped = sum(case.find("skipped") is not None for case in cases)
    passed = len(cases) - len(failed) - skipped
    if not passed + len(failed):
        raise ValueError("JUnit verification did not execute any test cases")
    return dict(passed=passed, failed=len(failed), skipped=skipped)
