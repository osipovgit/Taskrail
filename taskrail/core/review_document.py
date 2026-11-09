"""Turn a reviewer's review.md into the review result the workflow validates and stores.

Requirement outcomes determine the verdict. Plan review accepts independent defects
on the same requirement and verifies a separate decision on each earlier finding.
"""

import re

from taskrail.core import plan_citations, plan_findings, prompt_texts, review_lines
from taskrail.core.plan_markdown import requirement_entry, unbullet

SUMMARY = "summary:"
EVIDENCE = "evidence"
GAPS = "blocking_gaps"
LABEL = "label"
BLOCKED = "BLOCKED"
IDENTIFIER = "id"


def payload(text, context, resolve):
    """The review result of review.md, or ValueError naming every problem by line.

    resolve(name, start, end) returns the absolute path a citation names.
    """
    stage = context["stage"]
    review = Review(context["requirements"], stage, resolve)
    checks = read_lines(review, text)
    if stage == review_lines.PLAN_REVIEW:
        plan_findings.reassess(review, checks, context.get("prior_findings", ()))
    prefix = review_lines.prefix(stage, context.get("stage_number", 1))
    return review.finished(prefix)


def read_lines(review, text):
    """Collect prior-ID checks separately from the ordinary requirement outcomes."""
    checks = []
    seen = set()
    for number, line in enumerate(text.splitlines(), 1):
        stripped = unbullet(line.strip())
        if review.stage == review_lines.PLAN_REVIEW and re.match(r"F\d", stripped):
            checks.append((stripped, number))
        elif stripped in seen and requirement_entry(number, stripped):
            review.problems.append(
                prompt_texts.text(
                    "finding.same_line", line=number, label=stripped.partition(":")[0]
                )
            )
        else:
            seen.add(stripped)
            review.read(number, line.strip())
    return checks


def verdict(gaps, findings):
    """A gap blocks, a failure requests changes, otherwise the review approves."""
    if gaps:
        return BLOCKED
    return "REQUEST_CHANGES" if findings else "APPROVE"


class Review:
    """The requirement lines read so far, their evidence and the problems found."""

    def __init__(self, requirements, stage, resolve):
        self.requirements = requirements
        self.stage = stage
        self._resolve = resolve
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
        if not known:
            self.problems.append("line {line}: {label} is unknown".format(**entry))
            return
        self.decide(entry, self.requirements[index])

    def decide(self, entry, requirement):
        """One requirement's outcome, its citations and what it explains."""
        decision = review_lines.classify(entry["text"], self.stage)
        if decision is None:
            self.problems.append(prompt_texts.text("review.outcome", **entry))
            self.rows[entry[LABEL]] = None
            return
        cited = self.cite(*decision, entry)
        if decision[0] in review_lines.EXPLAINED and not cited[1]:
            self.problems.append(prompt_texts.text("review.reason", **entry))
        row = row_of(entry, requirement, decision[0], cited)
        self.add(entry, row, cited[1])
        if decision[0] == review_lines.GAP:
            self.found[GAPS].append(row["explanation"])
        if decision[0] == review_lines.DEFERRED:
            self.found["unverified"].append(requirement["text"])

    def add(self, entry, row, explanation, finding_id=None):
        """Keep one coverage row while retaining each independent plan defect."""
        combined = review_lines.combine(self.rows, entry[LABEL], row, self.stage)
        if not combined:
            self.problems.append(prompt_texts.text("review.repeated", **entry))
            return
        identifiers = row["evidence_ids"]
        if row["outcome"] == review_lines.CONTRADICTED and identifiers:
            first = self.found[EVIDENCE][-len(identifiers)]["path"]
            failed = review_lines.finding(row[IDENTIFIER], first, explanation, identifiers)
            if finding_id:
                failed[IDENTIFIER] = finding_id
            self.found["findings"].append(failed)

    def cite(self, kind, detail, entry):
        """Evidence IDs of the citations and the explanation in parentheses after them."""
        cited = kind in review_lines.CITED or (kind == review_lines.PLANNED and detail)
        if not cited:
            return [], detail
        try:
            spans, explanation = plan_citations.parts(detail)
        except ValueError as error:
            self.problems.append("line {}: {}".format(entry["line"], error))
            return [], ""
        return [self.evidence(*span) for span in spans], explanation

    def evidence(self, name, start, end):
        """One cited range as an evidence entry; returns its ID."""
        cited = self.found[EVIDENCE]
        number = len(cited) + 1
        first = int(start)
        last = int(end or start)
        span = dict(
            id=f"E{number}",
            path=str(self._resolve(name, first, last)),
            line_start=first,
            line_end=last,
        )
        cited.append(span)
        return span[IDENTIFIER]

    def finished(self, prefix):
        """The stored review result; ValueError lists the problems."""
        count = len(self.requirements)
        labels = [f"R{number}" for number in range(1, count + 1)]
        missing = ", ".join(label for label in labels if label not in self.rows)
        if missing:
            self.problems.append(prompt_texts.text("review.missing", labels=missing))
        if self.problems:
            listed = "; ".join(self.problems)
            raise ValueError(f"review.md: {listed}")
        rows = [row for row in self.rows.values() if row]
        return stored(rows, self.found, self.summary, prefix)


def stored(rows, found, summary, prefix):
    """The stored shape: findings numbered, the verdict derived from gaps and findings."""
    findings = review_lines.numbered(found["findings"], prefix)
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
    row = dict(id=requirement[IDENTIFIER], outcome=kind, evidence_ids=identifiers)
    return dict(row, explanation=f"{label}: {stated}")
