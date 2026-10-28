# Backlog

Planned work that is agreed but not started. Remove an entry when it ships.

## Re-split a task that outgrew its plan

When a task of a split turns out larger than planned, the planner splits it again
from what is known now, and the new tasks continue the delivery graph from that task.

- **Trigger:** the task reaches the change limit or exceeds its planned size by a
  configured factor (changed lines, files beyond the plan), or its implementer has to
  end with work listed under Remaining in `progress.md`.
- **Planner input:** the task's sealed contract, its commits on the task branch,
  `progress.md`, review findings, new evidence and the later tasks of the split.
- **Result:** new child tasks attached to the outgrown task; its committed part stays.
  The delivery graph and the UI show them as a continuation of that node, and the
  integration review covers them.
- **Open:** the depth limit (decide from practice), how it interacts with the change
  limit, and whether the operator confirms a re-split.
- **Builds on:** task branches with one commit per approved task, the Not to do list of
  later tasks, and fresh sessions that continue from the last commit and `progress.md`.

## Reliable result format

Format repair rounds still fail too often; most rejections are contract errors
(citations, line ranges, missing inputs), not broken JSON.

- **Measure first:** count rejections per validator rule across runs, so the most
  frequent causes are fixed first.
- **Deterministic intake:** take the one JSON object out of fences or prose, accept
  trailing commas and normalize values, without inventing facts.
- **Degrade instead of reject:** a claim without proof becomes a gap with its reason
  and the result is accepted; reject only a result that cannot be used.
- **Validate inside the turn:** opencode 1.2 and later offer a `StructuredOutput` tool
  for a JSON schema, but only through the server API (`format` of a prompt), not
  `run`. With a server per stage, the final turn could be sent through the API.
  Unverified: whether the internal models accept the forced tool call.
- **Keep** the existing same-session correction and fresh-session rebuild as the last
  resort.

## Local commands inside the turn

With commands sandboxed, an agent could run them as tool calls instead of ending its
turn with `LOCAL_REQUEST`: opencode's own shell tool, started through bubblewrap.

- **Gain:** no turn break per command, no request format to get wrong.
- **Needs:** the command journal, output snapshots used as evidence and the
  inspect-only rule of reading stages rebuilt on tool events; the project rule
  "Native shell tools stay disabled" changed.
- **Open:** how opencode builds choose their shell, and commands that need the host.

## Sandbox on restricted hosts

Where bubblewrap cannot start (for example user namespaces limited by AppArmor),
every local command still waits for approval. `taskrail check` now names bubblewrap's
error for each kind of sandbox; decide from it whether another isolation (such as
Landlock with a seccomp filter) is worth adding.
