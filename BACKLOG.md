# Backlog

Ideas that are agreed in principle but not scheduled. Each entry says why it is not
done yet.

## Replan an oversized unfinished task

A task that no longer fits one implementation session may ask the planner to replace
its unfinished work with a reviewed continuation graph. This is deferred until the
completed-step and recovery behavior has been exercised on real projects; recursion
depth and practical split thresholds are deliberately not fixed yet.

- Inputs: original Goal and Constraints, the reviewed task and its Not ToDo owners,
  accepted commits, executed check records, current diff, unfinished criteria and
  newly discovered dependencies. Historical text provides context, never authority.
- Keep accepted commits and complete outcomes. Never replay uncertain writes, roll
  back unrelated changes or silently transfer another task's deliverable.
- Give each new task explicit requirement lineage, dependencies, required local
  checks and excluded outcomes. Independent plan review must accept the new graph
  before any replacement writer starts; integration reviews the combined result.
- Persist replacement links before launching and show the new subgraph as a
  continuation of the original node, including attempts and accepted commits.
- Trigger from remaining outcomes, context pressure, new dependencies and lack of
  progress together. Changed-line count alone is not a task boundary. Reject cycles,
  duplicate ownership and unbounded no-progress expansion.

## Read-only server inspection without approval

Collecting data from servers without changing their state is safe for the services,
so it could run without a root approval, like Jenkins builds of jobs configured with
`"approval": "none"`. It is not done because reading can still leak secrets into the
model context and the provider (`sudo cat` of credential files, container environment
variables, configuration with tokens).

A safe version needs the executor itself, not the application, to enforce it:

- only one command from the existing read-only list, with literal arguments;
- a root-configured deny list of secret paths and commands (for example `/etc/shadow`,
  `*.env`, `docker inspect` of environment variables), refused before a ticket exists;
- optional redaction of secret-shaped values in returned output;
- a per-host opt-in in `hosts.json`, so root decides which servers allow it.

Until then every SSH action, including inspection, waits for root approval.
