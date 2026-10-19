"""Live source workflow with controlled Git and no automatic rollback."""

from types import MappingProxyType

from countersign.application.workflow_engine import execute

OPTIONS = MappingProxyType(
    dict(debug=False, run_dir=None, plan_response=None, resume=False, note=None)
)


def execute_task(task, settings=None, **options):
    """Run a task, or continue one with `resume`; `note` is an operator note for the continuation."""
    unknown = set(options) - set(OPTIONS)
    if unknown:
        raise TypeError(f"Unknown execute_task options: {sorted(unknown)}")
    return execute(dict(OPTIONS, **options, task=task, settings=settings))
