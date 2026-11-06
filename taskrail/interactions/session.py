"""Continue executor turns through an explicit opencode session inside one stage."""

from taskrail.application import (
    evidence_delivery,
    feedback_files,
    response_format,
)
from taskrail.application.artifacts import save_run
from taskrail.core import control
from taskrail.core.files import atomic_json, changed
from taskrail.infrastructure import opencode_api
from taskrail.infrastructure.runner import run_agent
from taskrail.interactions import context_summary, events, turn_recovery
from taskrail.interactions.actions import Actions
from taskrail.interactions.clock import StageClock

STATUS = "status"
OK = "OK"
SESSION_ID = "session_id"
TOKENS = "tokens"
ROLE = "role"
RESULT_CORRECTIONS = "result_corrections"
VALIDATION_ERRORS = "validation_errors"
RUN = "run"


class StageSession:
    """Retain one context and aggregate usage once at stage completion."""

    def __init__(self, active, state, environment, launch):
        self.active = active
        self.state = state
        self.environment = dict(environment, inline=True)
        if active[1][ROLE] != "implementer":
            self.environment["allowed"] = []
        self.launch = dict(launch)
        self.clock = StageClock(active[1]["timeout_seconds"])
        self.context = dict(session_id=None, turns=0, tokens={}, attachment={})
        self.context[RESULT_CORRECTIONS] = 0
        self.context[VALIDATION_ERRORS] = []

    def run(self):
        """One stage server serves every turn and stops with the stage."""
        runtime = self.launch.get("runtime", {})
        allow = (runtime.get("env_allow", ()), runtime.get("autocompact", False))
        startup = dict(
            timeout=self.clock.remaining(),
            check=lambda: control.check_stop(self.environment[RUN]),
        )
        try:
            with opencode_api.stage_server(
                self.launch.get("command", ()),
                self.launch.get("workspace"),
                *allow,
                startup=startup,
                attach=self.launch.get("server", True),
            ) as server:
                self.context["attachment"] = server.attachment() if server else {}
                return self.turns()
        except TimeoutError as error:
            outcome = dict(status="TIMEOUT", final_text="", errors=[str(error)])
            return self.finished(outcome)

    def turns(self):
        """Only intermediate responses continue; final validation stays independent."""
        while self.clock.remaining() > 0:
            outcome = self.turn()
            response = next_response(self, outcome)
            if response is None:
                return self.finished(outcome)
            if outcome.get("context_boundary") and outcome[STATUS] == OK:
                return self.finished(context_summary.handoff(self, outcome, response))
            if not self.continue_context(outcome, response):
                outcome.update(
                    status="SESSION_ERROR",
                    errors=["No unique opencode session ID; refusing a fresh-context retry"],
                )
                return self.finished(outcome)
        return self.finished(
            dict(status="TIMEOUT", final_text="", errors=["Stage active time exhausted"])
        )

    def turn(self):
        """Run another turn without recreating the workflow stage or allowance."""
        options = dict(
            self.launch,
            timeout=self.clock.remaining(),
            runtime=dict(
                self.launch.get("runtime", {}),
                session_id=self.context[SESSION_ID],
                attachment=self.context["attachment"],
            ),
        )
        outcome = received_turn(self, options)
        self.context["turns"] += 1
        totals = self.context[TOKENS]
        for key, count in outcome.get(TOKENS, {}).items():
            totals[key] = totals.get(key, 0) + count
        try:
            self.check_sources()
        except ValueError as error:
            outcome.update(status="SCOPE_VIOLATION", errors=[str(error)])
        if outcome[STATUS] == OK:
            self.context.pop("turn_recovery", None)
        return outcome

    def check_sources(self):
        """Keep source and Git guards before any command can execute."""
        env = self.environment
        if env.get("beyond_plan"):
            env["allowed_paths"] = env["beyond_plan"]()
        current = env["scan"]()
        control.check_delta(
            changed(env["expected"], current),
            env["allowed"],
            env["git_metadata"](env["roots"]) == env["git_before"],
        )
        env["expected"] = current

    def continue_context(self, outcome, response, handoff=False):
        """Never infer or continue an unrelated global latest session."""
        sessions = outcome.get("sessions", [])
        if len(sessions) != 1:
            return False
        if self.context[SESSION_ID] and sessions[0] != self.context[SESSION_ID]:
            return False
        self.context[SESSION_ID] = sessions[0]
        folder, record = self.active
        prompt = folder / "tool-result.md"
        prompt.write_text(
            response
            if handoff
            else response + response_format.continuation(record["stage"], folder / "request.md")
        )
        self.launch["prompt"] = prompt
        record.update(
            session_id=sessions[0],
            session_turns=self.context["turns"],
            elapsed_seconds=self.clock.elapsed(),
            paused_seconds=self.clock.paused,
        )
        atomic_json(folder / "stage.json", record)
        save_run(self.environment[RUN], self.state)
        return True

    def finished(self, outcome):
        """Charge all turns once and exclude the operator's waiting time."""
        context_summary.preserve(self.active[0], outcome)
        elapsed = round(self.clock.elapsed(), 3)
        outcome.update(elapsed_seconds=elapsed, tokens=self.context[TOKENS])
        outcome[VALIDATION_ERRORS] = self.context[VALIDATION_ERRORS]
        record = self.active[1]
        record.update(session_turns=self.context["turns"], paused_seconds=self.clock.paused)
        record[RESULT_CORRECTIONS] = self.context[RESULT_CORRECTIONS]
        record[events.REJECTIONS] = self.context.get(events.REJECTIONS, [])
        return outcome


def next_response(session, outcome):
    """Only validated or correctable intermediate responses continue."""
    feedback = Actions(session).route(outcome) or result_feedback(session, outcome)
    return feedback or turn_recovery.response(session, outcome)


def received_turn(session, options):
    """Keep prepared evidence pending until its receiving session completed the turn."""
    run = session.environment[RUN]
    prompt = session.launch["prompt"].read_text()
    outcome = run_agent(options)
    expected = session.context[SESSION_ID]
    unexpected = expected and outcome.get("sessions") != [expected]
    if unexpected and outcome[STATUS] == OK:
        outcome.update(status="SESSION_ERROR", errors=["Unexpected opencode session identity"])
    evidence_delivery.confirm(run, session.active[0], prompt, outcome, expected)
    return outcome


def result_feedback(session, outcome):
    """Return all outstanding failures while the artifact or diagnostics change."""
    check = session.environment.get("check_result")
    context = session.context
    if check is None or outcome[STATUS] != OK:
        return None
    error = check(outcome)
    if error is None:
        return None
    if turn_recovery.repeated_feedback(session, "result", error):
        return None
    context[RESULT_CORRECTIONS] += 1
    context[VALIDATION_ERRORS].append(error)
    message = feedback_files.validation(session.active[0], error)
    feedback = response_format.correction(session.active[1][ROLE], message)
    if message != error:
        feedback += evidence_delivery.pending_text(session.active[0])
    events.correction(session, "result", "final result", feedback)
    return feedback


def run_stage(active, state, environment, launch):
    """Run a stage with a single session and active-time deadline."""
    session = StageSession(active, state, environment, launch)
    try:
        return session.run()
    except BaseException:
        record_interruption(session)
        raise


def record_interruption(session):
    """Cooperative Stop settles active time even after an arbitrarily long wait."""
    folder, record = session.active
    outcome = session.finished(dict(status="INTERRUPTED"))
    record.update(elapsed_seconds=outcome["elapsed_seconds"], tokens=outcome[TOKENS])
    atomic_json(folder / "stage.json", record)
