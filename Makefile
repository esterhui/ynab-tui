.PHONY: help install run test coverage sloc check format mock-data mock-prod-data clean pull pull-full push push-dry db-status build version-check

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
	@echo "  make mock-data  - Generate mock data (CSV + DB + pending splits)"
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
	@echo "  uv run python -m ynab_tui.main                     # Launch TUI"
	@echo "  uv run python -m ynab_tui.main amazon-match        # Match Amazon transactions"
	@echo "  uv run python -m ynab_tui.main uncategorized       # List uncategorized transactions"
	@echo "  uv run python -m ynab_tui.main --help              # Show all commands"
	@echo ""
	@echo "Mock mode (no live APIs):"
	@echo "  uv run python -m ynab_tui.main --mock              # Launch TUI with mock data"
	@echo "  uv run python -m ynab_tui.main --mock db-clear     # Only clears mock DB"
	@echo ""
	@echo "Release (use the release script):"
	@echo "  ./scripts/release.py 0.2.0           # Full release"
	@echo "  ./scripts/release.py 0.2.0 --dry-run # Preview first"
	@echo "  make build                           # Just build (no release)"
	@echo "  See RELEASING.md for details"

install:
	uv sync --all-extras

run:
	uv run python -m ynab_tui.main

test:
	uv run pytest tests/ -n auto -q

coverage:
	uv run pytest tests/ --cov=ynab_tui --cov-report=html --cov-report=term-missing

sloc:
	scc -a -x csv,toml  ynab_tui/ tests/

sloc-src:
	scc -a -x csv,toml  ynab_tui/


check:
	uv run ruff format ynab_tui/ tests/
	uv run ruff check --fix ynab_tui/ tests/
	uv run mypy ynab_tui/

format:
	uv run ruff format ynab_tui/ tests/
	uv run ruff check --fix ynab_tui/ tests/

mock-data:
	@echo "Generating synthetic mock data..."
	@echo "Step 1: Generate CSV files..."
	uv run python -m ynab_tui.mock_data.generate_mock_data
	@echo ""
	@echo "Step 2: Clear mock database..."
	uv run python -m ynab_tui.main --mock db-clear --yes
	@echo ""
	@echo "Step 3: Pull mock data into database..."
	uv run python -m ynab_tui.main --mock pull --full
	@echo ""
	@echo "Step 4: Generate pending splits..."
	uv run python -m ynab_tui.mock_data.generate_mock_data --pending-splits
	@echo ""
	@echo "Mock data generation complete!"

mock-prod-data:
	@echo "Exporting production database to mock CSV files..."
	@echo "Note: Run 'make pull' first to sync data from live APIs."
	uv run python -m ynab_tui.main db-transactions --year 2025 --csv ynab_tui/mock_data/transactions.csv
	uv run python -m ynab_tui.main ynab-categories --csv ynab_tui/mock_data/categories.csv
	uv run python -m ynab_tui.main db-amazon-orders --year 2025 --csv ynab_tui/mock_data/orders.csv
	@echo "Production data exported to ynab_tui/mock_data/"

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

# Sync commands (git-style)
pull:
	uv run python -m ynab_tui.main pull

pull-full:
	uv run python -m ynab_tui.main pull --full

push:
	uv run python -m ynab_tui.main push

push-dry:
	uv run python -m ynab_tui.main push --dry-run

db-status:
	uv run python -m ynab_tui.main db-status

# Release commands
build:
	uv build
