# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**IMPORTANT:** DB location is `~/.config/ynab-tui/categorizer.db` (PROD) and `~/.config/ynab-tui/mock_categorizer.db` (mock)

**IMPORTANT:** Never clear the production database unless you ask the user and get permission

**IMPORTANT:** Always run "make format" before committing any work

## Project Overview

YNAB TUI is a transaction categorization tool for YNAB (You Need A Budget). It helps categorize uncategorized transactions by:
1. Matching Amazon transactions to scraped order history to identify purchased items
2. Using historical categorization patterns for recurring payees

## Commands

```bash
# Install dependencies
uv sync --all-extras

# Run the TUI application
uv run python -m src.main
uv run python -m src.main --mock            # Mock mode (no credentials needed)

# Sync commands (git-style pull/push)
uv run python -m src.main pull              # Incremental pull from YNAB + Amazon
uv run python -m src.main pull --full       # Full pull of all data
uv run python -m src.main push              # Push local categorizations to YNAB
uv run python -m src.main push --dry-run    # Preview what would be pushed

# Database commands
uv run python -m src.main db-status         # Show sync status and statistics
uv run python -m src.main db-transactions --uncategorized  # List uncategorized
uv run python -m src.main db-amazon-orders --year 2024     # List orders by year

# Testing commands
uv run python -m src.main ynab-test         # Test YNAB API connection
uv run python -m src.main amazon-test       # Test Amazon connection
uv run python -m src.main amazon-match      # Match Amazon transactions to orders

# Run tests
uv run pytest tests/ -v                     # All tests
uv run pytest tests/test_matcher.py -v      # Single test file
uv run pytest tests/test_matcher.py::test_name -v  # Single test
uv run pytest tests/ -n auto -q             # Parallel execution (faster)

# Lint and format
uv run ruff check src/ tests/
uv run ruff format src/ tests/
```

## Architecture

### Data Flow

```
YNAB API ──pull──→ Local SQLite DB ←──pull── Amazon Orders
                         ↓
              TransactionMatcher.enrich_transactions()
                         ↓
         ┌───────────────┴───────────────┐
         ↓                               ↓
    Amazon Transaction              Other Transaction
         ↓                               ↓
    Match to order by             Get historical payee
    amount + date                 category patterns
         ↓                               ↓
         └───────────────┬───────────────┘
                         ↓
              TUI for user review
                         ↓
              pending_changes table (local delta)
                         ↓
                    push to YNAB
```

### Core Components

**CategorizerService** (`src/services/categorizer.py`): Main orchestrator. Entry point for transaction operations, category application, and undo.

**TransactionMatcher** (`src/services/matcher.py`): Identifies Amazon transactions by payee patterns, matches to orders by amount (±$0.10) and date (two-stage: 7-day strict, 24-day extended).

**SyncService** (`src/services/sync.py`): Git-style pull/push:
- `pull_ynab()`: Downloads transactions (incremental with 7-day overlap)
- `pull_amazon()`: Downloads Amazon orders
- `push_ynab()`: Uploads pending changes to YNAB

**Database** (`src/db/database.py`): SQLite with mixin architecture:
- `TransactionMixin`: YNAB transaction CRUD
- `AmazonMixin`: Amazon orders and items cache
- `PendingChangesMixin`: Delta table for undo support
- `HistoryMixin`: Categorization learning history
- `SyncMixin`: Sync state tracking

**Clients** (`src/clients/`):
- `YNABClient`: Wraps `ynab` SDK. **YNAB amounts are in milliunits (1000 = $1.00)**
- `MockYNABClient`: Loads from CSV files in `src/mock_data/` for offline testing
- `AmazonClient`: Scrapes order history via `amazon-orders` library

### Key Tables

| Table | Purpose |
|-------|---------|
| `ynab_transactions` | Synced YNAB transactions with sync status |
| `pending_changes` | Local changes (delta) awaiting push |
| `amazon_orders_cache` | Cached Amazon orders |
| `amazon_order_items` | Items with prices for category learning |
| `categorization_history` | Historical decisions for pattern learning |

### Configuration

Config from `~/.config/ynab-tui/config.toml` with env var overrides:

| Setting | Env Variable | Default |
|---------|--------------|---------|
| YNAB API token | `YNAB_API_TOKEN` | required |
| YNAB budget | `YNAB_BUDGET_ID` | "last-used" |
| Amazon username | `AMAZON_USERNAME` | required |
| Amazon password | `AMAZON_PASSWORD` | required |

### TUI Keybindings

Vim-style navigation in `src/tui/app.py`:
- `j/k` or arrows: Navigate
- `g/G`: Top/bottom
- `c`: Categorize, `a`: Approve, `x`: Split, `u`: Undo
- `/`: Search, `p`: Preview pending, `q`: Quit

## Key Implementation Details

**Delta Table Design**: Changes are stored in `pending_changes` (not modifying `ynab_transactions`) until pushed. This enables undo and prevents data loss.

**Amazon Matching**: Two-stage fuzzy matching by amount (±$0.10) and date:
- Stage 1: 7-day window (strict)
- Stage 2: 24-day window (extended)
- Detects duplicate matches (same order → multiple transactions)

**Historical Learning**: Categorization decisions are recorded for pattern-based suggestions.

**Testing**: Use `--mock` flag for offline testing. Mock clients load from `src/mock_data/*.csv`. Tests use `pytest-asyncio` for TUI testing and fixtures in `tests/conftest.py`.

## Dev Notes

- Never use `git add -A`, always add specific files
- YNAB amounts are in **milliunits** (divide by 1000 for dollars)
- The database uses WAL mode for concurrent access
