"""Verify that opencode enforces a managed profile before any model runs."""

import json
import re
import subprocess
from types import MappingProxyType

from countersign.infrastructure import opencode_cli
from countersign.infrastructure.process_group import stop_group

LISTING_SECONDS = 60
ANSI = re.compile(r"\x1b\[[0-9;]*m")
INVALID_LIST = "Invalid effective permission list"
RESET = MappingProxyType(dict(permission="*", pattern="*", action="deny"))


def verify_permissions(command, cwd, name, expected, log):
    """Only a verified closed policy can authorize a live write; rights are never approximated."""
    code = run_listing(command, cwd, log)
    text = ANSI.sub("", log.read_text(errors="replace"))
    actual = listed_rules(text, name, code, log)
    check_closed(actual, expected, log)
    return actual


def run_listing(command, cwd, log):
    """`opencode agent list` with its output in log; the process group is always stopped."""
    with log.open("wb") as output:
        process = subprocess.Popen(
            [*command, "agent", "list"],
            cwd=cwd,
            env=opencode_cli.environment(),
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            return process.wait(timeout=LISTING_SECONDS)
        except BaseException:
            stop_group(process.pid)
            process.wait()
            raise
        finally:
            stop_group(process.pid)


def listed_rules(text, name, code, log):
    """The effective rules printed after the managed agent's name."""
    match = re.search(f"(?m)^{re.escape(name)}\\s+\\(primary\\)\\s*", text)
    if code or not match:
        raise ValueError(f"opencode did not expose the managed agent permissions; inspect {log}")
    actual = decoded_rules(text[match.end() :].lstrip(), log)
    if not all(isinstance(rule, dict) for rule in actual):
        raise ValueError(INVALID_LIST)
    return actual


def decoded_rules(remainder, log):
    """The JSON rule list at the start of the remaining listing."""
    try:
        actual = json.JSONDecoder().raw_decode(remainder)[0]
    except ValueError:
        raise ValueError(f"Cannot parse opencode permissions: {log}") from None
    if not isinstance(actual, list):
        raise ValueError(INVALID_LIST)
    return actual


def check_closed(actual, expected, log):
    """Rules after the last default deny must equal the requested policy.

    Extra explicit denials are safe, but cannot erase a required allow rule.
    """
    suffix = closed_suffix(actual)
    kept = []
    for rule in suffix:
        if rule in expected or rule.get("action") != "deny":
            kept.append(rule)
    if kept != expected:
        raise ValueError(
            f"Effective opencode permissions differ from requested policy; inspect {log}"
        )


def closed_suffix(actual):
    """Rules after the last default deny, without opencode's tool-output guard.

    opencode appends that guard to every agent: a directory access guard, not
    permission to edit or execute anything.
    """
    resets = [index for index, rule in enumerate(actual) if rule == RESET]
    if not resets:
        raise ValueError("opencode ignored default-deny policy; no model launched")
    guard = dict(permission="external_directory", action="allow")
    guard["pattern"] = opencode_cli.tool_output_pattern()
    return [rule for rule in actual[resets[-1] :] if rule != guard]
