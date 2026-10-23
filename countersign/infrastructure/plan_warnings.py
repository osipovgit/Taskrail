"""Prove that a rejected plan overwrite was completed after a native read."""

REJECTION = "You must read file {0} before overwriting it. Use the Read tool first"
RESOLUTION = "The rejected plan overwrite was followed by an actual read and successful write in the same session. The saved plan still requires validation."
WRITERS = frozenset(("write", "edit"))
TOOLS = WRITERS | {"read"}
PROVENANCE = ("event_line", "call_id", "part_id")
EVENT_LINE = "event_line"
TOOL = "tool"


class PlanWrites:
    """Record completed native operations only for the server-owned planner artifact."""

    def __init__(self, target):
        """Without an explicit planner path, no failed write may be recovered."""
        self.target = target
        self.calls = []
        self.seen = set()

    def observe(self, event_line, event):
        """Keep actual completed operations with their original session and event identity."""
        if self.target is None or event.get("type") != "tool_use":
            return
        part = event.get("part", {})
        state = part.get("state", {})
        identity = call_identity(event, part)
        if not all(identity) or identity in self.seen:
            return
        matches = state.get("input", {}).get("filePath") == self.target
        completed = state.get("status") == "completed"
        if not matches or not completed or part.get(TOOL) not in TOOLS:
            return
        self.seen.add(identity)
        self.calls.append(
            dict(
                tool=part[TOOL],
                session_id=event.get("sessionID"),
                event_line=event_line,
                call_id=part.get("callID"),
                part_id=part.get("id"),
            )
        )

    def recover(self, outcome, final_line):
        """Retain a known rejection as a warning only with a later read/write proof."""
        sessions = outcome["sessions"]
        answered = final_line is not None and outcome["final_text"].strip()
        if self.target is None or not answered or len(sessions) != 1:
            return outcome
        for failure in outcome["tool_errors"]:
            proof = self.recovery(failure, sessions[0], final_line)
            if proof is not None and failure["error"] in outcome["errors"]:
                failure.update(recovered_by=proof, resolution=RESOLUTION)
                outcome["warnings"].append(dict(failure))
                outcome["errors"].remove(failure["error"])
        return outcome

    def recovery(self, failure, session_id, final_line):
        """Only the known rejection in the completed session can use an observed proof."""
        if failure.get("session_id") != session_id or not unread(failure, self.target):
            return None
        return self.proof(failure[EVENT_LINE], session_id, final_line)

    def proof(self, failed_line, session_id, final_line):
        """The ordered read and mutation must precede the final response in one session."""
        observed = [
            call
            for call in self.calls
            if call["session_id"] == session_id and failed_line < call[EVENT_LINE] < final_line
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
        and failure.get("input", {}).get("filePath") == target
        and failure.get("error") in {message, f"Error: {message}"}
    )
