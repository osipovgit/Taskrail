"""The run index written before preflight."""

from taskrail.application import check_specs
from taskrail.core.runtime import SOFTWARE_VERSION
from taskrail.observability.progress import clock

ROOTS = "roots"
TOKENS = "max_observed_tokens"


def initial_state(config):
    """The run index before preflight."""
    checks = config["verification"]
    obligations = config["task_spec"]["requirements"]
    return dict(
        version=4,
        software_version=SOFTWARE_VERSION,
        contract_version=1,
        requirements=obligations,
        check_specs=check_specs.configured(config, obligations),
        task_spec=config["task_spec"],
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
