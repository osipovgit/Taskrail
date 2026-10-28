"""Continue executor turns through an explicit opencode session inside one stage."""

from taskrail.application import budgets, plan_write, response_format
from taskrail.application.artifacts import save_run
from taskrail.core import control
from taskrail.core.files import atomic_json, changed
from taskrail.infrastructure import opencode_api
from taskrail.infrastructure.runner import run_agent
from taskrail.interactions import events, provider_resume, request_limits
from taskrail.interactions.actions import Actions
from taskrail.interactions.clock import StageClock

SESSION_ID = "session_id"
TOKENS = "tokens"
MAX_RESULT_CORRECTIONS = 3
ROLE = "role"
RESULT_CORRECTIONS = "result_corrections"
VALIDATION_ERRORS = "validation_errors"


class StageSession:
    """Retain one context and aggregate usage once at stage completion."""

    def __init__(self, active, state, environment, launch):
        self.active = active
        self.state = state
        self.environment = dict(environment, inline=True)
        if active[1][ROLE] != "implementer":
            self.environment["allowed"] = []
        self.launch = dict(launch)
        self.clock = StageClock(active[1]["budget"]["timeout"])
        self.context = dict(session_id=None, turns=0, tokens={}, attachment={})
        self.context["corrections"] = 0
        self.context[RESULT_CORRECTIONS] = 0
        self.context[VALIDATION_ERRORS] = []

    def run(self):
        """One stage server serves every turn and stops with the stage."""
        runtime = self.launch.get("runtime", {})
        allow = (runtime.get("env_allow", ()), runtime.get("autocompact", False))
        startup = dict(
            timeout=self.clock.remaining(),
            check=lambda: control.check_stop(self.environment["run"]),
        )
        try:
            with opencode_api.stage_server(
                self.launch.get("command", ()),
                self.launch.get("workspace"),
                *allow,
                startup=startup,
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
            if request_limits.check(self, outcome):
                return self.finished(outcome)
            response = Actions(self).route(outcome) or result_feedback(self, outcome)
            response = response or provider_resume.response(self, outcome)
            if response is None:
                return self.finished(outcome)
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
        outcome = run_agent(options)
        self.context["turns"] += 1
        totals = self.context[TOKENS]
        for key, count in outcome.get(TOKENS, {}).items():
            totals[key] = totals.get(key, 0) + count
        try:
            self.check_sources()
        except ValueError as error:
            outcome.update(status="SCOPE_VIOLATION", errors=[str(error)])
        return outcome

    def check_sources(self):
        """Keep source and Git guards before any command can execute."""
        env = self.environment
        if env.get("beyond_plan"):
            env["beyond_plan"]()
        current = env["scan"]()
        control.check_delta(
            changed(env["expected"], current),
            env["allowed"],
            env["git_metadata"](env["roots"]) == env["git_before"],
        )
        env["expected"] = current

    def continue_context(self, outcome, response):
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
            response + response_format.continuation(record[ROLE], folder / "request.md")
        )
        self.launch["prompt"] = prompt
        record.update(
            session_id=sessions[0],
            session_turns=self.context["turns"],
            elapsed_seconds=self.clock.elapsed(),
            paused_seconds=self.clock.paused,
        )
        atomic_json(folder / "stage.json", record)
        save_run(self.environment["run"], self.state)
        return True

    def finished(self, outcome):
        """Charge all turns once and exclude the operator's waiting time."""
        elapsed = round(self.clock.elapsed(), 3)
        outcome.update(elapsed_seconds=elapsed, tokens=self.context[TOKENS])
        outcome[VALIDATION_ERRORS] = self.context[VALIDATION_ERRORS]
        record = self.active[1]
        record.update(session_turns=self.context["turns"], paused_seconds=self.clock.paused)
        record[RESULT_CORRECTIONS] = self.context[RESULT_CORRECTIONS]
        return outcome


def result_feedback(session, outcome):
    """Return a final result that fails validation to the same session, three times per stage.

    The session still has its context and tools; a later format repair has neither.
    """
    check = session.environment.get("check_result")
    context = session.context
    correction = plan_feedback(session, outcome)
    if correction is not None:
        return correction
    if check is None or session.environment["format_only"] or outcome["status"] != "OK":
        return None
    if context[RESULT_CORRECTIONS] >= MAX_RESULT_CORRECTIONS:
        return None
    error = check(outcome)
    if error is None:
        return None
    context[RESULT_CORRECTIONS] += 1
    context[VALIDATION_ERRORS].append(error)
    feedback = response_format.correction(session.active[1][ROLE], error)
    events.append(session.active[0], "correction", dict(response="final result"), feedback)
    return feedback


def plan_feedback(session, outcome):
    """Recover a rejected plan edit without restarting or asserting a fictitious read."""
    context = session.context
    eligible = session.active[1][ROLE] == "planner"
    eligible = eligible and not session.environment["format_only"]
    if not eligible or context[RESULT_CORRECTIONS] >= MAX_RESULT_CORRECTIONS:
        return None
    feedback = plan_write.read_before_write(outcome, session.environment["run"])
    if feedback is not None:
        context[RESULT_CORRECTIONS] += 1
        events.append(session.active[0], "correction", dict(response="unread plan"), feedback)
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
    if (folder.parent / budgets.BUDGET_FILE).exists():
        budgets.settle(folder.parent, folder.name, outcome)
    atomic_json(folder / "stage.json", record)
