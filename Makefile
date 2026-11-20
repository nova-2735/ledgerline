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
	$(UV_RUN) python -m app.demo.seed

reset:
	$(UV_RUN) python -m app.demo.seed --regenerate

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
	$(UV_RUN) python -m app.eval --provider fake --gate --out "$(CURDIR)/reports/eval_fake.md"

eval-live:
	$(UV_RUN) python -m app.eval --provider gemini --force-fresh --out "$(CURDIR)/reports/eval_live.md"

IMAGE ?= ledgerline
BASE_URL ?= http://localhost:8000
ACCESS_CODE ?=

docker-build:
	docker build -t $(IMAGE) .

docker-run:
	docker run --rm -p 8000:8000 --env-file .env -e DATA_DIR=/app/data -e PORT=8000 $(IMAGE)

smoke:
	$(UV_RUN) python "$(CURDIR)/scripts/smoke.py" --base-url "$(BASE_URL)" --access-code "$(ACCESS_CODE)"
