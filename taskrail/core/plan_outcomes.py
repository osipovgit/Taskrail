"""The `## Requirements` lines of plan.md: each requirement's outcome and owners.

An outcome is the tasks that deliver the requirement (a part names its scope),
`all tasks` for an obligation every task keeps, `done:` or `contradicted:` with cited
lines, `runtime` with an optional description of the later check, `n/a:` with why the
requirement does not apply, or `gap:`.
"""

import re
from types import MappingProxyType

from taskrail.core import plan_citations, prompt_texts, read_hints
from taskrail.core.paths import absolute
from taskrail.core.plan_keys import numbered

TASK_REFERENCE = re.compile(r"(T\d+)\s*(?:\[([^\]]*)\]|\(([^)]*)\))?\s*", re.IGNORECASE)
TASK_SEPARATOR = re.compile(r"\s*[,;]\s*")
OPTIONAL_HINT = re.compile(r"<.*>|none|n/a", re.IGNORECASE)
PLACEHOLDER = re.compile(r"^<.*>$")
PLANNED = "planned"
LINE = "line"
LABEL = "label"
SATISFIED = "satisfied"
DEFERRED = "deferred"
GAP = "gap"
EVIDENCE = "evidence"
PREFIXES = MappingProxyType(
    {
        "done": SATISFIED,
        SATISFIED: SATISFIED,
        "contradicted": "contradicted",
        "runtime": DEFERRED,
        DEFERRED: DEFERRED,
        GAP: GAP,
        "blocked": GAP,
        "n/a": "not_applicable",
    }
)
CITED = frozenset((SATISFIED, "contradicted"))
EVERY_TASK = frozenset(("all tasks", "all"))
IDENTIFIER = "id"
TEXT = "text"


class Coverage:
    """Outcomes, evidence and task owners of the requirement lines, with problems."""

    def __init__(self, requirements, roots):
        """requirements are the server's, in order: R1 is the first."""
        self.requirements = requirements
        self.roots = roots
        self.problems = []
        self.found = {"coverage": [], EVIDENCE: [], "unverified": [], "blocking_gaps": []}
        self.owners = {}
        self.everyone = []

    def read(self, lines):
        """Every requirement line, then the requirements without one."""
        seen = {self.line(entry, set()) for entry in lines}
        if len(seen) != len(lines):
            self.problems.append("## Requirements: a requirement is listed twice")
        missing = missing_labels(len(self.requirements), seen)
        if missing:
            self.problems.append(f"## Requirements: no line for {missing}")

    def line(self, entry, seen):
        """One line; returns its label."""
        index = int(entry[LABEL][1:]) - 1
        if 0 <= index < len(self.requirements):
            self.outcome(self.requirements[index], entry)
        else:
            self.problems.append("line {line}: {label} is unknown".format(**entry))
        return entry[LABEL]

    def outcome(self, requirement, entry):
        """Tasks, done, contradicted, runtime or gap."""
        kind, detail = classify(entry[TEXT])
        if kind is None:
            self.problems.append("line {line}: {label} has no outcome".format(**entry))
            return
        if kind in CITED and not detail:
            self.problems.append(prompt_texts.diagnostic("validation.plan_outcome", **entry))
            return
        if kind == PLANNED:
            self.assign(requirement, entry)
        if kind == DEFERRED:
            if requirement["kind"] != "runtime":
                self.problems.append(prompt_texts.diagnostic("validation.plan_runtime", **entry))
            detail = detail or requirement[TEXT]
            self.found["unverified"].append(detail)
        if kind == "not_applicable" and not detail:
            self.problems.append("line {line}: {label} n/a needs its reason".format(**entry))
        evidence = self.cite(detail, entry[LINE]) if kind in CITED else []
        explanation = f"{entry[LABEL]}: {detail}"
        if kind == GAP:
            self.found["blocking_gaps"].append(explanation)
        record = dict(id=requirement[IDENTIFIER], outcome=kind, evidence_ids=evidence)
        self.found["coverage"].append(dict(record, explanation=explanation))

    def assign(self, requirement, entry):
        """`T1, T2 [scope]` or `all tasks`: the tasks that deliver the requirement."""
        if classify(entry[TEXT])[1] == "all tasks":
            marker = dict(id=requirement[IDENTIFIER], line=entry[LINE])
            self.everyone.append(dict(marker, label=entry[LABEL]))
            return
        references = task_references(entry[TEXT])
        if not references:
            self.problems.append(prompt_texts.diagnostic("validation.plan_outcome", **entry))
        for task, scope in references:
            owned = self.owners.setdefault(task.upper(), [])
            owned.append(dict(id=requirement[IDENTIFIER], scope=scope.strip()))

    def cite(self, detail, line, explanation=True):
        """Evidence entries for `path:from-to` citations; returns their IDs."""
        try:
            found = plan_citations.parts(detail, explanation)[0]
        except ValueError as error:
            self.problems.append(f"line {line}: {error}")
            return []
        return [self.evidence(match) for match in found]

    def evidence(self, match):
        """One cited range as an evidence entry; returns its ID."""
        name, start, end = match
        number = len(self.found[EVIDENCE]) + 1
        span = dict(
            line_start=int(start),
            line_end=int(end or start),
            id=f"E{number}",
            path=str(absolute(name, self.roots)),
        )
        self.found[EVIDENCE].append(span)
        return span["id"]


def cited_ranges(coverage, fields):
    """Keep explicit future read windows and report every malformed hint at its line."""
    hints = ([], [])
    for entry, line in numbered(fields, "read"):
        if OPTIONAL_HINT.fullmatch(entry):
            continue
        try:
            windows, reason = read_hints.parse(entry, coverage.roots)
        except ValueError:
            coverage.problems.append(prompt_texts.text("validation.read_hint", line=line))
            continue
        hints[0].extend(windows)
        if reason:
            hints[1].append(entry)
    return hints


def missing_labels(count, seen):
    """The labels R1..R<count> that have no line, comma-separated."""
    labels = [f"R{number}" for number in range(1, count + 1)]
    return ", ".join(label for label in labels if label not in seen)


def task_references(text):
    """Consume every character; a valid task ID cannot hide unparsed instructions."""
    found = []
    position = 0
    while position < len(text):
        match = TASK_REFERENCE.match(text, position)
        if match is None:
            return []
        found.append(reference(match))
        position = match.end()
        if position < len(text):
            separator = TASK_SEPARATOR.match(text, position)
            if separator is None or separator.end() == len(text):
                return []
            position = separator.end()
    names = [entry[0].upper() for entry in found]
    return found if len(set(names)) == len(names) else []


def reference(match):
    """Matching square brackets or parentheses delimit one optional ownership scope."""
    scope = match[2] or match[3] or ""
    return match[1], scope


def classify(text):
    """(outcome, detail); planned keeps the whole text, None means no outcome."""
    if not text or PLACEHOLDER.match(text):
        return None, ""
    normalized = text.strip().casefold()
    if normalized in EVERY_TASK or any(
        normalized.startswith(prefix) and plan_citations.explained(normalized[len(prefix) :])
        for prefix in EVERY_TASK
    ):
        return PLANNED, "all tasks"
    prefix, _, rest = text.partition(":")
    kind = PREFIXES.get(prefix.strip().casefold())
    return (kind, rest.strip()) if kind else (PLANNED, text)
