.PHONY: help install run test coverage sloc check format mock-data mock-prod-data clean pull pull-full push push-dry db-status build version-check release release-prep

help:
	@echo "YNAB TUI"
	@echo ""
	@echo "Make targets:"
	@echo "  make install    - Install dependencies"
	@echo "  make run        - Launch TUI application"
	@echo "  make test       - Run tests"
	@echo "  make coverage   - Run tests with coverage report"
	@echo "  make sloc       - Count lines of code (requires scc)"
	@echo "  make check      - Run all checks (format, lint, typecheck)"
	@echo "  make format     - Format code only"
	@echo "  make mock-data  - Generate synthetic mock CSV data (deterministic)"
	@echo "  make mock-prod-data - Export production DB to mock CSV files"
	@echo "  make clean      - Remove cache files"
	@echo ""
	@echo "Sync commands (git-style):"
	@echo "  make pull       - Pull YNAB + Amazon data to local DB (incremental)"
	@echo "  make pull-full  - Full pull of all data"
	@echo "  make push       - Push local categorizations to YNAB"
	@echo "  make push-dry   - Preview what would be pushed"
	@echo "  make db-status  - Show database sync status"
	@echo ""
	@echo "CLI examples:"
	@echo "  uv run python -m src.main                     # Launch TUI"
	@echo "  uv run python -m src.main amazon-match        # Match Amazon transactions"
	@echo "  uv run python -m src.main uncategorized       # List uncategorized transactions"
	@echo "  uv run python -m src.main --help              # Show all commands"
	@echo ""
	@echo "Mock mode (no live APIs):"
	@echo "  uv run python -m src.main --mock              # Launch TUI with mock data"
	@echo "  uv run python -m src.main --mock db-clear     # Only clears mock DB"
	@echo ""
	@echo "Release commands:"
	@echo "  make build         - Build package (sdist + wheel)"
	@echo "  make version-check - Verify version consistency"
	@echo "  make release       - Full release: check, test, build"
	@echo ""
	@echo "Release script (preferred):"
	@echo "  ./scripts/release.py 0.2.0           # Prepare release 0.2.0"
	@echo "  ./scripts/release.py 0.2.0 --dry-run # Preview changes"
	@echo "  See RELEASING.md for full documentation"

install:
	uv sync --all-extras

run:
	uv run python -m src.main

test:
	uv run pytest tests/ -n auto -q

coverage:
	uv run pytest tests/ --cov=src --cov-report=html --cov-report=term-missing

sloc:
	scc -a -x csv,toml  src/ tests/

sloc-src:
	scc -a -x csv,toml  src/


check:
	uv run ruff format src/ tests/
	uv run ruff check --fix src/ tests/
	uv run mypy src/

format:
	uv run ruff format src/ tests/
	uv run ruff check --fix src/ tests/

mock-data:
	@echo "Generating synthetic mock data..."
	uv run python src/mock_data/generate_mock_data.py

mock-prod-data:
	@echo "Exporting production database to mock CSV files..."
	@echo "Note: Run 'make pull' first to sync data from live APIs."
	uv run python -m src.main db-transactions --year 2025 --csv src/mock_data/transactions.csv
	uv run python -m src.main ynab-categories --csv src/mock_data/categories.csv
	uv run python -m src.main db-amazon-orders --year 2025 --csv src/mock_data/orders.csv
	@echo "Production data exported to src/mock_data/"

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

# Sync commands (git-style)
pull:
	uv run python -m src.main pull

pull-full:
	uv run python -m src.main pull --full

push:
	uv run python -m src.main push

push-dry:
	uv run python -m src.main push --dry-run

db-status:
	uv run python -m src.main db-status

# Release commands
build:
	uv build

version-check:
	@echo "Checking version consistency..."
	@PYPROJECT_VERSION=$$(grep '^version = ' pyproject.toml | cut -d'"' -f2) && \
	INIT_VERSION=$$(grep '__version__' src/__init__.py | cut -d'"' -f2) && \
	if [ "$$PYPROJECT_VERSION" != "$$INIT_VERSION" ]; then \
		echo "ERROR: Version mismatch!"; \
		echo "  pyproject.toml: $$PYPROJECT_VERSION"; \
		echo "  src/__init__.py: $$INIT_VERSION"; \
		exit 1; \
	else \
		echo "Version $$PYPROJECT_VERSION OK"; \
	fi

release: version-check check test build
	@echo ""
	@VERSION=$$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml); \
	echo "Build complete! Next steps:"; \
	echo "  1. Create git tag: git tag v$$VERSION"; \
	echo "  2. Push tag: git push origin --tags"; \
	echo "  3. Go to GitHub Actions and trigger 'Publish to PyPI' workflow"; \
	echo ""; \
	echo "Built artifacts in dist/:"
	@ls -la dist/
