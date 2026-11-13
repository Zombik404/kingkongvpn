.DEFAULT_GOAL := help
SHELL := /bin/bash

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

check-env: ## Report available tools and what they unblock
	@scripts/check-env.sh

env: ## Create .env from template (won't overwrite)
	@test -f .env && echo ".env exists, not touching it" || (cp .env.example .env && echo "created .env")

keys: ## Generate dev JWT keys and node CA into ./secrets
	@python3 scripts/generate-dev-secrets.py

up: ## Start dev infrastructure (postgres, redis, mailpit)
	docker compose up -d

up-app: ## Start infrastructure + application services
	docker compose --profile app up -d --build

down: ## Stop dev stack
	docker compose --profile app down

logs: ## Tail logs
	docker compose --profile app logs -f --tail=100

test: ## Run stdlib-only suites (node agent, scripts) — no services needed
	python3 -m pytest -q scripts/tests node-agent/tests

test-backend: ## Backend tests with coverage (needs `make up`: postgres + redis)
	cd backend && python -m pytest -q --cov --cov-report=term

test-all: test test-backend ## Everything

lint: ## ruff + format check + mypy --strict
	cd backend && ruff check app tests migrations && ruff format --check app tests migrations && mypy app
	cd node-agent && mypy --strict agent

backend-install: ## Install backend + dev deps from the lock files into the active venv
	cd backend && pip install --require-hashes -r requirements-dev.lock && pip install --no-deps -e .

lock: ## Re-pin backend dependencies (hash-locked, Python 3.12)
	cd backend && uv pip compile pyproject.toml --python-version 3.12 --generate-hashes -o requirements.lock --no-header
	cd backend && uv pip compile pyproject.toml --extra dev --python-version 3.12 --generate-hashes -o requirements-dev.lock --no-header

migrate: ## Apply database migrations (docker)
	docker compose --profile app run --rm migrate

seed: ## Dev-only sample plans/prices (docker)
	docker compose --profile app run --rm backend python -m app.cli seed-dev

openapi: ## Regenerate shared/api-contracts/openapi.json
	cd backend && python -m app.openapi

compose-check: ## Validate docker-compose.yml
	docker compose --env-file .env.example --profile app config --quiet && echo "compose OK"

secret-scan: ## Fail if anything that looks like a secret is tracked
	@! git ls-files -z | xargs -0 grep -nIE '(sk_live_|sk_test_[0-9a-zA-Z]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|[0-9]{8,10}:[A-Za-z0-9_-]{35})' -- 2>/dev/null \
	  | grep -v 'Makefile' || (echo "possible secret found" && exit 1)
	@echo "secret scan OK"

graph: ## Rebuild the code graph in graphify-out/ (pip install graphifyy; local, no API cost)
	@command -v graphify >/dev/null || (echo "install it: pip install graphifyy" && exit 1)
	@graphify update .

.PHONY: help check-env env keys up up-app down logs test test-backend test-all lint backend-install lock migrate seed openapi compose-check secret-scan graph
