# YNAB TUI

[![CI](https://github.com/esterhui/ynab-tui/actions/workflows/ci.yml/badge.svg)](https://github.com/esterhui/ynab-tui/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

A terminal user interface for categorizing YNAB (You Need A Budget) transactions with Amazon order matching.

## Features

- **TUI for transaction review** - Review and categorize uncategorized transactions
- **Amazon order matching** - Scrapes your Amazon order history to identify purchased items
- **Split transaction support** - Split Amazon orders into individual items with separate categories
- **Historical pattern learning** - Learns from your categorization decisions for recurring payees
- **Git-style workflow** - Pull transactions to local DB, categorize offline, push changes back
- **Mock mode** - Test without real credentials using synthetic data

## Installation

```bash
# Clone and install
git clone https://github.com/esterhui/ynab-tui.git
cd ynab-tui
uv sync --all-extras
```

## Configuration

Copy the example config and fill in your credentials:

```bash
mkdir -p ~/.config/ynab-tui
cp config.example.toml ~/.config/ynab-tui/config.toml
```

Required credentials:
- **YNAB API token** - Get from https://app.ynab.com/settings/developer
- **Amazon credentials** - Your Amazon login (for order history scraping)

You can also use environment variables:
```bash
export YNAB_API_TOKEN="your-token"
export AMAZON_USERNAME="your-email"
export AMAZON_PASSWORD="your-password"
```

## Usage

### TUI (Terminal User Interface)

```bash
# Launch the TUI
uv run python -m src.main

# Or use mock mode (no credentials needed)
uv run python -m src.main --mock
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
- `q` - Quit

### CLI Commands

```bash
# Sync commands (git-style pull/push)
uv run python -m src.main pull              # Pull YNAB + Amazon data to local DB
uv run python -m src.main pull --full       # Full pull of all data
uv run python -m src.main push              # Push local categorizations to YNAB
uv run python -m src.main push --dry-run    # Preview what would be pushed

# List uncategorized transactions
uv run python -m src.main uncategorized

# Database status
uv run python -m src.main db-status

# Test connections
uv run python -m src.main ynab-test
uv run python -m src.main amazon-test
```

## How It Works

1. **Pull** transactions from YNAB and orders from Amazon to local SQLite database
2. **Match** Amazon transactions to orders by amount and date (fuzzy matching)
3. **Review** uncategorized transactions in the TUI
4. **Categorize** using the category picker or split into individual items
5. **Push** your changes back to YNAB

## Development

```bash
# Run tests
uv run pytest tests/ -v

# Lint and format
uv run ruff check src/ tests/
uv run ruff format src/ tests/

# Run with mock data (no credentials needed)
uv run python -m src.main --mock
```

## License

MIT
