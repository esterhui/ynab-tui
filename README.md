# YNAB TUI

[![CI](https://github.com/esterhui/ynab-tui/actions/workflows/ci.yml/badge.svg)](https://github.com/esterhui/ynab-tui/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/esterhui/ynab-tui/graph/badge.svg)](https://codecov.io/gh/esterhui/ynab-tui)
[![PyPI](https://img.shields.io/pypi/v/ynab-tui)](https://pypi.org/project/ynab-tui/)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

A terminal user interface for categorizing YNAB (You Need A Budget) transactions with Amazon order matching.

![YNAB TUI Screenshot](ynab-tui-screenshot.png)

## Features

- **TUI for transaction review** - Review and categorize uncategorized transactions
- **Amazon order matching** - Scrapes your Amazon order history to identify purchased items
- **Split transaction support** - Split Amazon orders into individual items with separate categories
- **Historical pattern learning** - Learns from your categorization decisions for recurring payees
- **Git-style workflow** - Pull transactions to local DB, categorize offline, push changes back
- **Multi-budget support** - Switch between YNAB budgets
- **Advanced filtering** - Filter transactions by category, payee, or status
- **Bulk tagging** - Tag multiple transactions for batch operations
- **Undo support** - Revert categorizations before pushing
- **CSV export** - Export transaction data for external analysis
- **Mock mode** - Test without real credentials using synthetic data

## Installation

**Requires Python 3.11** (Python 3.12+ not yet supported due to a [dependency issue](https://github.com/a-maliarov/amazoncaptcha/issues/47) with amazoncaptcha/pillow)

### From PyPI (Recommended)

```bash
# With pip (ensure Python 3.11)
pip install ynab-tui

# With uv (specify Python version)
uv pip install ynab-tui --python 3.11

# With pipx
pipx install ynab-tui --python python3.11
```

### From Source

```bash
git clone https://github.com/esterhui/ynab-tui.git
cd ynab-tui
uv sync --all-extras
```

## Configuration

Initialize the configuration file:

```bash
ynab-tui init
```

This creates `~/.config/ynab-tui/config.toml`. Edit it to add your credentials:

- **YNAB API token** (required) - Get from https://app.ynab.com/settings/developer
- **Amazon credentials** (optional) - For order history scraping via [amazon-orders](https://github.com/alexdlaird/amazon-orders)

You can also use environment variables instead of the config file:
```bash
export YNAB_API_TOKEN="your-token"
export AMAZON_USERNAME="your-email"
export AMAZON_PASSWORD="your-password"
```

## Usage

### TUI (Terminal User Interface)

```bash
# Launch the TUI
ynab-tui

# Or use mock mode (no credentials needed)
ynab-tui --mock

# Show version
ynab-tui --version
```

**Vim-style keybindings:**
- `j/k` or arrows - Navigate up/down
- `g/G` - Go to top/bottom
- `Ctrl+d/u` - Page down/up
- `c` - Categorize selected transaction
- `a` - Approve transaction
- `x` - Split transaction (for Amazon orders)
- `u` - Undo last change
- `p` - Preview pending changes
- `/` - Search transactions
- `f` - Cycle filter (all/approved/uncategorized/pending)
- `t` - Tag transaction for bulk operations
- `T` - Clear all tags
- `b` - Switch budget
- `s` - Settings
- `?` - Help
- `q` - Quit

### CLI Commands

```bash
# Setup
ynab-tui init              # Create config file at ~/.config/ynab-tui/config.toml

# Sync commands (git-style pull/push)
ynab-tui pull              # Pull YNAB + Amazon data to local DB
ynab-tui pull --full       # Full pull of all data
ynab-tui push              # Push local categorizations to YNAB
ynab-tui push --dry-run    # Preview what would be pushed

# List uncategorized transactions
ynab-tui uncategorized

# Database inspection
ynab-tui db-status         # Show sync status and statistics
ynab-tui db-deltas         # Show pending changes before push
ynab-tui ynab-budgets      # List available budgets

# Category mappings (learn from history)
ynab-tui mappings          # Query learned item->category mappings
ynab-tui mappings-create   # Build mappings from approved transactions

# Test connections
ynab-tui ynab-test
ynab-tui amazon-test
```

### Makefile

A Makefile is provided for common tasks. Run `make help` to see all available targets:

```
YNAB TUI

Make targets:
  make install    - Install dependencies
  make run        - Launch TUI application
  make test       - Run tests
  make coverage   - Run tests with coverage report
  make sloc       - Count lines of code (requires scc)
  make check      - Lint code
  make format     - Format code
  make mock-data  - Generate synthetic mock CSV data (deterministic)
  make mock-prod-data - Export production DB to mock CSV files
  make clean      - Remove cache files

Sync commands (git-style):
  make pull       - Pull YNAB + Amazon data to local DB (incremental)
  make pull-full  - Full pull of all data
  make push       - Push local categorizations to YNAB
  make push-dry   - Preview what would be pushed
  make db-status  - Show database sync status

CLI examples:
  uv run python -m ynab_tui.main                     # Launch TUI
  uv run python -m ynab_tui.main amazon-match        # Match Amazon transactions
  uv run python -m ynab_tui.main uncategorized       # List uncategorized transactions
  uv run python -m ynab_tui.main --help              # Show all commands

Mock mode (no live APIs):
  uv run python -m ynab_tui.main --mock              # Launch TUI with mock data
  uv run python -m ynab_tui.main --mock db-clear     # Only clears mock DB
```

## How It Works

1. **Pull** transactions from YNAB and orders from Amazon to local SQLite database
2. **Match** Amazon transactions to orders by amount and date (fuzzy matching)
3. **Review** uncategorized transactions in the TUI
4. **Categorize** using the category picker or split into individual items
5. **Push** your changes back to YNAB

### Data Storage

Transaction and order data is stored locally in an **unencrypted** SQLite database at `~/.config/ynab-tui/categorizer.db`. This includes your YNAB transactions, Amazon order history, and categorization decisions.

For security, ensure appropriate file permissions:
```bash
chmod 600 ~/.config/ynab-tui/*.db
```

Database encryption is planned for a future release.

### Typical Workflow

**First time setup:**
```bash
# Do a full pull to download all YNAB transactions and Amazon order history
ynab-tui pull --full
```

**Ongoing usage:**
```bash
# 1. Pull new transactions (incremental - only fetches recent changes)
ynab-tui pull

# 2. Launch the TUI to review and categorize
ynab-tui

# 3. In the TUI: navigate with j/k, categorize with 'c', approve with 'a'
#    For Amazon orders, use 'x' to split into individual items

# 4. Push your changes back to YNAB (from CLI or use 'P' in TUI)
ynab-tui push

# Optional: preview changes before pushing
ynab-tui push --dry-run
```

### Amazon Order Matching

YNAB transactions from Amazon typically show as "Amazon.com" with just the total amount, making it difficult to know what you actually purchased. This tool uses [amazon-orders](https://github.com/alexdlaird/amazon-orders) to scrape your Amazon order history and match transactions to specific orders.

**How matching works:**
- Matches by amount (within $0.10 tolerance) and date (7-day window, extended to 24 days if needed)
- Once matched, the TUI shows the actual items purchased instead of just "Amazon.com"
- You can then categorize the whole order, or use split (`x`) to break it into individual items with separate categories

**Example:** A $45.67 Amazon transaction gets matched to an order containing:
- Book: "Clean Code" - $29.99 → Categorize as "Books"
- USB Cable - $15.68 → Categorize as "Electronics"

This makes Amazon transactions much easier to categorize accurately.

## Development

```bash
# Run tests
uv run pytest tests/ -v

# Lint and format
uv run ruff check ynab_tui/ tests/
uv run ruff format ynab_tui/ tests/

# Run with mock data (no credentials needed)
ynab-tui --mock

# Build package
make build

# Full release check (lint, test, build)
make release
```

## License

MIT
