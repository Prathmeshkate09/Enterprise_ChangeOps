PYTHON ?= python

.PHONY: setup lint test audit build dev smoke sandbox-check persistence-check agent-fleet-check tool-gateway-check workflow-check control-tower-check clean

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

tool-gateway-check:
	$(PYTHON) scripts/tasks.py tool-gateway-check

workflow-check:
	$(PYTHON) scripts/tasks.py workflow-check

control-tower-check:
	$(PYTHON) scripts/tasks.py control-tower-check

clean:
	$(PYTHON) scripts/tasks.py clean
