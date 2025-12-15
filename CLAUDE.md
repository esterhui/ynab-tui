# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

IMPORTANT: DB location is ~/.config/ynab-cli/categorizer.db (PROD) and for mock it's ~/.config/ynab-cli/mock_categorizer.db

IMPORTANT: Never clear the production (PROD) database categorizer.db unless you ask the user and get permission

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

# CLI commands
uv run python -m src.main uncategorized     # List uncategorized transactions

# Sync commands (git-style pull/push)
uv run python -m src.main pull              # Pull YNAB + Amazon data to local DB (incremental)
uv run python -m src.main pull --full       # Full pull of all data
uv run python -m src.main pull --ynab-only  # Only pull YNAB transactions
uv run python -m src.main pull --amazon-only --amazon-year 2024  # Pull specific year
uv run python -m src.main push              # Push local categorizations to YNAB
uv run python -m src.main push --dry-run    # Preview what would be pushed

# Database query commands
uv run python -m src.main db-status                      # Show database sync status
uv run python -m src.main db-transactions                # List all transactions from DB
uv run python -m src.main db-transactions --uncategorized  # Only uncategorized
uv run python -m src.main db-transactions --pending      # Only pending push
uv run python -m src.main db-transactions --payee Amazon  # Filter by payee
uv run python -m src.main db-amazon-orders               # List Amazon orders from DB
uv run python -m src.main db-amazon-orders --year 2024   # List orders for specific year

# YNAB commands
uv run python -m src.main ynab-test           # Test YNAB API connection
uv run python -m src.main ynab-budgets        # List available budgets (shows which is selected)
uv run python -m src.main ynab-categories     # List YNAB categories
uv run python -m src.main ynab-unapproved     # List unapproved transactions

# Amazon commands
uv run python -m src.main amazon-test         # Test Amazon connection and authentication
uv run python -m src.main amazon-match        # Match Amazon transactions to orders

# Category mapping commands
uv run python -m src.main mappings            # Show learned item→category mappings
uv run python -m src.main mappings-create     # Learn mappings from approved transactions

# Export to CSV (for generating mock data)
uv run python -m src.main db-transactions --csv src/mock_data/transactions.csv
uv run python -m src.main ynab-categories --csv src/mock_data/categories.csv
uv run python -m src.main db-amazon-orders --csv src/mock_data/orders.csv

# Testing with mock clients (no real credentials needed)
uv run python -m src.main --mock uncategorized     # Uses mock DB + mock clients
uv run python -m src.main --mock db-clear          # Only clears mock DB (safe)

# Run tests
uv run pytest tests/ -v

# Lint and format
uv run ruff check src/ tests/
uv run ruff format src/ tests/

# Makefile shortcuts
make pull         # Incremental pull
make pull-full    # Full pull
make push         # Push local changes to YNAB
make push-dry     # Preview push
make db-status    # Show database status
```

## Architecture

### Data Flow

```
YNAB API → Uncategorized Transactions
                    ↓
         TransactionMatcher.enrich_transactions()
                    ↓
    ┌───────────────┴───────────────┐
    ↓                               ↓
Amazon Transaction              Other Transaction
    ↓                               ↓
AmazonClient.find_matching_order()  Database.get_payee_category_distribution()
    ↓                               ↓
Get item names from order       Get historical patterns
    ↓                               ↓
    └───────────────┬───────────────┘
                    ↓
         TUI for user review
                    ↓
         YNABClient.update_transaction_category()
                    ↓
         Database.add_categorization() (for learning)
```

### Core Components

**CategorizerService** (`src/services/categorizer.py`): Main orchestrator that coordinates the categorization workflow. Entry point for all transaction operations.

**TransactionMatcher** (`src/services/matcher.py`): Identifies Amazon transactions by payee patterns, matches them to Amazon orders by amount and date (fuzzy matching with configurable window).

**Clients** (`src/clients/`):
- `YNABClient`: Wraps official `ynab` SDK for transaction and category operations. YNAB amounts are in milliunits (1000 = $1.00).
- `MockYNABClient`: Loads data from CSV files in `src/mock_data/` for offline testing.
- `AmazonClient`: Scrapes Amazon order history using `amazon-orders` library. Requires login credentials. Orders are cached in SQLite.

**Database** (`src/db/database.py`): SQLite storage for:
- `ynab_transactions`: All synced YNAB transactions (approved, uncategorized, etc.) with sync status
- `amazon_orders_cache`: Cached Amazon orders
- `amazon_order_items`: Individual items from orders (for category learning)
- `categorization_history`: Historical categorization decisions (for learning)
- `sync_state`: Tracks last sync date/time for incremental updates

**SyncService** (`src/services/sync.py`): Git-style pull/push operations:
- `pull_ynab()`: Downloads all YNAB transactions to local DB (incremental with 7-day overlap)
- `pull_amazon()`: Downloads Amazon orders to local DB
- `push_ynab()`: Uploads local categorization changes to YNAB (only when explicitly called)

**Models** (`src/models/`):
- `Transaction`: Central model combining YNAB data and Amazon enrichment
- `SubTransaction`: Split transaction components (YNAB requires per-split categorization)
- `CategoryList`/`Category`: YNAB budget categories with search functionality
- `AmazonOrder`/`OrderMatch`: Amazon order data and matching results

### Configuration

Config is loaded from TOML with environment variable overrides (env vars take precedence):

| Setting | Env Variable | Default |
|---------|--------------|---------|
| YNAB API token | `YNAB_API_TOKEN` | required |
| YNAB budget | `YNAB_BUDGET_ID` | "last-used" |
| Amazon username | `AMAZON_USERNAME` | required |
| Amazon password | `AMAZON_PASSWORD` | required |
| Date match window | `DATE_MATCH_WINDOW_DAYS` | 14 |

### TUI Design

The Textual-based TUI (`src/tui/app.py`) uses vim-style keybindings:
- `j/k` or arrows for navigation
- `g/G` for top/bottom
- `Ctrl+d/u` for page up/down
- `c` for categorize, `a` for approve, `x` for split, `u` for undo

## Key Implementation Details

**Amazon Matching**: Uses two-stage fuzzy matching by amount (within 10 cents) and date:
- Stage 1: 7-day window for strict matches
- Stage 2: 24-day window for remaining unmatched transactions
Also detects duplicate matches (same order matching multiple transactions).

**Historical Learning**: Every categorization decision is recorded in SQLite for pattern-based categorization assistance.

**Mock Clients**: `MockYNABClient` and `MockAmazonClient` allow testing without real credentials. Use `--mock` flag. MockYNABClient loads transaction and category data from CSV files in `src/mock_data/`.

### Dev

IMPORTANT: Never use git add -A, always add the files you changed instead
