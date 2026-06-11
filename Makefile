.PHONY: install lint typecheck test test-integration up down migrate backup restore-drill

install:
	uv sync --all-packages
	uv run pre-commit install

lint:
	uv run ruff check libs services tests
	uv run ruff format --check libs services tests

format:
	uv run ruff check --fix libs services tests
	uv run ruff format libs services tests

typecheck:
	uv run mypy libs services

test:
	uv run pytest

test-integration:
	uv run pytest -m integration

up:
	docker compose up -d --build

up-monitoring:
	docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d --build

down:
	docker compose down

migrate:
	uv run alembic upgrade head

backup:
	./infrastructure/backup/backup.sh

restore-drill:
	./infrastructure/backup/restore_drill.sh
