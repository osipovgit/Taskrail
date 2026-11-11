"""Review a real plan defect, then its repaired proposal, using exact observed citations."""

import json
from pathlib import Path

from fake_report_repair import observed


def proposal(context, role, run, emit):
    plan = run / "plan.md"
    if role == "planner":
        if not context.get("feedback"):
            plan.write_text(
                plan.read_text().replace("- Static review", "- Skip required verification")
            )
        else:
            findings = json.loads(Path(context["feedback"]["findings_file"]).read_text())[
                "findings"
            ]
            respond(plan, findings)
        return None
    if role == "plan-reviewer":
        if not any((run / "00-input/local").glob("*.json")):
            return json.dumps(
                dict(
                    schema_version=1,
                    status="LOCAL_REQUEST",
                    cwd=context["roots"]["project"],
                    argv=["ls", "."],
                    reason="Inspect the files before reviewing the proposal",
                )
            )
        lines = plan.read_text().splitlines()
        bad = next(
            (number for number, line in enumerate(lines, 1) if "Skip required" in line), None
        )
        if bad:
            observed(plan, bad, 1, emit)
            decision = (
                f"fails: {plan}:{bad}-{bad} (the proposed check skips required verification)."
            )
        else:
            snapshot = run / context["plan_result"]
            state = json.loads((run / "run.json").read_text())
            assert snapshot == run / state["results"]["plan"]
            observed(snapshot, 1, 1, emit)
            name = context["plan"]["finding_responses"][0]["id"]
            decision = f"planned: {snapshot}:1 (the revised proposal owns this work).\n- {name}: closed: {snapshot}:1 (required verification restored)"
        (run / "review.md").write_text(f"Summary: Inspect the proposal\n- R1: {decision}\n")
    elif role == "reviewer":
        review = run / "review.md"
        review.write_text(
            "\n".join(
                line + "." if line.startswith("- R") else line
                for line in review.read_text().splitlines()
            )
            + "\n"
        )
    return None


def respond(plan, findings):
    """A generic one-finding repair fixture writes the planner's accountable response."""
    plan.write_text(
        plan.read_text()
        + "\n## Finding responses\n"
        + "".join(
            f"- {entry['id']}: fixed: The revised Verify step covers the required check.\n"
            for entry in findings
        )
    )


def finding_cycle(context, role, run, emit):
    """Five independent findings on R1, including an accepted and a rejected dispute."""
    if role not in {"planner", "plan-reviewer"}:
        return
    plan = run / "plan.md"
    reference = context.get("feedback", {}).get("findings_file")
    prior = json.loads(Path(reference).read_text())["findings"] if reference else []
    partial = len(prior) == 5
    checks = ["normal input", "bad input", "static review", "empty input", "retry"]
    if role == "planner":
        states = ["Skip", "Skip", "Check", "Skip", "Skip"]
        if prior:
            states[:2] = ["Check", "Check"]
            if not partial:
                states = ["Check"] * 5
        steps = [f"- {state} {check}" for state, check in zip(states, checks, strict=True)]
        draft = plan.read_text().replace("- Static review", "\n".join(steps))
        if prior:
            draft += "\n## Finding responses\n"
            for entry in prior:
                index = int(entry["id"].partition("-")[2]) - 1
                answer = f"fixed: Added a check for {checks[index]}"
                if partial and index in {2, 4}:
                    answer = f"disputed: The current Verify step already checks {checks[index]}"
                draft += f"- {entry['id']}: {answer}\n"
        plan.write_text(draft)
        return
    lines = plan.read_text().splitlines()
    observed(plan, 1, len(lines), emit)
    review = ["Summary: Independently checked each Verify step."]
    if not prior:
        for check in checks:
            number = next(n for n, line in enumerate(lines, 1) if line.endswith(" " + check))
            review.append(f"- R1: fails: {plan}:{number} (missing check for {check})")
    else:
        responses = context["plan"]["finding_responses"]
        assert {row["id"] for row in prior} == {row["id"] for row in responses}
        pending = False
        for entry in prior:
            index = int(entry["id"].partition("-")[2]) - 1
            number = next(
                n for n, line in enumerate(lines, 1) if line.endswith(" " + checks[index])
            )
            checked = lines[number - 1].startswith("- Check")
            pending |= not checked
            status = "closed" if checked else "open"
            review.append(f"- {entry['id']}: {status}: {plan}:{number} ({lines[number - 1][2:]})")
        if not pending:
            review.append("- R1: planned")
    (run / "review.md").write_text("\n".join(review) + "\n")
