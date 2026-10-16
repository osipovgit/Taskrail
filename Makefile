PYTHON ?= python3

.PHONY: lint lint-python lint-ui test format-check check
lint: lint-python lint-ui
	bash -n deploy/fresh.sh deploy/reset-executor.sh deploy/install.sh deploy/options.sh deploy/countersign deploy/install-executor.sh deploy/executor-service deploy/countersign-executor-approve deploy/ssh-askpass
lint-python:
	$(PYTHON) -m ruff check countersign tests tools
	$(PYTHON) tools/lint_python.py
lint-ui:
	npm run lint
format-check:
	$(PYTHON) -m ruff format --check countersign tests tools
	npm run format:check
test:
	$(PYTHON) -m unittest discover -s tests
	npm test
check: lint format-check test
