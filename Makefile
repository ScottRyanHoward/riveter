.PHONY: help install install-dev test test-fast lint format format-check \
        type-check security pre-commit clean clean-all build

# Default target
help:
	@echo "Riveter — development commands"
	@echo ""
	@echo "Setup"
	@echo "  install        Install the package (runtime only)"
	@echo "  install-dev    Install the package with dev dependencies"
	@echo ""
	@echo "Quality"
	@echo "  format         Auto-format with black + isort"
	@echo "  format-check   Check formatting without making changes"
	@echo "  lint           Run ruff linter"
	@echo "  type-check     Run mypy type checker"
	@echo "  security       Run bandit security scanner"
	@echo "  pre-commit     Run all pre-commit hooks"
	@echo ""
	@echo "Testing"
	@echo "  test           Run full test suite with coverage"
	@echo "  test-fast      Run tests without coverage reporting"
	@echo ""
	@echo "Build"
	@echo "  build          Build standalone binary with PyInstaller"
	@echo ""
	@echo "Cleanup"
	@echo "  clean          Remove build artifacts"
	@echo "  clean-all      Deep clean including caches"

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"
	pre-commit install

# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------

format:
	black src/ tests/
	isort src/ tests/

format-check:
	black --check src/ tests/
	isort --check-only src/ tests/

lint:
	ruff check src/ tests/

type-check:
	mypy src/riveter/

security:
	bandit -r src/riveter/ -ll

pre-commit:
	pre-commit run --all-files

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

test:
	pytest

test-fast:
	pytest --no-cov -q

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

build:
	python build_binary.py

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

clean:
	rm -rf dist/ build/ *.spec
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true

clean-all: clean
	rm -rf .mypy_cache .ruff_cache htmlcov .coverage coverage.xml
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
