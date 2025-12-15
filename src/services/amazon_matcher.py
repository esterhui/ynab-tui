"""Amazon order matching service.

Extracts transaction-to-order matching logic for reuse across commands.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import combinations
from typing import Optional

from ..config import AmazonConfig
from ..db.database import AmazonOrderCache, Database


@dataclass
class TransactionInfo:
    """Normalized transaction info for matching."""

    transaction_id: str
    amount: float  # Absolute value
    date: datetime
    date_str: str
    display_amount: str
    is_split: bool = False
    category_id: Optional[str] = None
    category_name: Optional[str] = None
    approved: bool = False
    raw_data: dict = field(default_factory=dict)  # Original transaction dict


@dataclass
class AmazonMatchResult:
    """Results from Amazon order matching."""

    stage1_matches: list[tuple[TransactionInfo, AmazonOrderCache]]
    stage2_matches: list[tuple[TransactionInfo, AmazonOrderCache]]
    duplicate_matches: list[tuple[TransactionInfo, AmazonOrderCache]]
    combo_matches: list[tuple[AmazonOrderCache, tuple[TransactionInfo, ...]]]
    unmatched_transactions: list[TransactionInfo]
    unmatched_orders: list[AmazonOrderCache]

    @property
    def all_matches(self) -> list[tuple[TransactionInfo, AmazonOrderCache]]:
        """All matched transactions (stage1 + stage2)."""
        return self.stage1_matches + self.stage2_matches

    @property
    def total_matched(self) -> int:
        """Total number of matched transactions."""
        return len(self.stage1_matches) + len(self.stage2_matches)


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
        db: Database,
        amazon_config: Optional[AmazonConfig] = None,
        stage1_window: Optional[int] = None,
        stage2_window: Optional[int] = None,
        amount_tolerance: Optional[float] = None,
    ):
        """Initialize matcher.

        Args:
            db: Database instance for querying transactions and orders.
            amazon_config: Amazon configuration (provides defaults for windows/tolerance).
            stage1_window: Days for first-pass strict matching (overrides config).
            stage2_window: Days for extended matching window (overrides config).
            amount_tolerance: Amount tolerance in dollars (overrides config).
        """
        self._db = db
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

        Args:
            txn_info: Transaction to match.
            orders: List of orders to search.
            window_days: Maximum days between transaction and order date.
            exclude_order_ids: Order IDs to skip (already matched).

        Returns:
            Best matching order or None if no match found.
        """
        exclude_order_ids = exclude_order_ids or set()
        best_match = None
        best_date_diff = float("inf")

        for order in orders:
            if order.order_id in exclude_order_ids:
                continue
            if abs(order.total - txn_info.amount) <= self.amount_tolerance:
                date_diff = abs((txn_info.date - order.order_date).days)
                if date_diff <= window_days and date_diff < best_date_diff:
                    best_match = order
                    best_date_diff = date_diff

        return best_match

    def match_transactions(
        self,
        transactions: list[TransactionInfo],
        orders: list[AmazonOrderCache],
        all_transactions: Optional[list[TransactionInfo]] = None,
    ) -> AmazonMatchResult:
        """Match transactions to orders using two-stage matching.

        Args:
            transactions: Transactions to match (typically unapproved Amazon txns).
            orders: Amazon orders to match against.
            all_transactions: All Amazon transactions (for reverse matching).
                             If None, reverse matching uses `transactions`.

        Returns:
            AmazonMatchResult with all match types.
        """
        if all_transactions is None:
            all_transactions = transactions

        matched_order_ids: set[str] = set()
        matched_txn_ids: set[str] = set()
        stage1_matches: list[tuple[TransactionInfo, AmazonOrderCache]] = []
        stage2_matches: list[tuple[TransactionInfo, AmazonOrderCache]] = []
        duplicate_matches: list[tuple[TransactionInfo, AmazonOrderCache]] = []
        unmatched_txns: list[TransactionInfo] = []

        # Stage 1: Strict window - find all potential matches first
        # Then sort by match quality: exact amount matches first, then by date
        stage1_candidates: list[tuple[TransactionInfo, AmazonOrderCache, float, int]] = []
        for txn_info in transactions:
            for order in orders:
                amount_diff = abs(order.total - txn_info.amount)
                if amount_diff <= self.amount_tolerance:
                    date_diff = abs((txn_info.date - order.order_date).days)
                    if date_diff <= self.stage1_window:
                        stage1_candidates.append((txn_info, order, amount_diff, date_diff))

        # Sort by amount difference first (exact matches first), then by date difference
        stage1_candidates.sort(key=lambda x: (x[2], x[3]))

        # Greedily assign matches - best matches first
        stage1_unmatched: list[TransactionInfo] = []
        for txn_info, order, amount_diff, date_diff in stage1_candidates:
            if txn_info.transaction_id in matched_txn_ids:
                continue  # Transaction already matched
            if order.order_id not in matched_order_ids:
                stage1_matches.append((txn_info, order))
                matched_order_ids.add(order.order_id)
                matched_txn_ids.add(txn_info.transaction_id)
            else:
                duplicate_matches.append((txn_info, order))
                matched_txn_ids.add(txn_info.transaction_id)

        # Find transactions that weren't matched in stage 1
        for txn_info in transactions:
            if txn_info.transaction_id not in matched_txn_ids:
                stage1_unmatched.append(txn_info)

        # Stage 2: Extended window for remaining unmatched - same approach
        stage2_candidates: list[tuple[TransactionInfo, AmazonOrderCache, float, int]] = []
        for txn_info in stage1_unmatched:
            for order in orders:
                amount_diff = abs(order.total - txn_info.amount)
                if amount_diff <= self.amount_tolerance:
                    date_diff = abs((txn_info.date - order.order_date).days)
                    if date_diff <= self.stage2_window:
                        stage2_candidates.append((txn_info, order, amount_diff, date_diff))

        stage2_candidates.sort(key=lambda x: (x[2], x[3]))

        for txn_info, order, amount_diff, date_diff in stage2_candidates:
            if txn_info.transaction_id in matched_txn_ids:
                continue
            if order.order_id not in matched_order_ids:
                stage2_matches.append((txn_info, order))
                matched_order_ids.add(order.order_id)
                matched_txn_ids.add(txn_info.transaction_id)
            else:
                duplicate_matches.append((txn_info, order))
                matched_txn_ids.add(txn_info.transaction_id)

        # Find truly unmatched transactions
        for txn_info in transactions:
            if txn_info.transaction_id not in matched_txn_ids:
                unmatched_txns.append(txn_info)

        # Reverse match: find orders without matching transactions
        unmatched_orders = self._find_unmatched_orders(orders, all_transactions)

        # Combination matching: try summing unmatched transactions
        combo_matches = self._find_combo_matches(unmatched_txns, unmatched_orders)

        # Filter out combo-matched items from unmatched lists
        combo_matched_order_ids = {order.order_id for order, _ in combo_matches}
        combo_matched_txn_keys = set()
        for _, combo_txns in combo_matches:
            for t in combo_txns:
                combo_matched_txn_keys.add((t.date_str, t.amount))

        truly_unmatched_orders = [
            o for o in unmatched_orders if o.order_id not in combo_matched_order_ids
        ]
        truly_unmatched_txns = [
            t for t in unmatched_txns if (t.date_str, t.amount) not in combo_matched_txn_keys
        ]

        return AmazonMatchResult(
            stage1_matches=stage1_matches,
            stage2_matches=stage2_matches,
            duplicate_matches=duplicate_matches,
            combo_matches=combo_matches,
            unmatched_transactions=truly_unmatched_txns,
            unmatched_orders=truly_unmatched_orders,
        )

    def _find_unmatched_orders(
        self,
        orders: list[AmazonOrderCache],
        all_transactions: list[TransactionInfo],
    ) -> list[AmazonOrderCache]:
        """Find orders that don't match any transaction.

        Args:
            orders: Orders to check.
            all_transactions: All Amazon transactions to check against.

        Returns:
            List of orders without matching transactions.
        """
        unmatched_orders = []

        for order in orders:
            if order.total == 0:
                continue

            has_match = False
            for txn in all_transactions:
                if abs(order.total - txn.amount) <= self.amount_tolerance:
                    date_diff = abs((txn.date - order.order_date).days)
                    if date_diff <= self.stage2_window:
                        has_match = True
                        break

            if not has_match:
                unmatched_orders.append(order)

        return unmatched_orders

    def _find_combo_matches(
        self,
        unmatched_txns: list[TransactionInfo],
        unmatched_orders: list[AmazonOrderCache],
    ) -> list[tuple[AmazonOrderCache, tuple[TransactionInfo, ...]]]:
        """Find combinations of transactions that sum to an order total.

        Args:
            unmatched_txns: Transactions without matches.
            unmatched_orders: Orders without matches.

        Returns:
            List of (order, tuple of transactions) for combo matches.
        """
        combo_matches: list[tuple[AmazonOrderCache, tuple[TransactionInfo, ...]]] = []

        if not unmatched_txns or not unmatched_orders:
            return combo_matches

        for order in unmatched_orders:
            nearby_txns = [
                t
                for t in unmatched_txns
                if abs((t.date - order.order_date).days) <= self.stage2_window
            ]

            if len(nearby_txns) < 2:
                continue

            found_combo = False
            for combo_size in range(2, min(5, len(nearby_txns) + 1)):
                if found_combo:
                    break
                for txn_combo in combinations(nearby_txns, combo_size):
                    combo_total = sum(t.amount for t in txn_combo)
                    if abs(combo_total - order.total) <= self.amount_tolerance:
                        combo_matches.append((order, txn_combo))
                        found_combo = True
                        break

        return combo_matches

    def get_orders_for_date_range(
        self, transactions: list[TransactionInfo]
    ) -> list[AmazonOrderCache]:
        """Get orders from database for the date range of transactions.

        Args:
            transactions: Transactions to get date range from.

        Returns:
            Orders within extended date range of transactions.
        """
        if not transactions:
            return []

        dates = [t.date for t in transactions]
        earliest_date = min(dates)
        latest_date = max(dates)

        start_date = earliest_date - timedelta(days=self.stage2_window)
        end_date = latest_date + timedelta(days=self.stage2_window)

        return self._db.get_cached_orders_by_date_range(start_date, end_date)
