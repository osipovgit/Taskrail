# Development

Runtime: Python 3.10+, standard library only. Tooling: the same Python and Node 24.19+.
Install pinned dependencies and run the complete gate:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
npm ci --ignore-scripts
make check PYTHON=.venv/bin/python
```

`make check` first compares every pin in `requirements-dev.txt` with the distributions
installed for the selected Python and stops with the install command when one differs.
Ruff checks imports, correctness, bugbear, pyupgrade, simplification and Ruff rules,
and formatting, with no per-file exemptions. Wemake/Flake8 checks the design and style of `countersign/` and `tools/`; tests use Ruff
only, because descriptive test names, literal fixtures and expected values conflict
with Wemake's name length, string reuse and magic number limits. ESLint, Stylelint and
Prettier cover the UI. Bash parses every deployment script separately; ShellCheck
follows sourced libraries from their entry points and shfmt (`-i 4 -ci`) checks the
formatting. Both come from the same pinned environment, and `make lint-shell` also
checks `local/*.sh` when a private overlay is present. No new findings are allowed and
there is no debt baseline: fix every finding instead of suppressing it.

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
.venv/bin/shfmt -i 4 -ci -w deploy/*.sh
npx prettier --write 'countersign/web/static/**/*' 'tests/*.cjs' eslint.config.mjs
.venv/bin/python tools/lint_python.py
```

Keep current documentation concise. Add behavior tests for a contract or transition
change; do not add release-specific narratives. Use [AGENTS.md](../AGENTS.md) for
maintainer rules and [contracts](contracts.md) for instruction ownership.
