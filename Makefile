PYTHON ?= .venv/bin/python

.PHONY: check test lint fix run
check: lint test

lint:
	$(PYTHON) -m ruff check src tests
	$(PYTHON) -m ruff format --check src tests

test:
	$(PYTHON) -m pytest -q

fix:
	$(PYTHON) -m ruff check --fix src tests
	$(PYTHON) -m ruff format src tests

run:
	$(PYTHON) src/main.py
