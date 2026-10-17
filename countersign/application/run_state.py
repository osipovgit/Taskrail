"""The run index written before preflight."""

from countersign.core import requirements
from countersign.core.runtime import SOFTWARE_VERSION
from countersign.observability.progress import clock

ROOTS = "roots"
TOKENS = "max_observed_tokens"


def initial_state(config):
    """The run index before preflight."""
    checks = config["verification"]
    return dict(
        version=4,
        software_version=SOFTWARE_VERSION,
        contract_version=1,
        requirements=requirements.task_requirements(config["task_text"], checks),
        status="RUNNING",
        stage="preflight",
        roots=stored_roots(config[ROOTS]),
        task=str(config["task"]),
        started_at=clock(),
        monitoring={TOKENS: config[TOKENS]},
        stages=[],
        attempts=[],
        changed_files=[],
        checks=[],
        unverified=checks,
        preimages={},
        results={},
        worktrees=config["worktrees"],
    )


def stored_roots(roots):
    """Roots as stored in the run index."""
    return {alias: str(path) for alias, path in roots.items()}
