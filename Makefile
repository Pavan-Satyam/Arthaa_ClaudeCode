# Arch-safe wrappers. This machine runs an x86_64 (Rosetta) shell because Homebrew
# lives under /usr/local, so we pin every Python invocation to x86_64 to match the
# venv's wheels. On a native arm64 setup, set PYARCH= (empty) or ARCH=arm64.
ARCH ?= x86_64
PYARCH := arch -$(ARCH)
PY := $(PYARCH) .venv/bin/python
PIP := $(PYARCH) .venv/bin/pip

.PHONY: help setup up down health seed analyze serve test fmt

help:  ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-9s\033[0m %s\n",$$1,$$2}'

setup:  ## Create the x86_64 venv and install (matches this Rosetta shell)
	$(PYARCH) /usr/local/bin/python3 -m venv .venv
	$(PIP) install -U pip && $(PIP) install -e ".[dev]"

up:     ## Start TimescaleDB + Qdrant + Redpanda
	docker compose up -d
down:   ## Stop the stack
	docker compose down
health: ## Datastore healthcheck
	$(PY) -m arthaai.cli health
seed:   ## Seed illustrative news into Qdrant
	$(PY) -m arthaai.cli seed-news
analyze: ## Analyze a symbol:  make analyze SYM=GLD
	$(PY) -m arthaai.cli analyze $(SYM)
llm-status: ## Show which LLM providers are reachable
	$(PY) -m arthaai.cli llm-status
backtest: ## Backtest a symbol:  make backtest SYM=GLD
	$(PY) -m arthaai.cli backtest $(SYM)
serve:  ## Run the Tier 1 FastAPI gateway on :8000
	$(PYARCH) .venv/bin/uvicorn arthaai.gateway.app:app --reload --port 8000
test:   ## Run the test suite
	$(PYARCH) .venv/bin/pytest -q
fmt:    ## Format + lint
	$(PYARCH) .venv/bin/ruff format . && $(PYARCH) .venv/bin/ruff check --fix .
