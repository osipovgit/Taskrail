# Deterministic verification

The application executes selected checks, waits for completion and parses their
declared output format. The model chooses relevant recipes and interprets recorded
facts; it does not construct commands, poll jobs or count errors in logs.
Independent review remains mandatory.

## Configure exact recipes

Only the operator's settings define `check_recipes`. Each recipe fixes `kind`,
`phase`, `request`, `adapter` and an optional short `description`. For example:

```json
{
  "check_recipes": {
    "unit-tests": {
      "kind": "local",
      "phase": "check",
      "description": "Run the project's Python unit tests",
      "request": {
        "cwd": "/home/me/src/shop",
        "argv": ["python3", "-m", "unittest", "discover", "-s", "tests"],
        "timeout_seconds": 600
      },
      "adapter": "exit-code"
    },
    "jenkins-tests": {
      "kind": "jenkins",
      "phase": "validation",
      "description": "Build the configured Jenkins job and inspect its tests",
      "request": {
        "server": "ci",
        "job": "shop-tests",
        "operation": "build",
        "build": "new",
        "parameters": {},
        "reason": "Validate the finished change",
        "timeout_seconds": 600
      },
      "adapter": "jenkins"
    }
  }
}
```

Local recipes use `phase: check`, a declared root as `cwd`, an explicit argv and
the existing local command policy. In an isolated run, the application maps the
root to its worktree. Source or Git changes during verification stop the run.
Local recipes and `verify_commands` run without a decision in the
[local command sandbox](access.md#local-commands), with writable roots; on a host
without one they require personal approval of the exact command, or the operator's
Allow all actions. `verify_commands` remain mandatory gates and
appear in the recipe catalog
as `verify-<digest>`; this ID prefix is reserved.

Jenkins recipes start one build through the isolated executor and its root
approval. The executor follows that build's queue and number, then retrieves its
console tail and test report in the same execution. Missing reports remain
unknown. The job and its fixed parameters determine which revision Jenkins tests;
the local source snapshot records when the observation was made and does not
prove Jenkins checked out that revision. SSH recipes use `kind: ssh`,
`phase: server`, `adapter: exit-code` and the
exact [SSH action fields](ssh-executor.md). They run only after the parent change
has been confirmed, still through the root approval route. Recipe selection
never grants remote authority.

## Select and bind checks

The planner receives only recipe IDs, descriptions, kinds, phases and adapters.
In `plan.md`, it may select recipes for runtime requirements:

```markdown
## Check selections
- unit-tests: R3, R4
- jenkins-tests: R5
```

After independent plan approval, the application maps the short requirement
labels to stable IDs and creates closed `CheckSpec` records:

```json
{
  "id": "check-content-digest",
  "recipe_id": "unit-tests",
  "criteria": ["R-stable-runtime-id"],
  "phase": "check",
  "parameters": {}
}
```

A local runtime criterion may use `R3 → T1` in `## Requirements` when a selected
local recipe checks it. Planning and plan review accept that intent only with
both the recipe and the owning task; the atomic child inherits and executes the
check. This does not count as runtime success. Implementation and final review
cannot retain `planned`; claims of runtime success still need executed results.
Remote criteria remain explicit `runtime:` deferrals for their delivery phase.

Typed task headers may supply the same `check_specs` structure. Every criterion
must be a runtime requirement of that task. The recipe owns the phase; parameter,
command and adapter overrides are rejected. Selecting the same recipe/criterion
binding twice does not duplicate execution. Selecting an existing mandatory
verification command binds that execution to criteria rather than rerunning it.
Written `Jenkins check:` and `Server check:` plan entries become the deferred
verification of their delivery phase; they are never guessed into executable commands.

Local checks run after syntax checks, including an approved no-change plan that
selects them. Child tasks inherit only their assigned local checks. Integration
review repeats the parent's local checks on the combined result. Fixed validation
and server batches execute in code before review. A failed or unknown fixed
batch stops; when all runtime criteria are covered by passed checks, the next
model stage is the independent reviewer. Runtime requirements without a selected
recipe keep the ordinary planning path.

## Results and continuation

`00-input/settings.json` freezes the catalog and mandatory commands; the run index
records their digest. Continue verifies and restores that snapshot. A linked
child or delivery phase authenticates its parent, roots and exact criterion
bindings before inheriting the frozen catalog. A removed or rephased recipe in
current settings can reject a new phase during initial validation; it never
silently substitutes a different command. An interrupted run restores its own
frozen configuration before parsing check references, independently of live
recipe changes. An adopted delivery phase also records its exact parent, phase,
roots, criteria and catalog digest, so continuation can verify those inputs
without reopening the parent. SSH server actions still recheck the parent's
live confirmation and linked server phase before execution.

Each execution writes an immutable JSON artifact under `00-input/checks/` and a
durable entry in `check-results.json`. A `CheckResult` records its `check_id`,
`criteria`, exact `request_sha256`, source/Git `source_snapshot`, structured
`assessment` and execution identity. Local stdout/stderr are separate artifacts
with byte counts and hashes. Remote results link the executor ticket and its
existing full snapshot. The model receives bounded diagnostics and artifact
references rather than repeated raw logs.

Supported adapters are `exit-code`, `ruff-json`, `eslint-json`, `stylelint-json`,
`shellcheck-json`, `junit` and `jenkins`. Local structured reports must be emitted
on stdout in the selected format. Reports are limited to 2 MiB and 100 displayed
diagnostics, with an explicit omission count. JUnit and Jenkins require executed
test cases; an empty report or a report containing only skipped tests remains
unknown. Malformed output, missing exit codes, denied execution and incomplete
remote operations never become passed checks. Words such as “error” in arbitrary
logs do not determine results.

A runtime criterion is satisfied only by a current passed result bound to that
criterion. A current failed result can support a contradiction. Unrelated,
superseded, altered or stale results cannot support either claim; generic command
success alone is insufficient. Reviewers must read and cite the result artifact.

The local action journal records approval and RUNNING before execution. An
interrupted unresolved command is not automatically replayed. Remote checks
retain their exact ticket across continuation; UNKNOWN and failed tickets are
never replaced automatically. A completed remote check is reused only while its
request and source identity still match. Inspect unresolved effects before
starting a new run.
