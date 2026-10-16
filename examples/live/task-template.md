```countersign-task
{"roots":{"project":"~/src/my-project"},"verification":["Deferred runtime check: action and expected result"]}
```

# Short task title

## Goal
Describe the expected behavior and why it is needed.

## Current behavior
Describe the problem, reproduction steps, and relevant errors, if known.

## Acceptance criteria
- State an observable result that proves the change meets the goal.
- If the current source already satisfies the requirements, no edits are needed.

## Known entry points
- project/path/to/file (optional).
Discover related files and the minimum change scope within the declared roots.

## Constraints
Preserve existing user changes and compatibility. Avoid unrelated changes.
Read-only Git history is allowed. Do not change Git state, publish, or deploy.

## Verification
Run available built-in syntax checks and static review. Do not execute deferred
runtime checks from verification; list them as unverified in the report.
