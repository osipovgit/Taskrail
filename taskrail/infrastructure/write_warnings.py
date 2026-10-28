"""Prove that an approved file overwrite was completed after a native read.

The orchestrator's own run files are attached to every turn, so a new process of a
continued session knows them as read. Should a native rejection still reach one of
them, it is a warning: such a file is a note, never evidence. Project files keep the
proof.
"""

REJECTION = "You must read file {0} before overwriting it. Use the Read tool first"
NOTE_RESOLUTION = "A rejected overwrite of an orchestrator run file is not a failure: the file is a note, never evidence. Result validation and independent review still apply."
RESOLUTION = "The rejected overwrite was followed by an actual read and successful write of the same approved file in the same session. Result validation and independent review still apply."
WRITERS = frozenset(("write", "edit"))
TOOLS = WRITERS | {"read"}
PROVENANCE = ("event_line", "call_id", "part_id")
EVENT_LINE = "event_line"
TOOL = "tool"
INPUT = "input"
FILE_PATH = "filePath"
ERROR = "error"
ERRORS = "errors"


class FileWrites:
    """Record completed native operations only for server-approved writable files."""

    def __init__(self, targets, notes=()):
        """Without explicit writable paths, no failed write may be recovered."""
        self.targets = frozenset(targets)
        self.notes = frozenset(map(str, notes))
        self.calls = []
        self.seen = set()

    def observe(self, event_line, event):
        """Keep actual completed operations with their original session and event identity."""
        if not self.targets or event.get("type") != "tool_use":
            return
        part = event.get("part", {})
        state = part.get("state", {})
        identity = call_identity(event, part)
        if not all(identity) or identity in self.seen:
            return
        target = state.get(INPUT, {}).get(FILE_PATH)
        if target not in self.targets or part.get(TOOL) not in TOOLS:
            return
        if state.get("status") != "completed":
            return
        self.seen.add(identity)
        self.calls.append(
            dict(
                tool=part[TOOL],
                session_id=event.get("sessionID"),
                event_line=event_line,
                call_id=part.get("callID"),
                part_id=part.get("id"),
                target=target,
            )
        )

    def recover(self, outcome, final_line):
        """Retain a known rejection as a warning only with a later read/write proof."""
        self.excuse_notes(outcome)
        sessions = outcome["sessions"]
        answered = final_line is not None and outcome["final_text"].strip()
        if not self.targets or not answered or len(sessions) != 1:
            return outcome
        for failure in outcome["tool_errors"]:
            proof = self.recovery(failure, sessions[0], final_line)
            if proof is not None and failure[ERROR] in outcome[ERRORS]:
                failure.update(recovered_by=proof, resolution=RESOLUTION)
                outcome["warnings"].append(dict(failure))
                outcome[ERRORS].remove(failure[ERROR])
        return outcome

    def excuse_notes(self, outcome):
        """A known rejection of an orchestrator run file never fails the turn."""
        for failure in outcome["tool_errors"]:
            target = failure.get(INPUT, {}).get(FILE_PATH)
            if target not in self.notes or not unread(failure, target):
                continue
            if failure[ERROR] in outcome[ERRORS]:
                failure.update(resolution=NOTE_RESOLUTION)
                outcome["warnings"].append(dict(failure))
                outcome[ERRORS].remove(failure[ERROR])

    def recovery(self, failure, session_id, final_line):
        """Only the known rejection in the completed session can use an observed proof."""
        target = failure.get(INPUT, {}).get(FILE_PATH)
        if target not in self.targets or failure.get("session_id") != session_id:
            return None
        if not unread(failure, target):
            return None
        return self.proof(failure, session_id, final_line)

    def proof(self, failure, session_id, final_line):
        """The ordered read and mutation must precede the final response in one session."""
        observed = [
            call
            for call in self.calls
            if call["session_id"] == session_id
            and call["target"] == failure[INPUT][FILE_PATH]
            and failure[EVENT_LINE] < call[EVENT_LINE] < final_line
        ]
        read = next((call for call in observed if call[TOOL] == "read"), None)
        if read is None:
            return None
        later = [call for call in observed if call[EVENT_LINE] > read[EVENT_LINE]]
        write = next((call for call in later if call[TOOL] in WRITERS), None)
        if write is None:
            return None
        return dict(provenance(write), read=provenance(read))


def call_identity(event, part):
    """Repeated updates of one native call cannot prove a new read."""
    identity = part.get("id") or part.get("callID")
    return event.get("sessionID"), identity


def provenance(call):
    """Only public event identifiers are needed to locate the successful operation."""
    return {key: call[key] for key in PROVENANCE}


def unread(failure, target):
    """Match the exact native rejection and exact approved path, never prose claims."""
    message = REJECTION.format(target)
    return (
        failure.get(TOOL) in WRITERS
        and failure.get(INPUT, {}).get(FILE_PATH) == target
        and failure.get(ERROR) in {message, f"Error: {message}"}
    )
