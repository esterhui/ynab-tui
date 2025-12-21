"""Pure matching algorithms for Amazon order matching.

This package contains pure functions for matching transactions to orders,
separated from I/O operations for testability.
"""

from .algorithms import (
    calculate_date_range,
    find_best_order_match,
    find_combo_matches,
    find_unmatched_orders,
    match_transactions_two_stage,
)
from .types import AmazonMatchResult, TransactionInfo

__all__ = [
    "AmazonMatchResult",
    "TransactionInfo",
    "calculate_date_range",
    "find_best_order_match",
    "find_combo_matches",
    "find_unmatched_orders",
    "match_transactions_two_stage",
]
