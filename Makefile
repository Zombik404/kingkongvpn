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

test: ## Run all test suites that exist so far
	python3 -m pytest -q scripts/tests node-agent/tests

compose-check: ## Validate docker-compose.yml
	docker compose --env-file .env.example --profile app config --quiet && echo "compose OK"

secret-scan: ## Fail if anything that looks like a secret is tracked
	@! git ls-files -z | xargs -0 grep -nIE '(sk_live_|sk_test_[0-9a-zA-Z]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|[0-9]{8,10}:[A-Za-z0-9_-]{35})' -- 2>/dev/null \
	  | grep -v 'Makefile' || (echo "possible secret found" && exit 1)
	@echo "secret scan OK"

.PHONY: help check-env env keys up up-app down logs test compose-check secret-scan
