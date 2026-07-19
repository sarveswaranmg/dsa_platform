COMPOSE := docker compose -f infra/docker-compose.yml
BACKEND_SERVICES := $(patsubst services/%/pyproject.toml,%,$(wildcard services/*/pyproject.toml))

.PHONY: dev infra-up test lint migrate

dev:
	$(COMPOSE) up --build

infra-up:
	$(COMPOSE) up -d --wait postgres redis localstack

ifdef SVC
test: infra-up
	cd services/$(SVC) && uv run pytest
else
test: infra-up
	@for svc in $(BACKEND_SERVICES); do \
		echo "==> pytest services/$$svc"; \
		(cd services/$$svc && uv run pytest) || exit 1; \
	done
endif

lint:
	@for svc in $(BACKEND_SERVICES); do \
		echo "==> lint services/$$svc"; \
		(cd services/$$svc && uv run ruff check . && uv run mypy .) || exit 1; \
	done
	@if [ -f frontend/package.json ]; then \
		echo "==> lint frontend"; \
		cd frontend && npm run lint && npx tsc --noEmit; \
	else \
		echo "==> frontend not scaffolded yet, skipping"; \
	fi

migrate: infra-up
ifndef SVC
	$(error Usage: make migrate SVC=<service> MSG="<message>")
endif
ifndef MSG
	$(error Usage: make migrate SVC=<service> MSG="<message>")
endif
	cd services/$(SVC) && uv run alembic revision --autogenerate -m "$(MSG)"
