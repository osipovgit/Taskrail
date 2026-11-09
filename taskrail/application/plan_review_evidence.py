"""The current proposal is evidence of planned work or a plan defect, never completion."""

from pathlib import Path

from taskrail.application import reviewed_artifacts
from taskrail.core import prompt_texts, schema
from taskrail.core.paths import tool_paths

STAGE = "plan-reviewer"


def paths(run, stage, reference):
    """Exact files of the current accepted planner result, not its whole attempt directory."""
    if stage != STAGE or not reference:
        return []
    snapshot = run / reference
    canonical = snapshot.resolve() == snapshot and snapshot.parent.parent == run
    if not canonical or snapshot.name != "result.json":
        return []
    return [run / "plan.md", snapshot]


def sources(context):
    """The server-owned current result reference supplies the scope."""
    return paths(context["run"], context.get("stage"), context.get("plan_reference"))


def accepts(claim, payload, context):
    """Authenticate the proposal and require every citation owner to discuss planned work."""
    if Path(claim["path"]) not in sources(context):
        return False
    identifier = claim["id"]
    owners = [row for row in payload["coverage"] if identifier in row["evidence_ids"]]
    kinds = {row["outcome"] for row in owners}
    rechecked = any(
        identifier in decision["evidence_ids"] for decision in payload.get("finding_checks", ())
    )
    permitted = (bool(owners) or rechecked) and kinds <= {"planned", "contradicted"}
    schema.require(permitted, prompt_texts.diagnostic("validation.plan_review_evidence"))
    return True


def verify(context):
    """Both readable plan copies and the result must still match the proposal being reviewed."""
    files = sources(context)
    schema.require(
        files and all(map(regular, files)),
        prompt_texts.diagnostic("validation.plan_review_changed"),
    )
    recorded = reviewed_artifacts.document(context["run"], context["plan_reference"])
    expected = tool_paths(context["plan"], context["roots"])
    matching = recorded == expected and markdown_matches(files)
    schema.require(matching, prompt_texts.diagnostic("validation.plan_review_changed"))


def regular(path):
    """No symlink or missing file may substitute for the proposal."""
    return path.resolve() == path and path.is_file()


def markdown_matches(files):
    """The archived copy stays server-only; the reviewer cites the readable current plan."""
    saved = files[1].with_name("plan.md")
    return regular(saved) and files[0].read_bytes() == saved.read_bytes()
