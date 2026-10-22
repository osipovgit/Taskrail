# Development

Runtime: Python 3.10+, standard library only. Tooling: the same Python and Node 24.19+.
Install pinned dependencies and run the complete gate:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
npm ci --ignore-scripts
make check PYTHON=.venv/bin/python
```

Wemake/Flake8 checks Python design and style; Ruff checks imports/basic correctness
and formatting. ESLint, Stylelint and Prettier cover the UI. Bash parses every deployment
script separately; pinned ShellCheck follows sourced libraries from their entry points.
`make` locates ShellCheck beside the selected Python runtime; `SHELLCHECK` may override
the executable when development tools are installed separately. No new findings are
allowed. The code has no Wemake findings, so `quality/wemake-baseline.json` is empty;
it is not a suppression budget. Never refresh the baseline to conceal a finding:
fix it.

Tests use fake opencode 1.x and 2.x subprocesses, temporary source trees and real
local HTTP workers. They exercise contracts, permissions, workflow and recovery,
checkpoints, budgets, telemetry, UI DOM behavior and deployment. Deployment tests use
private release copies and system paths, with unconditional privilege-command stubs;
they never invoke the host's sudo, systemd or executor reset.
GitHub Actions (`.github/workflows/ci.yml`) runs `make check` on Python 3.12, the
test suite on Python 3.10 to 3.14, and `countersign init` plus `countersign check`
against a pinned opencode 1.x without calling a model. CodeQL (only while the
repository is public; private repositories need GitHub Code Security) and Dependabot
watch the code and pinned dependencies. `tests/fixtures/` holds recorded opencode 1.19.3
and 2.0.30 event streams; when opencode changes its events, record a new stream with
paths replaced by `/fixture` and keep both. `make test` runs the Python tests with a temporary
`HOME`, so the locks of running tasks and installed settings cannot affect them.
Passing tests does not establish model quality, provider behavior, visual rendering
or runtime acceptance in the target environment.

Deterministic-contract tests cover lossless inputs, strict plan parsing, requirement
lineage, compact decisions, source packets, context admission, durable command replay
guards and criterion-bound check evidence. Subprocess workflow tests cover direct
child implementation, independent integration review and same-session plan edit
recovery. Run an individual workflow test with a private `HOME`, as `make test` does;
failure assertions should include the run summary rather than only its status.

```sh
.venv/bin/python -m ruff format countersign tests tools
npx prettier --write 'countersign/web/static/**/*' 'tests/*.cjs' eslint.config.mjs
.venv/bin/python tools/lint_python.py
```

Keep current documentation concise. Add behavior tests for a contract or transition
change; do not add release-specific narratives. Use [AGENTS.md](../AGENTS.md) for
maintainer rules and [contracts](contracts.md) for instruction ownership.
