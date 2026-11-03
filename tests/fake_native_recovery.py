"""A scripted agent inspects and repairs a partial write through controlled Git."""

import json
import sys

from fake_file_writes import event


def interrupted_writer(run, root, target, record, prompt, mode, emit):
    turn = record.get("session_turns", 0)
    if turn == 0:
        target.write_text(target.read_text().replace("return 1", "return ("))
        event(emit, target, "write", "error", "Tool execution aborted")
        sys.exit(1)
    if turn == 1:
        assert "previous turn was interrupted" in prompt
        assert "Tool execution aborted" in prompt
        argv = ["diff", "--", "hello.py"]
    elif turn == 2:
        assert "return (" in prompt
        argv = ["restore", "--worktree", "--", "hello.py"]
    else:
        if mode == "native-partial-dirty":
            assert "REJECTED" in prompt and "user edits" in prompt
            assert "# earlier user work" in target.read_text()
            event(emit, target, "read", "completed", target.read_text())
            target.write_text(target.read_text().replace("return (", "return 1"))
        else:
            assert "SUCCEEDED" in prompt
            assert "return 1" in target.read_text()
        return
    payload = dict(
        schema_version=1,
        status="GIT_REQUEST",
        root=str(root),
        argv=argv,
        reason="Inspect and repair this interrupted source edit",
    )
    emit(
        json.dumps(
            dict(
                type="text", part=dict(id="request", messageID="request", text=json.dumps(payload))
            )
        )
    )
    emit(
        json.dumps(
            dict(
                type="step_finish",
                part=dict(id="stop", messageID="request", reason="stop", tokens={}),
            )
        )
    )
    sys.exit(0)
