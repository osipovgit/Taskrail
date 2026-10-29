PYTHON ?= python3
# Pinned shell tools come from requirements-dev.txt and sit beside the selected Python.
TOOL_DIR := $(shell $(PYTHON) -c 'import sysconfig; print(sysconfig.get_path("scripts"))')
SHELLCHECK = $(TOOL_DIR)/shellcheck
SHFMT = $(TOOL_DIR)/shfmt
SHELL_SCRIPTS = deploy/fresh.sh deploy/executor-maintenance.sh deploy/install-locks.sh deploy/reset-executor.sh deploy/install.sh deploy/options.sh deploy/taskrail deploy/install-executor.sh deploy/executor-service deploy/taskrail-executor-approve deploy/ssh-askpass
SHELL_ENTRYPOINTS = deploy/install.sh deploy/install-executor.sh deploy/reset-executor.sh deploy/taskrail deploy/executor-service deploy/taskrail-executor-approve deploy/ssh-askpass

.PHONY: lint lint-python lint-ui lint-shell test test-python test-ui test-acceptance test-coverage format-check check tool-versions
lint: lint-python lint-ui lint-shell
tool-versions:
	$(PYTHON) tools/check_tools.py
lint-shell: tool-versions
	@for script in $(SHELL_SCRIPTS); do bash -n "$$script" || exit; done
	$(SHELLCHECK) -x -P . $(SHELL_ENTRYPOINTS)
	$(SHFMT) -i 4 -ci -d $(SHELL_SCRIPTS)
lint-python: tool-versions
	$(PYTHON) -m ruff check taskrail tests tools
	$(PYTHON) tools/lint_python.py
lint-ui:
	npm run lint
format-check: tool-versions
	$(PYTHON) -m ruff format --check taskrail tests tools
	npm run format:check
test: test-python test-ui
test-python: tool-versions
	@# A private HOME keeps the real workflow lock and installed settings out of the tests.
	taskrail_test_home=$$(mktemp -d) && HOME=$$taskrail_test_home $(PYTHON) -m unittest discover -s tests; \
		status=$$?; rm -rf "$$taskrail_test_home"; exit $$status
test-ui:
	npm test
# Explicit operator request only; neither target is a dependency of check or CI.
test-acceptance: tool-versions
	taskrail_test_home=$$(mktemp -d) && HOME=$$taskrail_test_home PYTHONPATH=.:tests $(PYTHON) -m unittest discover -s tests/acceptance -p 'scenario_*.py' -v; \
		status=$$?; rm -rf "$$taskrail_test_home"; exit $$status
test-coverage: tool-versions
	$(PYTHON) tools/test_coverage.py
check: tool-versions lint format-check test
