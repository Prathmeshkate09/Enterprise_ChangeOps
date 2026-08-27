PYTHON ?= python

.PHONY: setup lint test audit build dev smoke sandbox-check persistence-check agent-fleet-check clean

setup:
	$(PYTHON) scripts/tasks.py setup

lint:
	$(PYTHON) scripts/tasks.py lint

test:
	$(PYTHON) scripts/tasks.py test

audit:
	$(PYTHON) scripts/tasks.py audit

build:
	$(PYTHON) scripts/tasks.py build

dev:
	$(PYTHON) scripts/tasks.py dev

smoke:
	$(PYTHON) scripts/tasks.py smoke

sandbox-check:
	$(PYTHON) scripts/tasks.py sandbox-check

persistence-check:
	$(PYTHON) scripts/tasks.py persistence-check

agent-fleet-check:
	$(PYTHON) scripts/tasks.py agent-fleet-check

clean:
	$(PYTHON) scripts/tasks.py clean
