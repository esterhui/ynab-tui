# Changelog

All notable changes to YNAB TUI will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-01-04

### Added
- **Conflict detection**: Preserve local category when YNAB returns "Uncategorized" after push; shows "!" flag in TUI with `pull --fix` to resolve
- `pull --dry-run` flag with detailed insert/update/conflict preview
- `pull --since-days` support for YNAB pull (previously Amazon-only)
- Dedicated help screen (`?` to open/close)
- Pending and conflict counts in status bar
- Push verification logging for debugging sync issues

### Changed
- Simplify push preview: Enter/y pushes, q/n/Esc cancels (removed intermediate step)
- Escape key now context-aware: clears filters first, then quits
- Rename "new" filter to "unapproved" (keybinding `n` -> `a`)
- Rename flags: `--ynab-only`/`--amazon-only` -> `--ynab`/`--amazon`
- Split transactions display "Split" consistently (matching YNAB)
- Condense TUI: compact status bar, reduce footer shortcuts to essentials
- Flatten DB mixins and merge matching/ directory (code consolidation)

### Fixed
- Pull no longer overwrites locally categorized transactions
- PageUp/PageDown/Home/End now move cursor (not just viewport)
- Push screen no longer flickers after successful push
- Split transactions show correct category in push preview
- Filter reset key changed from `x` to `r` (was conflicting with Split)

### Removed
- Dead code cleanup: protocol files, unused services, ~1,200 lines removed
- "approved" filter (rarely used)


## [0.1.1] - 2025-12-21

### Changed
- Restrict Python version to 3.11 due to `amazoncaptcha` dependency requiring `pillow<9.6.0` which only has Linux/macOS wheels for Python 3.11
- Rename package directory from `src/` to `ynab_tui/` for conventional Python packaging

### Added
- Wheel install testing in CI before PyPI publish to catch dependency issues
- `--test-install` flag in release script for local wheel verification


## [0.1.0] - 2024-12-20

Initial release of YNAB TUI - a terminal user interface for categorizing YNAB transactions with Amazon order matching.

### Added

#### Core Features
- Interactive terminal UI built with Textual
- Vim-style navigation (j/k, g/G, Ctrl+d/u, Ctrl+f/b)
- Git-style sync workflow: `pull` downloads data, `push` uploads categorizations
- Offline-first architecture with local SQLite database
- Transaction memo viewing and editing

#### Amazon Integration
- Automatic matching of Amazon transactions to order history
- Two-stage fuzzy matching by amount (within $0.10) and date (7-24 day window)
- Split transaction support for multi-item Amazon orders
- Item-level visibility: see actual purchased items instead of generic "Amazon.com"
- Duplicate and combo match detection

#### Categorization
- Category picker modal with fuzzy search
- Bulk tagging for batch categorization (t/T keys)
- Historical pattern learning from approved transactions
- Undo support for pending changes before push

#### Multi-Budget Support
- Switch between YNAB budgets (b key or --budget flag)
- Budget picker modal with fuzzy search

#### Filtering & Search
- Filter by status: all, approved, new, uncategorized, pending
- Filter by category or payee with picker modals
- Real-time fuzzy search across transactions (/)
- Configurable search matching modes

#### CLI Commands
- `pull` / `push` - Sync with YNAB and Amazon
- `db-status` - Show sync status and statistics
- `db-deltas` - Preview pending changes before push
- `db-transactions` - Query and export transactions
- `db-amazon-orders` - Query and export Amazon orders
- `mappings` / `mappings-create` - Category pattern management
- `ynab-test` / `amazon-test` - Connection testing
- `ynab-categories` / `ynab-budgets` - List YNAB data
- CSV export for transactions, orders, and categories

#### Developer Experience
- Mock mode (`--mock`) for testing without credentials
- Comprehensive test suite with pytest
- Type hints throughout codebase
