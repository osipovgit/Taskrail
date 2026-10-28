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
