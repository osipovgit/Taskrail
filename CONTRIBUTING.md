# Contributing

Thank you for helping improve Taskrail. Maintainer rules live in
[AGENTS.md](AGENTS.md); this page covers the practical steps.

## Issues

Describe the goal, the observed behavior and the expected behavior. For a failed
run, attach the files listed under "For a failure" in the [README](README.md) and
redact secrets and private source. Report security problems privately as described
in [SECURITY.md](SECURITY.md).

## Development setup

You need Linux, Python 3.10+ and Node 24.19+.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
npm ci --ignore-scripts
make check PYTHON=.venv/bin/python
```

See [development](docs/development.md) for formatting commands and what the tests
cover.

## Pull requests

- Create a feature branch for every task, including documentation and dependency
  updates. After validation, commit and push the changes, open a pull request
  targeting `master`, and provide its URL. Local changes or a pushed branch alone
  do not complete a task; report missing PR access as a blocker.
  Never commit or push directly to `master`.
- Merge only when all required pipelines pass for the latest revision and the
  repository owner has personally reviewed and accepted the change. Agents must
  not merge, enable auto-merge or bypass repository rules.
- Keep each pull request focused on one change and explain why it is needed.
- `make check` must pass with zero new Ruff, Wemake, ESLint, Stylelint or formatting
  findings. Do not disable rules or add suppressions to hide findings.
- Add behavior tests for contract, transition, permission or UI changes, and update
  the current documentation in the same pull request.
- Project-owned code, comments, prompts, UI text and documentation are English.

By contributing you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE).
