"""Independent rechecks of outstanding plan findings, using the current review's evidence."""

from taskrail.core import finding_decisions, prompt_texts, review_lines

OPEN = "open"
IDENTIFIER = "id"
CRITERION = "criterion"


def reassess(review, lines, prior):
    """An open finding supplies a fails outcome for its requirement. Closed items stay audited."""
    decisions = finding_decisions.parse(lines, (OPEN, "closed"))
    finding_decisions.complete(decisions, prior)
    labels = requirement_labels(review.requirements)
    for finding in prior:
        decision = decisions[finding[IDENTIFIER]]
        criterion = current_criterion(finding, decision, labels)
        record_decision(review, criterion, decision, labels.get(criterion, decision[IDENTIFIER]))


def requirement_labels(requirements):
    """Use the original R label for an outstanding finding."""
    labels = {}
    for index, entry in enumerate(requirements, 1):
        labels[entry[IDENTIFIER]] = f"R{index}"
    return labels


def current_criterion(finding, decision, labels):
    """If understanding replaced the old requirement, an open issue names its current owner."""
    criterion = finding[CRITERION]
    if criterion in labels or decision["status"] != OPEN:
        return criterion
    label, _, detail = decision["reason"].partition(":")
    for name, active in labels.items():
        if label.strip() == active:
            decision["reason"] = detail.strip()
            return name
    raise ValueError(prompt_texts.text("finding.replaced", id=finding[IDENTIFIER]))


def record_decision(review, criterion, decision, label):
    """Each disposition needs an observed citation and a reason, including accepted disputes."""
    name = decision[IDENTIFIER]
    entry = dict(label=label, text=decision["reason"], line=name)
    identifiers, reason = review.cite(review_lines.CONTRADICTED, entry["text"], entry)
    if not identifiers or not reason:
        review.problems.append(prompt_texts.text("finding.proof", id=name))
        return
    decision.update(criterion=criterion, reason=reason, evidence_ids=identifiers)
    review.found.setdefault(finding_decisions.CHECKS, []).append(decision)
    if decision["status"] == OPEN:
        row = dict(id=criterion, outcome=review_lines.CONTRADICTED)
        row.update(explanation=f"{label}: {reason}", evidence_ids=identifiers)
        review.add(entry, row, reason, name)


def tracked_proof(record, failing):
    """Rebuild cannot discard a finding decision or another defect sharing its requirement."""
    checks = record.get(finding_decisions.CHECKS, ())
    if any(set(check["evidence_ids"]).intersection(failing) for check in checks):
        return True
    criteria = {entry[CRITERION] for entry in record["findings"]}
    affected = (row for row in record["coverage"] if row[IDENTIFIER] in criteria)
    return any(set(row["evidence_ids"]).intersection(failing) for row in affected)
