PYTHON ?= python3
# Pinned shell tools come from requirements-dev.txt and sit beside the selected Python.
TOOL_DIR := $(shell $(PYTHON) -c 'import sysconfig; print(sysconfig.get_path("scripts"))')
SHELLCHECK = $(TOOL_DIR)/shellcheck
SHFMT = $(TOOL_DIR)/shfmt
SHELL_SCRIPTS = deploy/fresh.sh deploy/executor-maintenance.sh deploy/reset-executor.sh deploy/install.sh deploy/options.sh deploy/countersign deploy/install-executor.sh deploy/executor-service deploy/countersign-executor-approve deploy/ssh-askpass
SHELL_ENTRYPOINTS = deploy/install.sh deploy/install-executor.sh deploy/reset-executor.sh deploy/countersign deploy/executor-service deploy/countersign-executor-approve deploy/ssh-askpass

.PHONY: lint lint-python lint-ui lint-shell test format-check check tool-versions
lint: lint-python lint-ui lint-shell
tool-versions:
	$(PYTHON) tools/check_tools.py
lint-shell: tool-versions
	@for script in $(SHELL_SCRIPTS); do bash -n "$$script" || exit; done
	$(SHELLCHECK) -x -P . $(SHELL_ENTRYPOINTS)
	$(SHFMT) -i 4 -ci -d $(SHELL_SCRIPTS)
lint-python: tool-versions
	$(PYTHON) -m ruff check countersign tests tools
	$(PYTHON) tools/lint_python.py
lint-ui:
	npm run lint
format-check: tool-versions
	$(PYTHON) -m ruff format --check countersign tests tools
	npm run format:check
test:
	@# A private HOME keeps the real workflow lock and installed settings out of the tests.
	home=$$(mktemp -d) && HOME=$$home $(PYTHON) -m unittest discover -s tests; \
		status=$$?; rm -rf "$$home"; exit $$status
	npm test
check: tool-versions lint format-check test
