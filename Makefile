.PHONY: test lint typecheck fmt check

test:
	uv run pytest

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

typecheck:
	uv run mypy

fmt:
	uv run ruff format src tests
	uv run ruff check --fix src tests

check: lint typecheck test

lab:
	uv run jupyter lab --notebook-dir=notebooks

db:
	uv run python -m trp.explore --build-db
