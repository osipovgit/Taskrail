"""Turn a reviewer's review.md into the review result the workflow validates and stores.

One line per requirement: `R<n>: done: <citations>`, `fails: <citations> (<problem>)`,
`gap: <what is missing>`, `n/a: <why it does not apply>`, `later: <the check after
delivery>` and, in plan review, `planned` (see `review_lines`). Other lines are free
notes. The server derives the verdict: a gap blocks, a failure requests changes,
otherwise the review approves. Every problem names its line.
"""

from taskrail.core import plan_citations, prompt_texts, review_lines
from taskrail.core.plan_markdown import requirement_entry

SUMMARY = "summary:"
PROBLEM_LIMIT = 12
EVIDENCE = "evidence"
GAPS = "blocking_gaps"
LABEL = "label"
BLOCKED = "BLOCKED"


def payload(text, requirements, stage, resolve):
    """The review result of review.md, or ValueError naming every problem by line.

    resolve(name, start, end) returns the absolute path a citation names.
    """
    review = Review(requirements, dict(stage=stage, resolve=resolve))
    for number, line in enumerate(text.splitlines(), 1):
        review.read(number, line.strip())
    return review.finished()


def verdict(gaps, findings):
    """A gap blocks, a failure requests changes, otherwise the review approves."""
    if gaps:
        return BLOCKED
    return "REQUEST_CHANGES" if findings else "APPROVE"


class Review:
    """The requirement lines read so far, their evidence and the problems found."""

    def __init__(self, requirements, options):
        self.requirements = requirements
        self.options = options
        self.summary = ""
        self.rows = {}
        self.found = {EVIDENCE: [], "findings": [], GAPS: [], "unverified": []}
        self.problems = []

    def read(self, number, line):
        """A summary line, a requirement line or a free note."""
        if line.casefold().startswith(SUMMARY):
            self.summary = line[len(SUMMARY) :].strip()
            return
        entry = requirement_entry(number, line)
        if entry is None:
            return
        index = int(entry[LABEL][1:]) - 1
        known = 0 <= index < len(self.requirements)
        if not known or entry[LABEL] in self.rows:
            self.problems.append("line {line}: {label} is unknown or repeated".format(**entry))
            return
        self.decide(entry, self.requirements[index])

    def decide(self, entry, requirement):
        """One requirement's outcome, its citations and what it explains."""
        decision = review_lines.classify(entry["text"], self.options["stage"])
        if decision is None:
            self.problems.append(prompt_texts.text("review.outcome", **entry))
            self.rows[entry[LABEL]] = None
            return
        cited = self.cite(*decision, entry)
        if decision[0] in review_lines.EXPLAINED and not cited[1]:
            self.problems.append(prompt_texts.text("review.reason", **entry))
        row = row_of(entry, requirement, decision[0], cited)
        self.rows[entry[LABEL]] = row
        self.consequence(row, requirement, cited[1])

    def cite(self, kind, detail, entry):
        """Evidence IDs of the citations and the explanation in parentheses after them."""
        cited = kind in review_lines.CITED or (kind == review_lines.PLANNED and detail)
        if not cited:
            return [], detail
        try:
            spans = plan_citations.parse(detail)
        except ValueError as error:
            self.problems.append("line {}: {}".format(entry["line"], error))
            return [], review_lines.parenthesized(detail)
        return [self.evidence(*span) for span in spans], review_lines.parenthesized(detail)

    def evidence(self, name, start, end):
        """One cited range as an evidence entry; returns its ID."""
        cited = self.found[EVIDENCE]
        number = len(cited) + 1
        first = int(start)
        last = int(end or start)
        span = dict(
            id=f"E{number}",
            path=str(self.options["resolve"](name, first, last)),
            line_start=first,
            line_end=last,
        )
        cited.append(span)
        return span["id"]

    def consequence(self, row, requirement, explanation):
        """A failure is a finding, a gap blocks, a later check stays unverified."""
        identifiers = row["evidence_ids"]
        if row["outcome"] == review_lines.CONTRADICTED and identifiers:
            first = self.found[EVIDENCE][-len(identifiers)]["path"]
            failed = review_lines.finding(requirement["id"], first, explanation, identifiers)
            self.found["findings"].append(failed)
        if row["outcome"] == review_lines.GAP:
            self.found[GAPS].append(row["explanation"])
        if row["outcome"] == review_lines.DEFERRED:
            self.found["unverified"].append(requirement["text"])

    def finished(self):
        """The stored review result; ValueError lists the problems."""
        count = len(self.requirements)
        labels = [f"R{number}" for number in range(1, count + 1)]
        missing = ", ".join(label for label in labels if label not in self.rows)
        if missing:
            self.problems.append(prompt_texts.text("review.missing", labels=missing))
        if self.problems:
            listed = "; ".join(self.problems[:PROBLEM_LIMIT])
            raise ValueError(f"review.md: {listed}")
        rows = [row for row in self.rows.values() if row]
        return stored(rows, self.found, self.summary)


def stored(rows, found, summary):
    """The stored shape: findings numbered, the verdict derived from gaps and findings."""
    findings = review_lines.numbered(found["findings"])
    status = verdict(found[GAPS], findings)
    record = dict(found, schema_version=1, status=status, coverage=rows, findings=findings)
    record.update(input_complete=status != BLOCKED)
    record["summary"] = summary or f"{len(rows)} requirement decisions."
    return record


def row_of(entry, requirement, kind, cited):
    """The coverage row of a requirement line; cited is (evidence IDs, explanation)."""
    identifiers, explanation = cited
    label = entry[LABEL]
    stated = explanation or entry["text"]
    row = dict(id=requirement["id"], outcome=kind, evidence_ids=identifiers)
    return dict(row, explanation=f"{label}: {stated}")
