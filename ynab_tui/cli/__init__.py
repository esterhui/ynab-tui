"""CLI module for YNAB TUI.

This module provides shared helpers and formatters for CLI commands.
Commands are defined in src/main.py.
"""

from .formatters import (
    display_amazon_match_results,
    display_dry_run_amazon,
    display_dry_run_categories,
    display_pull_transactions,
    echo_error,
    echo_header,
    echo_success,
    echo_warning,
    format_category_row,
    format_pull_result,
    format_push_result,
    format_sync_time,
    format_transaction_row,
)
from .helpers import (
    display_pending_changes,
    format_date_for_display,
    get_categorizer,
    get_sync_service,
    require_data,
)

__all__ = [
    "display_amazon_match_results",
    "display_dry_run_amazon",
    "display_dry_run_categories",
    "display_pending_changes",
    "display_pull_transactions",
    "echo_error",
    "echo_header",
    "echo_success",
    "echo_warning",
    "format_category_row",
    "format_date_for_display",
    "format_pull_result",
    "format_push_result",
    "format_sync_time",
    "format_transaction_row",
    "get_categorizer",
    "get_sync_service",
    "require_data",
]
