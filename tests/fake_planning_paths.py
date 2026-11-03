"""A planner copies source-checkout names and misplaced advice from its task."""

import json
from pathlib import Path


def plan(run, target, continued, prompt):
    """One correction moves prose out of Files; exact source targets need no model retry."""
    state = json.loads((run / "run.json").read_text())
    source = Path(state["worktrees"]["project"]["source"]) / target.name
    proposal = run / "plan.md"
    files = f"Files: {source}\nRead: {source}:1-3"
    if continued:
        assert "Move this entire explanation under Notes:" in prompt
        files += "\nNotes: Keep changes limited to confirmed findings."
    else:
        files = files.replace(
            "\nRead:",
            "\n- On an isolated task branch change files named by lint (`roles/*/tasks/*.yaml`).\nRead:",
        )
    proposal.write_text(proposal.read_text().replace(f"Files: {target}", files))
