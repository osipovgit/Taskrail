# Test suites

| Type | Purpose | When to run |
|---|---|---|
| Regression tests | Small contract checks, permission boundaries, failure recovery, subprocess workflows, UI DOM behavior and installation | Every code change: `make check PYTHON=.venv/bin/python` |
| Scenario acceptance tests | Real application stages with scripted model decisions on independent, realistic task fixtures; separate output oracles | Only on an explicit user request: `make test-acceptance PYTHON=.venv/bin/python` |
| Live provider acceptance | The same exported tasks through the configured provider CLI, configured models and normal personal approval routes | Only on an explicit user request, with operator-selected settings and disposable roots |
| Coverage measurement | Python line and branch coverage of regression and scenario suites, including Python subprocesses | Only on an explicit user request: `make test-coverage PYTHON=.venv/bin/python` |

Maintain the scenario fixtures and oracles whenever the corresponding functionality
changes, even when the suite is not requested for that change. A security or state
transition regression belongs in the normal suite as well. Do not make the optional
targets dependencies of `check` or CI, and do not present a scripted model decision
as evidence of real model quality. Lint and formatting still inspect all test code.

## Required checks

The local entry point is `make check`. CI uses its component targets so the Python
3.12 suite runs once, alongside the other supported Python versions.

| Group | Local command | GitHub job |
|---|---|---|
| Python lint and design | `make lint-python` | Quality / Lint and formatting |
| JavaScript and CSS lint | `make lint-ui` | Quality / Lint and formatting |
| Shell syntax, lint and formatting | `make lint-shell` | Quality / Lint and formatting |
| Python and UI formatting | `make format-check` | Quality / Lint and formatting |
| Python regressions | `make test-python` | Tests / Python 3.10–3.14 |
| UI regressions | `make test-ui` | Tests / UI |
| CLI permission compatibility | `taskrail init`, then `taskrail check` in disposable settings | Compatibility / opencode 1.19.3 |
| Static security analysis | GitHub CodeQL | Security / Python and JavaScript |

`make test` combines Python and UI regressions. Use the pinned Python environment,
for example `make test-python PYTHON=.venv/bin/python`.
`CI gate` requires every CI group to succeed, including every Python matrix entry.
`Security gate` requires both CodeQL languages on public repositories; the private
repository path explicitly reports that analysis is unavailable. A failed,
cancelled or unexpectedly skipped dependency cannot pass either gate.
Repository rules must require both statuses; YAML alone does not prevent a merge.

The ordinary regression suite includes real disposable Git repositories and linked
worktrees for automatic commit ownership, content receipts, filter suppression,
partial failure and interrupted writes. Split workflows use scripted 1.x and 2.x
CLI transports to check inherited permissions, configured checks, child commits,
restart/Continue and combined integration review. Evidence tests distinguish
attempts and session IDs and reject unsent or omitted source deliveries. These
tests require no model provider, production project or remote execution service.

## Scenario corpus

`tests/fixtures/acceptance/corpus.json` owns the task text, initial projects, expected
edits and independent live acceptance criteria. Each task gets separate roots with
spaces in their paths. `tests/acceptance/scenario_*.py` is discovered only by the
explicit target; support files do not use the regression suite's `test_` prefix.

| Task | Main acceptance criterion |
|---|---|
| `ANSIBLE-LINT` | Qualified modules and unchanged paths, variables and file modes; server idempotence remains unverified locally |
| `IMAGE-CACHE` | Both scripts build only the API without cache, reuse the image and stop after a failed build |
| `PERCENT-DISCOUNT` | Independent numeric expectations catch the seeded percentage error |
| `MULTI-ROOT-TIMEOUT` | Ordered child tasks keep global constraints, update both units consistently and receive combined independent review |
| `ANSWER-ONLY` | Reviewed answer with source references and unchanged roots |
| `DESIGN-ONLY` | Reviewed design artifact with unchanged source roots |
| `LITERAL-USER-TEXT` | CRLF, spaces, quotes, shell syntax and embedded headings survive typed input and frozen task data |
| `DOCS-ONLY` | A requested documentation deliverable completes the normal review workflow |
| `TESTS-ONLY` | Requested boundary tests pass without changing implementation |

The suite also checks syntax failures versus unchecked formats, protected map
entries, root limits, and a writer that damages unrelated user notes. Docker is a
recording stub; the suite never contacts a Docker daemon, model provider, SSH target
or Jenkins. Static YAML validation does not establish Ansible runtime correctness.

Export independent task directories without running them:

```sh
.venv/bin/python tests/acceptance/export.py /tmp/taskrail-acceptance-tasks
```

The destination must not exist. Each directory contains `task.md`, its own initial
projects and `oracle.json`. For a requested live run, choose a disposable directory,
use the actual configured provider CLI and the operator's explicit settings, submit
one task, then compare its artifacts with the oracle. Review command approvals in
the usual UI and keep all server checks deferred until change confirmation and
root approval. Never silently replace the configured provider CLI or interpret
fixture expectations as permission to access a real server.

## Coverage

The pinned `coverage` tool measures branches and Python subprocesses; reports and
separate suite logs are in `tmp/coverage/`, including `html/index.html` and
`coverage.json`. Measurements use a new data directory and private HOME each time;
temporary installed copies map back to the source package. Inspect missing branches
in changed code and add behavioral tests for meaningful gaps. A percentage alone
does not establish approval correctness or task quality. Killed processes may not
flush coverage. Python subprocesses that deliberately discard the coverage environment
or use a separate interpreter without the coverage bootstrap are not traced; the
runner selects the pinned Python for deployment fixtures where supported. JavaScript
DOM tests and shell behavior have separate regression checks and are not counted in
Python coverage.
