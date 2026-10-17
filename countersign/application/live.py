"""Live source workflow with controlled Git and no automatic rollback."""

from countersign.application.workflow_engine import execute


def execute_task(task, settings=None, debug=False, run_dir=None, plan_response=None, resume=False):
    return execute(
        dict(
            task=task,
            settings=settings,
            debug=debug,
            run_dir=run_dir,
            plan_response=plan_response,
            resume=resume,
        )
    )
