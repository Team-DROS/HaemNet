.PHONY: help install lint format typecheck test check website

help:  ## List the available commands
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-12s %s\n", $$1, $$2}'

install:  ## Install backend and tooling dependencies
	pip install -r backend/requirements.txt ruff==0.16.9 mypy==1.14.1

lint:  ## Static checks (ruff)
	ruff check backend

format:  ## Format the backend
	ruff format backend

typecheck:  ## Type check the backend (mypy)
	mypy backend

test:  ## Run the backend tests
	python -m pytest backend/tests -q

website:  ## Check the public website's links
	python frontend/website/check_links.py

check: lint typecheck test website  ## Everything CI runs for the backend and website
	ruff format --check backend
