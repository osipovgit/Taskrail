"""A local command request: checked, approved, executed and its effects adopted."""

from taskrail.interactions import (
    command_effects,
    events,
    local_actions,
    local_policy,
    local_request,
)

MISSING_PROGRAM = "{0} is not installed on the orchestrator host. Install it, then Allow to run this exact command; or Deny."
STILL_MISSING = "Executable is still not installed on the orchestrator host"
INLINE_NOTICE = (
    "Inline shell or Python code: review the whole script. Allow all actions never approves it."
)
REJECTED = "REJECTED"


def run_local(actions, outcome, payload):
    """Keep a visible running call even during approval or process execution."""
    event = events.begin(actions.folder, "local_command", payload)
    try:
        response = local_action(actions, payload)
    except BaseException:
        events.finish(actions.folder, event, "Interrupted; inspect local effects before retrying.")
        raise
    events.finish(actions.folder, event, response)
    return response


def local_action(actions, payload):
    """Review exact argv and recheck sources immediately before execution."""
    refused = refusal(actions, payload)
    if refused:
        return actions.local_result(payload, refused)
    answer = local_actions.previous(actions.run, payload)
    if answer is not None:
        return actions.local_result(payload, answer)
    inline = local_policy.inline_script(payload["argv"])
    notice = dict(notice=INLINE_NOTICE) if inline else install_notice(payload)
    decision = actions.approve(dict(payload, **notice), personal=inline)
    if decision["decision"] != "allow":
        answer = local_actions.execute(actions.run, actions.folder, payload, {}, decision)
        return actions.local_result(payload, answer)
    return executed(actions, payload, decision)


def refusal(actions, payload):
    """Why a request cannot even be offered for approval, or None."""
    writer = actions.session.active[1]["role"] == "implementer"
    try:
        local_request.checked_request(payload, actions.session.environment["roots"], writer)
    except ValueError as error:
        return dict(status=REJECTED, reason=str(error))
    return None


def executed(actions, payload, decision):
    """Run an approved command and adopt what it changed in the roots."""
    automatic = decision.get("rule") == "read_only"
    if local_request.missing_executable(payload["argv"], automatic):
        return actions.local_result(payload, dict(status=REJECTED, reason=STILL_MISSING))
    actions.session.check_sources()
    context = dict(actions.session.environment, automatic_read=automatic)
    context["timeout"] = actions.session.clock.remaining()
    answer = local_actions.execute(actions.run, actions.folder, payload, context, decision)
    response = actions.local_result(payload, answer)
    effects = command_effects.adopt(actions.session, answer.get("action_id"))
    return f"{response}\n{effects}" if effects else response


def install_notice(payload):
    """Let the operator install a missing program and allow the same command."""
    program = local_request.missing_executable(payload["argv"])
    if program is None:
        return {}
    return dict(notice=MISSING_PROGRAM.format(program))
