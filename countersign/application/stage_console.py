"""Console lines for a finished stage: warnings, the verdict and checks."""

from countersign.observability.progress import clock, say

STATUS = "status"
SUMMARY = "summary"


def announce(record, verdict):
    """Report the stage outcome; a verdict's status and summary also go to the record."""
    for warning in record.get("warnings", []):
        say(f"  Warning: {warning_text(warning)}")
    if isinstance(verdict, dict) and STATUS in verdict:
        record.update(verdict=verdict[STATUS], summary=verdict.get(SUMMARY, ""))
        announce_verdict(record, verdict)
    if isinstance(verdict, list):
        for check in verdict:
            say("  Check: {file} — {status}: {detail}".format(**check))


def warning_text(warning):
    """The recorded resolution, or the recovered read it refers to."""
    source = warning.get("input", {}).get("filePath", "")
    return warning.get("resolution", f"Invalid offset recovered by a later full read of {source}")


def announce_verdict(record, verdict):
    """Status, summary, findings and what remains unverified."""
    now = clock()
    say("  [{0}] Result [{1}]: {2}".format(now, record["directory"], verdict[STATUS]))
    if record[SUMMARY]:
        say("  {0}".format(record[SUMMARY].replace("\n", "\n  ")))
    for finding in verdict.get("findings", []):
        say(
            "  Finding: {0} — {1}".format(finding.get("criterion", ""), finding.get("evidence", ""))
        )
    for text in verdict.get("blocking_gaps", []) + verdict.get("unverified", []):
        say(f"  Not verified: {text}")
