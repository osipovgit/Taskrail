"""Normalize explicit linter JSON reporters without guessing semantic results."""

ERROR = "error"
COLUMN = "column"


def parse(adapter, entries):
    """Normalize the documented JSON fields of supported lint reporters."""
    if adapter == "ruff-json":
        return [ruff(entry) for entry in entries]
    if adapter == "shellcheck-json":
        return [shellcheck(entry) for entry in entries]
    if adapter == "eslint-json":
        return [eslint(report, message) for report in entries for message in report["messages"]]
    if adapter == "stylelint-json":
        return [stylelint(report, warning) for report in entries for warning in report["warnings"]]
    raise ValueError("Unsupported diagnostic adapter")


def ruff(entry):
    """Ruff JSON includes a source location and an optional rule code."""
    return dict(
        file=entry["filename"],
        line=entry["location"]["row"],
        column=entry["location"][COLUMN],
        rule=entry["code"],
        severity=ERROR,
        message=entry["message"],
    )


def shellcheck(entry):
    """ShellCheck JSON supplies exact severity and a stable numeric rule code."""
    return dict(
        file=entry["file"],
        line=entry["line"],
        column=entry[COLUMN],
        rule=f"SC{entry['code']}",
        severity=entry["level"],
        message=entry["message"],
    )


def eslint(report, entry):
    """ESLint parser failures and ordinary rule failures share its messages array."""
    return dict(
        file=report["filePath"],
        line=entry.get("line", 1),
        column=entry.get(COLUMN, 1),
        rule=entry["ruleId"],
        severity=ERROR if entry["severity"] == 2 else "warning",
        message=entry["message"],
    )


def stylelint(report, entry):
    """Stylelint's JSON formatter records source files and exact warning locations."""
    return dict(
        file=report["source"],
        line=entry["line"],
        column=entry[COLUMN],
        rule=entry["rule"],
        severity=entry["severity"],
        message=entry["text"],
    )
