"""Continue executor turns through an explicit opencode session inside one stage."""

from countersign.application import budgets
from countersign.application.artifacts import save_run
from countersign.core import control
from countersign.core.files import atomic_json, changed
from countersign.infrastructure import opencode_api
from countersign.infrastructure.runner import run_agent
from countersign.interactions.actions import Actions
from countersign.interactions.clock import StageClock

SESSION_ID = "session_id"
# opencode may summarize a long session and drop the attached instructions, so every
# continuation names the role and where its instructions and response schema are.
CONTINUE = "\nContinue the SAME task using existing context. Do not restart research. You are the {role} stage; if earlier context was summarized, re-read your instructions and response schema in {request}. Planner and reviewer stages never change project files. Return exactly one JSON object as the entire message: the next executor request or the final stage result.\n"
TOKENS = "tokens"


class StageSession:
    """Retain one context and aggregate usage once at stage completion."""

    def __init__(self, active, state, environment, launch):
        self.active = active
        self.state = state
        self.environment = dict(environment, inline=True)
        if active[1]["role"] != "implementer":
            self.environment["allowed"] = []
        self.launch = dict(launch)
        self.clock = StageClock(active[1]["budget"]["timeout"])
        self.context = dict(session_id=None, turns=0, tokens={}, attachment={})
        self.context["corrections"] = 0

    def run(self):
        """One stage server serves every turn and stops with the stage."""
        launch = self.launch
        allow = launch.get("runtime", {}).get("env_allow", ())
        command = launch.get("command", ())
        with opencode_api.stage_server(command, launch.get("workspace"), allow) as server:
            self.context["attachment"] = server.attachment() if server else {}
            return self.turns()

    def turns(self):
        """Only intermediate responses continue; final validation stays independent."""
        while self.clock.remaining() > 0:
            outcome = self.turn()
            response = Actions(self).route(outcome)
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
            response + CONTINUE.format(role=record["role"], request=folder / "request.md")
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
        record = self.active[1]
        record.update(session_turns=self.context["turns"], paused_seconds=self.clock.paused)
        return outcome


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
