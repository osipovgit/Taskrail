"""Materialize reviewed task decisions without inventing source observations."""

IDENTIFIER = "id"


def empty(summary):
    """A server review scope makes no source or completion claims."""
    return dict(
        schema_version=1,
        status="PLAN_READY",
        summary=summary,
        decision="none",
        coverage=[],
        evidence=[],
        unverified=[],
        blocking_gaps=[],
        steps=[],
        files_read=[],
        proposed_change_files=[],
    )


def single(step, requirements):
    """Keep one reviewed action and bind its criteria directly to child identities."""
    criteria = [entry[IDENTIFIER] for entry in requirements]
    owned = dict(step, criteria=criteria, depends_on=[])
    owned["scopes"] = list(map(scope, filter(scoped, requirements)))
    plan = empty(step["action"])
    plan.update(decision="single", steps=[owned], proposed_change_files=step["files"])
    plan["coverage"] = list(map(planned, requirements))
    runtime = [entry for entry in requirements if entry["kind"] == "runtime"]
    plan["unverified"] = [entry["text"] for entry in runtime]
    return plan


def planned(requirement):
    """Only independent implementation/review can replace these initial pending outcomes."""
    outcome = "deferred" if requirement["kind"] == "runtime" else "planned"
    return dict(
        id=requirement[IDENTIFIER],
        outcome=outcome,
        evidence_ids=[],
        explanation="Reviewed task contract",
    )


def scoped(requirement):
    """Only a scoped share needs an explicit ownership boundary."""
    return bool(requirement.get("scope"))


def scope(requirement):
    """Preserve the authenticated parent scope verbatim."""
    return dict(id=requirement[IDENTIFIER], scope=requirement["scope"])
