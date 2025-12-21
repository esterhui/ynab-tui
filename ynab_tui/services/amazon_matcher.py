"""Amazon order matching service.

Extracts transaction-to-order matching logic for reuse across commands.
The actual matching algorithms are in matching/algorithms.py as pure functions.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional, Union

from ..config import AmazonConfig
from ..db.database import AmazonOrderCache, Database
from .matching import (
    AmazonMatchResult,
    TransactionInfo,
    calculate_date_range,
    find_best_order_match,
    find_combo_matches,
    find_unmatched_orders,
    match_transactions_two_stage,
)

if TYPE_CHECKING:
    from ..db.protocols import AmazonOrderRepositoryProtocol

# Re-export for backwards compatibility
__all__ = ["AmazonMatchResult", "AmazonOrderMatcher", "TransactionInfo"]


class AmazonOrderMatcher:
    """Service for matching YNAB transactions to Amazon orders.

    Uses two-stage matching:
    - Stage 1: Strict 7-day window
    - Stage 2: Extended 24-day window for remaining unmatched

    Also detects:
    - Duplicate matches (same order matching multiple transactions)
    - Combination matches (multiple transactions summing to one order)
    """

    def __init__(
        self,
        order_repo: Union[Database, "AmazonOrderRepositoryProtocol"],
        amazon_config: Optional[AmazonConfig] = None,
        stage1_window: Optional[int] = None,
        stage2_window: Optional[int] = None,
        amount_tolerance: Optional[float] = None,
    ):
        """Initialize matcher.

        Args:
            order_repo: Repository for Amazon order queries. Can be Database or
                       any object implementing AmazonOrderRepositoryProtocol.
            amazon_config: Amazon configuration (provides defaults for windows/tolerance).
            stage1_window: Days for first-pass strict matching (overrides config).
            stage2_window: Days for extended matching window (overrides config).
            amount_tolerance: Amount tolerance in dollars (overrides config).
        """
        self._order_repo = order_repo
        config = amazon_config or AmazonConfig()
        self.stage1_window = (
            stage1_window if stage1_window is not None else config.stage1_window_days
        )
        self.stage2_window = (
            stage2_window if stage2_window is not None else config.stage2_window_days
        )
        self.amount_tolerance = (
            amount_tolerance if amount_tolerance is not None else config.amount_tolerance
        )

    def normalize_transaction(self, txn: dict) -> TransactionInfo:
        """Convert raw transaction dict to TransactionInfo.

        Args:
            txn: Raw transaction dictionary from database.

        Returns:
            Normalized TransactionInfo object.
        """
        txn_amount = abs(txn["amount"])
        txn_date_str = (
            txn["date"][:10] if isinstance(txn["date"], str) else txn["date"].strftime("%Y-%m-%d")
        )
        txn_date = datetime.strptime(txn_date_str, "%Y-%m-%d")
        display_amount = (
            f"-${abs(txn['amount']):,.2f}" if txn["amount"] < 0 else f"${txn['amount']:,.2f}"
        )

        return TransactionInfo(
            transaction_id=txn.get("id", ""),
            amount=txn_amount,
            date=txn_date,
            date_str=txn_date_str,
            display_amount=display_amount,
            is_split=txn.get("is_split", False),
            category_id=txn.get("category_id"),
            category_name=txn.get("category_name"),
            approved=txn.get("approved", False),
            raw_data=txn,
        )

    def find_order_match(
        self,
        txn_info: TransactionInfo,
        orders: list[AmazonOrderCache],
        window_days: int,
        exclude_order_ids: Optional[set[str]] = None,
    ) -> Optional[AmazonOrderCache]:
        """Find best matching order for a transaction within date window.

        Delegates to pure function find_best_order_match().

        Args:
            txn_info: Transaction to match.
            orders: List of orders to search.
            window_days: Maximum days between transaction and order date.
            exclude_order_ids: Order IDs to skip (already matched).

        Returns:
            Best matching order or None if no match found.
        """
        return find_best_order_match(
            txn_info=txn_info,
            orders=orders,
            window_days=window_days,
            amount_tolerance=self.amount_tolerance,
            exclude_order_ids=exclude_order_ids,
        )

    def match_transactions(
        self,
        transactions: list[TransactionInfo],
        orders: list[AmazonOrderCache],
        all_transactions: Optional[list[TransactionInfo]] = None,
    ) -> AmazonMatchResult:
        """Match transactions to orders using two-stage matching.

        Delegates to pure function match_transactions_two_stage().

        Args:
            transactions: Transactions to match (typically unapproved Amazon txns).
            orders: Amazon orders to match against.
            all_transactions: All Amazon transactions (for reverse matching).
                             If None, reverse matching uses `transactions`.

        Returns:
            AmazonMatchResult with all match types.
        """
        return match_transactions_two_stage(
            transactions=transactions,
            orders=orders,
            stage1_window=self.stage1_window,
            stage2_window=self.stage2_window,
            amount_tolerance=self.amount_tolerance,
            all_transactions=all_transactions,
        )

    def _find_unmatched_orders(
        self,
        orders: list[AmazonOrderCache],
        all_transactions: list[TransactionInfo],
    ) -> list[AmazonOrderCache]:
        """Find orders that don't match any transaction.

        Delegates to pure function find_unmatched_orders().

        Args:
            orders: Orders to check.
            all_transactions: All Amazon transactions to check against.

        Returns:
            List of orders without matching transactions.
        """
        return find_unmatched_orders(
            orders=orders,
            all_transactions=all_transactions,
            window_days=self.stage2_window,
            amount_tolerance=self.amount_tolerance,
        )

    def _find_combo_matches(
        self,
        unmatched_txns: list[TransactionInfo],
        unmatched_orders: list[AmazonOrderCache],
    ) -> list[tuple[AmazonOrderCache, tuple[TransactionInfo, ...]]]:
        """Find combinations of transactions that sum to an order total.

        Delegates to pure function find_combo_matches().

        Args:
            unmatched_txns: Transactions without matches.
            unmatched_orders: Orders without matches.

        Returns:
            List of (order, tuple of transactions) for combo matches.
        """
        return find_combo_matches(
            unmatched_txns=unmatched_txns,
            unmatched_orders=unmatched_orders,
            window_days=self.stage2_window,
            amount_tolerance=self.amount_tolerance,
        )

    def get_orders_for_date_range(
        self, transactions: list[TransactionInfo]
    ) -> list[AmazonOrderCache]:
        """Get orders from database for the date range of transactions.

        Uses pure function calculate_date_range() then queries DB.

        Args:
            transactions: Transactions to get date range from.

        Returns:
            Orders within extended date range of transactions.
        """
        if not transactions:
            return []

        start_date, end_date = calculate_date_range(transactions, self.stage2_window)
        return self._order_repo.get_cached_orders_by_date_range(start_date, end_date)
