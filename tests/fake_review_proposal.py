"""Review a real plan defect, then its repaired proposal, using exact observed citations."""

import json

from fake_report_repair import observed


def proposal(context, role, run, emit):
    plan = run / "plan.md"
    if role == "planner":
        if not context.get("feedback"):
            plan.write_text(
                plan.read_text().replace("- Static review", "- Skip required verification")
            )
        return
    if role == "plan-reviewer":
        if not (run / "local-execution.json").exists():
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
            state = json.loads((run / "run.json").read_text())
            snapshot = run / state["results"]["plan"]
            observed(snapshot, 1, 1, emit)
            decision = f"planned: {snapshot}:1 (the revised proposal owns this work)."
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
