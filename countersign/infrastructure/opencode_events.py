"""Translate opencode 2.x JSON events into the 1.x shape parsed by the workflow."""

import json
import os
import re

PART = "part"
SESSION = "sessionID"
READ = "read"
INPUT = "input"
ERROR = "error"
FILE_TOOLS = frozenset((READ, "edit", "write"))
PERMISSION_PREFIX = "Permission denied:"
READ_ERROR_PREFIX = "Error: "
MISSING_PREFIX = "File not found: "
FULL_READ = "<path>{0}</path>\n<type>file</type>\n<content>\n{1}\n\n(End of file - total {2} lines)\n</content>"
STOP = "stop"
# 1.x answers an unknown tool call with a completed `invalid` call; 2.x reports an error.
UNKNOWN_TOOL = re.compile(r'No tool named "[^"]+" is currently available\..*', re.S)
COUNTERS = (INPUT, "output")
CACHE_COUNTERS = ("read", "write")


class EventTranslator:
    """Keep raw events separately; emit one 1.x-shaped event per 2.x event."""

    def __init__(self, directory):
        self.directory = directory
        self.final_text = None
        self.failed = False

    def translate(self, raw):
        """Unknown or malformed lines pass through unchanged."""
        try:
            event = json.loads(raw)
        except ValueError:
            return raw
        if not isinstance(event, dict):
            return raw
        if not isinstance(event.get(PART, {}), dict):
            return raw
        return json.dumps(self.observe(event), ensure_ascii=False)

    def observe(self, event):
        kind, part = event.get("type"), event.get(PART, {})
        if kind == "tool_use":
            return dict(event, part=tool_part(part, self.directory))
        if kind == "step_finish":
            if part.get("reason") == STOP:
                self.final_text = None
            return dict(event, part=self.step_part(part))
        if kind == "text":
            self.final_text = event
        self.failed = self.failed or kind == ERROR
        return event

    def finish(self, returncode):
        """opencode 2.x may end a successful turn without its final step event."""
        if returncode or self.failed or self.final_text is None:
            return None
        session, text = self.final_text.get(SESSION), self.final_text[PART]
        stop_id = "{0}-stop".format(text.get("id", ""))
        part = dict(type="step-finish", reason=STOP, messageID=text.get("messageID"))
        part.update(id=stop_id, sessionID=session)
        return json.dumps(dict(type="step_finish", sessionID=session, part=part))

    def step_part(self, part):
        """Recover the 1.x total from the reported input, output and cache counters."""
        tokens = dict(part.get("tokens") or {})
        cache = tokens.get("cache") or {}
        counted = [tokens.get(name) for name in COUNTERS]
        counted.extend(cache.get(name) for name in CACHE_COUNTERS)
        numbers = [count for count in counted if isinstance(count, (int, float))]
        tokens.setdefault("total", sum(numbers))
        return dict(part, tokens=tokens)


def tool_part(part, directory):
    """Restore 1.x part identifiers, absolute file inputs and error tags."""
    tool = part.get("tool")
    state = part.get("state") or {}
    arguments = file_arguments(tool, state.get(INPUT) or {}, directory)
    call = part.get("id")
    translated = tool_state(tool, dict(state, input=arguments, metadata=tool_metadata(state)))
    return dict(part, id=part.get("partID", call), callID=call, state=translated)


def tool_state(tool, state):
    message = str(state.get(ERROR, ""))
    if state.get("status") == ERROR and UNKNOWN_TOOL.fullmatch(message):
        state.pop(ERROR)
        state.update(status="completed", output=message)
    elif state.get("status") == ERROR:
        state[ERROR] = tool_error(message, tool, state[INPUT])
    elif tool == READ:
        state["output"] = read_output(state)
    return state


def tool_metadata(state):
    """1.x tools report metadata such as `truncated` at the top level."""
    nested = (state.get("metadata") or {}).get("metadata")
    return nested if isinstance(nested, dict) else {}


def file_arguments(tool, arguments, directory):
    """1.x file tools take an absolute filePath; 2.x accepts a relative path."""
    arguments = dict(arguments)
    path = arguments.get("path")
    if tool in FILE_TOOLS and isinstance(path, str):
        arguments["filePath"] = os.path.normpath(os.path.join(directory, path))
    return arguments


def tool_error(message, tool, arguments):
    """Permission and missing-read classification match the 1.x messages."""
    if message.startswith(PERMISSION_PREFIX):
        return "PermissionDeniedError: {0}".format(message)
    if tool != READ or message.startswith(READ_ERROR_PREFIX):
        return message
    first, newline, rest = message.partition("\n")
    if first.startswith(MISSING_PREFIX):
        first = "{0}{1}".format(MISSING_PREFIX, arguments.get("filePath", ""))
    first = re.sub(r"\(1 line\)$", "(1 lines)", first)
    return "".join((READ_ERROR_PREFIX, first, newline, rest))


def read_output(state):
    """Only a complete file read gets the 1.x end-of-file marker."""
    output, arguments = state.get("output"), state[INPUT]
    complete = state["metadata"].get("truncated") is False
    complete = complete and arguments.get("offset", 1) == 1
    if not complete or not isinstance(output, str) or not output.startswith("Read file "):
        return output
    body = output.partition("\n")[2]
    count = len(body.splitlines())
    return FULL_READ.format(arguments.get("filePath", ""), body, count)
