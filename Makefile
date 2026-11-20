# Ledgerline developer commands. Recipes are POSIX sh.

PORT ?= 8000
BACKEND := backend
WEB := web
UV_RUN := cd $(BACKEND) && uv run

.DEFAULT_GOAL := help

.PHONY: help setup dev dev-api dev-web lint typecheck test web-build check \
	generate seed reset openapi types models extract eval eval-live \
	docker-build docker-run smoke

help:
	@echo "Targets: setup dev dev-api dev-web lint test check generate seed reset"
	@echo "         openapi types models extract eval eval-live docker-build docker-run smoke"

setup:
	cd $(BACKEND) && uv sync
	cd $(WEB) && npm ci

dev:
	@trap 'kill 0' INT TERM; \
	(cd $(BACKEND) && uv run uvicorn app.main:app --reload --port $(PORT)) & \
	(cd $(WEB) && npm run dev) & \
	wait

dev-api:
	$(UV_RUN) uvicorn app.main:app --reload --port $(PORT)

dev-web:
	cd $(WEB) && npm run dev

lint:
	$(UV_RUN) ruff check .
	$(UV_RUN) ruff format --check .

typecheck:
	-$(UV_RUN) mypy app
	cd $(WEB) && npm run typecheck

test:
	$(UV_RUN) pytest -q
	cd $(WEB) && npm test

web-build:
	cd $(WEB) && npm run build

check: lint typecheck test web-build

generate:
	$(UV_RUN) python -m app.demo.generate --out "$(CURDIR)/data/demo"

seed:
	@echo "make seed: available after B08"

reset:
	@echo "make reset: available after B08"

openapi:
	$(UV_RUN) python -m app.cli export-openapi

types:
	cd $(WEB) && npm run gen:types

models:
	$(UV_RUN) python -m app.cli models

extract:
	@test -n "$(FILE)" || { echo "usage: make extract FILE=path/to.pdf"; exit 2; }
	$(UV_RUN) python -m app.cli extract "$(abspath $(FILE))" $(ARGS)

eval:
	@echo "make eval: available after B12"

eval-live:
	@echo "make eval-live: available after B12"

docker-build:
	@echo "make docker-build: available after B13"

docker-run:
	@echo "make docker-run: available after B13"

smoke:
	@echo "make smoke: available after B13"
