.PHONY: up check-env down install test test-all lint invariants migrate gate api frontend frontend-check

up: check-env
	docker compose up -d

check-env:
	@test -f .env || (echo "Missing .env: cp .env.example .env and fill it in" && exit 1)
	@for v in POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB MINIO_ROOT_USER MINIO_ROOT_PASSWORD; do \
	  grep -Eq "^$$v=.+" .env || { echo "Set $$v in .env"; exit 1; }; \
	done

down:
	docker compose down

install:
	uv sync --all-groups

test:
	uv run pytest -q

test-all:
	uv run pytest -q -m ""

lint:
	uv run ruff check src tests scripts
	uv run ruff format --check src tests scripts
	uv run mypy
	uv run python scripts/check_invariants.py

invariants:
	python3 scripts/check_invariants.py

migrate:
	uv run alembic upgrade head

gate:
	@test -n "$(PHASE)" || (echo "usage: make gate PHASE=N" && exit 1)
	uv run python scripts/gate.py $(PHASE)

api:
	uv run uvicorn stockiq.api.app:app --host 127.0.0.1 --port 8000

frontend:
	cd frontend && npm install && npm run dev

frontend-check:
	cd frontend && npm run typecheck && npm test && npm run build
