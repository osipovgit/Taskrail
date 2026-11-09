"""Attempts of one model stage until a valid verdict or a recorded stop."""

from functools import partial

from taskrail.application import (
    attempt_context,
    evidence,
    plan_recovery,
    prompts,
    result_preview,
    session_budget,
    stage_artifacts,
)
from taskrail.application.attempt_launch import (
    attempt_prompt,
    install_profile,
    open_record,
    planned_files,
)
from taskrail.application.attempt_retries import Retries
from taskrail.application.attempt_session import (
    announce,
    invalid,
    launch_options,
    session_environment,
    validated,
)
from taskrail.application.changes import write_diff
from taskrail.application.plan_review_evidence import paths as review_paths
from taskrail.application.result_context import git_directory
from taskrail.application.task_branch import KEY as TASK_BRANCH
from taskrail.application.task_branch import extend as extend_beyond_plan
from taskrail.interactions import request_limits
from taskrail.interactions.session import run_stage

STATUS = "status"
RUNNING = "RUNNING"
STAGE = "stage"
EXECUTION_KEYS = ("stage", "plan", "allowed", "feedback")


class StageAttempts:
    """Bounded attempts share one request, recovery evidence and retry allowance."""

    def __init__(self, workflow):
        """Build the stage request; consume evidence restored by a continuation."""
        self.workflow = workflow
        request_limits.reset(workflow.run, workflow.flow[STAGE])
        self.request = first_request(workflow)
        self.recovery = workflow.runtime["recovery"]
        workflow.runtime["recovery"] = None
        self.retries = Retries(self)

    def run(self):
        """Return (verdict, record), or None once the state records a stop."""
        while self.workflow.state[STATUS] == RUNNING:
            active = self.prepare()
            outcome = self.launch(active)
            if outcome is None:
                return None
            verdict = self.conclude(active[1], outcome)
            if verdict is None:
                self.retry(active[1], outcome)
            else:
                return verdict, active[1]
        return None

    def retry(self, record, outcome):
        """Prepare the next attempt, or record why the stage stops."""
        if self.workflow.writable():
            write_diff(self.workflow)
        if not self.retries.allowed(outcome):
            fail(self.workflow.state, record, outcome)

    def prepare(self):
        """Open the record and store exactly what the model receives."""
        workflow = self.workflow
        workflow.guard.verify("Source/Git changed before retry; recorded evidence is stale")
        folder, record = open_record(workflow, self.retries.mode())
        record["result_rebuild"] = bool(self.retries.repair)
        record["writable_files"] = [str(path) for path in planned_files(workflow)]
        stage_artifacts.record_access(workflow, record)
        prompt = attempt_prompt(workflow, (folder, record), self.request, self.recovery)
        attempt_context.save_request(folder, record, prompt, workflow)
        return folder, record

    def launch(self, active):
        """Launch the session with its model window and steering timeout."""
        workflow = self.workflow
        files = planned_files(workflow)
        profile = install_profile(workflow, active, files)
        session_budget.capture(workflow.config, active)
        announce(active[1])
        outcome = run_stage(
            active,
            workflow.state,
            session_environment(workflow, profile, checker(workflow, active)),
            launch_options(workflow, active),
        )
        self.settle(active, outcome)
        return outcome

    def settle(self, active, outcome):
        """Record usage, adopt executor effects and check the source delta."""
        workflow = self.workflow
        guard = workflow.guard
        elapsed = workflow.runtime["stage_elapsed"]
        elapsed[self.retries.stage] = (
            elapsed.get(self.retries.stage, 0) + outcome["elapsed_seconds"]
        )
        attempt_context.record_outcome(workflow.run, workflow.state, active[1], outcome)
        prior = (guard.expected, guard.git_before)
        guard.adopt(*workflow.state.pop("source_effect", prior))
        if workflow.writable() and workflow.config.get(TASK_BRANCH):
            extend_beyond_plan(workflow)
        workflow.state["changed_files"] = guard.accept(workflow.writable())
        evidence.refresh(workflow.run, active[0] / "events.jsonl", evidence_roots(workflow))
        workflow.checkpoint()

    def conclude(self, record, outcome):
        """Return a valid verdict or finish the record with its failure."""
        workflow = self.workflow
        if outcome[STATUS] != "OK":
            recovered = plan_recovery.recover(workflow, record, outcome)
            if recovered is not None:
                workflow.finish_active("RESULT_VALID", recovered, outcome)
                return recovered
            workflow.finish_active(outcome[STATUS], diagnostics=outcome)
            return None
        try:
            verdict = validated(workflow, record, outcome)
        except (ValueError, TypeError) as error:
            invalid(workflow, outcome, error)
            return None
        workflow.finish_active("RESULT_VALID", verdict, outcome)
        return verdict


def checker(workflow, active):
    """Validate a final response inside the session, before the stage ends."""
    return partial(result_preview.preview, workflow, active, evidence_roots(workflow))


def first_request(workflow):
    """The current stage request uses the same declared authority on continuation."""
    execution = tuple(workflow.flow[key] for key in EXECUTION_KEYS)
    return prompts.make_request(workflow.config, execution, workflow.state, workflow.run)


def evidence_roots(workflow):
    """Sources, executor output snapshots and original files that reads may cite."""
    run = workflow.run
    inputs = run / "00-input"
    reference = workflow.state["results"].get("plan")
    return [
        *workflow.config["roots"].values(),
        git_directory(run),
        inputs / "ssh",
        inputs / "local",
        inputs / "checks",
        inputs / "source-views",
        inputs / "preimages",
        inputs / "original",
        *review_paths(run, workflow.flow[STAGE], reference),
    ]


def fail(state, record, outcome):
    """Stop the run with the most specific reason the attempt recorded."""
    errors = "; ".join(outcome.get("errors", []))
    detail = outcome.get("contract_error") or errors or outcome[STATUS]
    summary = "Stage {} failed: {}".format(record["directory"], detail)
    state.update(status=outcome[STATUS], summary=summary)
