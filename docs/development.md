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
and formatting. ESLint, Stylelint and Prettier cover the UI. No new findings are
allowed. `quality/wemake-baseline.json` records remaining existing debt by source
fingerprint; it is not a suppression budget for new code. Fix nearby simple debt,
remove resolved entries, and never refresh the baseline to conceal regressions. A
reviewed relocation keeps the rule and never increases its count or complexity.

Tests use fake opencode 1.x and 2.x subprocesses, temporary source trees and real
local HTTP workers. They exercise contracts, permissions, workflow and recovery,
checkpoints, budgets, telemetry, UI DOM behavior and deployment; systemd uses stubs.
GitHub Actions (`.github/workflows/ci.yml`) runs `make check` on Python 3.12, the
test suite on Python 3.10 to 3.14, and `countersign init` plus `countersign check`
against a pinned opencode 1.x without calling a model. CodeQL and Dependabot watch
the code and pinned dependencies. `tests/fixtures/` holds recorded opencode 1.19.3
and 2.0.30 event streams; when opencode changes its events, record a new stream with
paths replaced by `/fixture` and keep both. `make test` runs the Python tests with a temporary
`HOME`, so a running task's global lock and installed settings cannot affect them.
Passing tests does not establish model quality, provider behavior, visual rendering
or runtime acceptance in the target environment.

```sh
.venv/bin/python -m ruff format countersign tests tools
npx prettier --write 'countersign/web/static/**/*' 'tests/*.cjs' eslint.config.mjs
.venv/bin/python tools/lint_python.py
```

Keep current documentation concise. Add behavior tests for a contract or transition
change; do not add release-specific narratives. Use [AGENTS.md](../AGENTS.md) for
maintainer rules and [contracts](contracts.md) for instruction ownership.
