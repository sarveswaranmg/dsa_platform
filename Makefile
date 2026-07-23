COMPOSE := docker compose -f infra/docker-compose.yml
BACKEND_SERVICES := $(patsubst services/%/pyproject.toml,%,$(wildcard services/*/pyproject.toml))
VITE_API_BASE_URL ?= http://gateway:8000

.PHONY: dev infra-up test lint migrate migrate-run judge-images e2e build-frontend

dev:
	$(COMPOSE) up --build

# Full-MVP proof through the gateway. Needs `make dev` up and the judge worker
# running (cd services/judge && uv run python -m app.worker).
e2e:
	uv run scripts/e2e.py

# Build the per-language sandbox runner images the judge launches.
judge-images:
	docker build -f services/judge/runners/python/Dockerfile -t dsa-judge-python:3.12 services/judge/runners
	docker build -f services/judge/runners/java/Dockerfile -t dsa-judge-java:21 services/judge/runners
	docker build -f services/judge/runners/cpp/Dockerfile -t dsa-judge-cpp:13 services/judge/runners

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

# Applies pending migrations by running each service's one-shot migrate
# container to completion (exam, question — the only services with a
# database). Not to be confused with `migrate`, which authors a new
# migration file. `make dev` also runs these automatically before the app
# containers start (see infra/docker-compose.yml's service_completed_successfully
# dependency); this target is for running migrations standalone.
migrate-run: infra-up
	$(COMPOSE) run --rm exam-migrate
	$(COMPOSE) run --rm question-migrate

# Builds the production frontend image (npm run build, served via nginx).
# Override the gateway origin with: make build-frontend VITE_API_BASE_URL=https://api.example.com
build-frontend:
	docker build -t dsa-platform-frontend:prod --build-arg VITE_API_BASE_URL=$(VITE_API_BASE_URL) frontend
