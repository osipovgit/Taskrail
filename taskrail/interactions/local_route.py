"""A local command request: checked, sandboxed or approved, executed, effects adopted."""

from taskrail.interactions import (
    approval_policy,
    command_effects,
    events,
    local_actions,
    local_policy,
    local_request,
    local_sandbox,
)

MISSING_PROGRAM = "{0} is not installed on the orchestrator host. Install it, then Allow to run this exact command; or Deny."
STILL_MISSING = "Executable is still not installed on the orchestrator host"
INLINE_NOTICE = "Inline shell or Python code: review the whole script before you allow it."
REJECTED = "REJECTED"
ARGV = "argv"


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
    settled = without_decision(actions, payload)
    if settled is not None:
        return settled
    inline = local_policy.inline_script(payload[ARGV])
    notice = dict(notice=INLINE_NOTICE) if inline else install_notice(payload)
    decision = actions.approve(dict(payload, **notice))
    if decision["decision"] != "allow":
        answer = local_actions.execute(actions.run, actions.folder, payload, {}, decision)
        return actions.local_result(payload, answer)
    return executed(actions, payload, decision)


def without_decision(actions, payload):
    """The response to a refused, already decided or sandboxed request, else None.

    A command this host can sandbox runs without a decision; an installed program is
    required, so the operator can still install a missing one and allow it.
    """
    answer = refusal(actions, payload) or local_actions.previous(actions.run, payload)
    if answer is not None:
        return actions.local_result(payload, answer)
    if local_request.missing_executable(payload[ARGV]) or not local_sandbox.sandboxed(payload):
        return None
    request = dict(stage=actions.folder.name, **payload)
    decision = approval_policy.automatic(actions.run, request, approval_policy.SANDBOX)
    return executed(actions, payload, decision)


def refusal(actions, payload):
    """Why a request cannot even be offered for approval, or None."""
    roots = actions.session.environment["roots"]
    try:
        local_request.checked_request(payload, roots, writes(actions))
    except ValueError as error:
        return dict(status=REJECTED, reason=str(error))
    return None


def writes(actions):
    """Only the implementer may change files in its roots."""
    return actions.session.active[1]["role"] == "implementer"


def executed(actions, payload, decision):
    """Run an approved command and adopt what it changed in the roots."""
    automatic = decision.get("rule") == approval_policy.READ_ONLY
    if local_request.missing_executable(payload[ARGV], automatic):
        return actions.local_result(payload, dict(status=REJECTED, reason=STILL_MISSING))
    actions.session.check_sources()
    context = dict(actions.session.environment, automatic_read=automatic)
    if decision.get("rule") == approval_policy.SANDBOX:
        context[local_sandbox.WRITES] = writes(actions)
    context["timeout"] = actions.session.clock.remaining()
    answer = local_actions.execute(actions.run, actions.folder, payload, context, decision)
    response = actions.local_result(payload, answer)
    effects = command_effects.adopt(actions.session, answer.get("action_id"))
    return f"{response}\n{effects}" if effects else response


def install_notice(payload):
    """Let the operator install a missing program and allow the same command."""
    program = local_request.missing_executable(payload[ARGV])
    if program is None:
        return {}
    return dict(notice=MISSING_PROGRAM.format(program))
