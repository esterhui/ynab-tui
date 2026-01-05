"""Amazon order matching service with pure matching algorithms."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import combinations
from typing import Any, Optional

from ..config import AmazonConfig
from ..db.database import AmazonOrderCache, Database

__all__ = ["AmazonMatchResult", "AmazonOrderMatcher", "TransactionInfo"]


@dataclass
class TransactionInfo:
    """Normalized transaction data for matching.

    This is a lightweight representation of transaction data needed
    for the matching algorithm. It's independent of any specific
    Transaction model to keep matching logic pure and testable.
    """

    transaction_id: str
    amount: float  # Always positive (absolute value)
    date: datetime
    date_str: str  # YYYY-MM-DD format
    display_amount: str  # For display: "-$50.00" or "$50.00"
    is_split: bool = False
    category_id: str | None = None
    category_name: str | None = None
    approved: bool = False
    raw_data: dict[str, Any] | None = field(default=None, repr=False)


@dataclass
class AmazonMatchResult:
    """Results from matching transactions to Amazon orders."""

    stage1_matches: list[tuple[TransactionInfo, AmazonOrderCache]] = field(default_factory=list)
    stage2_matches: list[tuple[TransactionInfo, AmazonOrderCache]] = field(default_factory=list)
    duplicate_matches: list[tuple[TransactionInfo, AmazonOrderCache]] = field(default_factory=list)
    combo_matches: list[tuple[AmazonOrderCache, tuple[TransactionInfo, ...]]] = field(
        default_factory=list
    )
    unmatched_transactions: list[TransactionInfo] = field(default_factory=list)
    unmatched_orders: list[AmazonOrderCache] = field(default_factory=list)

    @property
    def all_matches(self) -> list[tuple[TransactionInfo, AmazonOrderCache]]:
        """All 1:1 matches (stage1 + stage2)."""
        return self.stage1_matches + self.stage2_matches

    @property
    def total_matched(self) -> int:
        """Total count of matched transactions."""
        return len(self.all_matches)


def calculate_date_range(
    transactions: list[TransactionInfo], window_days: int
) -> tuple[datetime, datetime]:
    """Calculate date range for order lookup based on transactions."""
    if not transactions:
        now = datetime.now()
        return (now, now)
    dates = [t.date for t in transactions]
    return (min(dates) - timedelta(days=window_days), max(dates) + timedelta(days=window_days))


def find_best_order_match(
    txn_info: TransactionInfo,
    orders: list[AmazonOrderCache],
    window_days: int,
    amount_tolerance: float,
    exclude_order_ids: Optional[set[str]] = None,
) -> Optional[AmazonOrderCache]:
    """Find best matching order for a transaction within date window."""
    exclude_order_ids = exclude_order_ids or set()
    best_match, best_date_diff = None, float("inf")
    for order in orders:
        if order.order_id in exclude_order_ids:
            continue
        if abs(order.total - txn_info.amount) <= amount_tolerance:
            date_diff = abs((txn_info.date - order.order_date).days)
            if date_diff <= window_days and date_diff < best_date_diff:
                best_match, best_date_diff = order, date_diff
    return best_match


def find_unmatched_orders(
    orders: list[AmazonOrderCache],
    all_transactions: list[TransactionInfo],
    window_days: int,
    amount_tolerance: float,
) -> list[AmazonOrderCache]:
    """Find orders that don't match any transaction."""
    unmatched = []
    for order in orders:
        if order.total == 0:
            continue
        has_match = any(
            abs(order.total - txn.amount) <= amount_tolerance
            and abs((txn.date - order.order_date).days) <= window_days
            for txn in all_transactions
        )
        if not has_match:
            unmatched.append(order)
    return unmatched


def find_combo_matches(
    unmatched_txns: list[TransactionInfo],
    unmatched_orders: list[AmazonOrderCache],
    window_days: int,
    amount_tolerance: float,
) -> list[tuple[AmazonOrderCache, tuple[TransactionInfo, ...]]]:
    """Find combinations of transactions that sum to an order total."""
    combo_matches: list[tuple[AmazonOrderCache, tuple[TransactionInfo, ...]]] = []
    if not unmatched_txns or not unmatched_orders:
        return combo_matches
    for order in unmatched_orders:
        nearby_txns = [
            t for t in unmatched_txns if abs((t.date - order.order_date).days) <= window_days
        ]
        if len(nearby_txns) < 2:
            continue
        found_combo = False
        for combo_size in range(2, min(5, len(nearby_txns) + 1)):
            if found_combo:
                break
            for txn_combo in combinations(nearby_txns, combo_size):
                if abs(sum(t.amount for t in txn_combo) - order.total) <= amount_tolerance:
                    combo_matches.append((order, txn_combo))
                    found_combo = True
                    break
    return combo_matches


def match_transactions_two_stage(
    transactions: list[TransactionInfo],
    orders: list[AmazonOrderCache],
    stage1_window: int,
    stage2_window: int,
    amount_tolerance: float,
    all_transactions: Optional[list[TransactionInfo]] = None,
) -> AmazonMatchResult:
    """Match transactions to orders using two-stage matching."""
    if all_transactions is None:
        all_transactions = transactions

    matched_order_ids: set[str] = set()
    matched_txn_ids: set[str] = set()
    stage1_matches, stage2_matches = [], []
    duplicate_matches, unmatched_txns = [], []

    # Stage 1: Strict window
    stage1_candidates = []
    for txn_info in transactions:
        for order in orders:
            amount_diff = abs(order.total - txn_info.amount)
            if amount_diff <= amount_tolerance:
                date_diff = abs((txn_info.date - order.order_date).days)
                if date_diff <= stage1_window:
                    stage1_candidates.append((txn_info, order, amount_diff, date_diff))
    stage1_candidates.sort(key=lambda x: (x[2], x[3]))

    for txn_info, order, _, _ in stage1_candidates:
        if txn_info.transaction_id in matched_txn_ids:
            continue
        if order.order_id not in matched_order_ids:
            stage1_matches.append((txn_info, order))
            matched_order_ids.add(order.order_id)
            matched_txn_ids.add(txn_info.transaction_id)
        else:
            duplicate_matches.append((txn_info, order))
            matched_txn_ids.add(txn_info.transaction_id)

    stage1_unmatched = [t for t in transactions if t.transaction_id not in matched_txn_ids]

    # Stage 2: Extended window
    stage2_candidates = []
    for txn_info in stage1_unmatched:
        for order in orders:
            amount_diff = abs(order.total - txn_info.amount)
            if amount_diff <= amount_tolerance:
                date_diff = abs((txn_info.date - order.order_date).days)
                if date_diff <= stage2_window:
                    stage2_candidates.append((txn_info, order, amount_diff, date_diff))
    stage2_candidates.sort(key=lambda x: (x[2], x[3]))

    for txn_info, order, _, _ in stage2_candidates:
        if txn_info.transaction_id in matched_txn_ids:
            continue
        if order.order_id not in matched_order_ids:
            stage2_matches.append((txn_info, order))
            matched_order_ids.add(order.order_id)
            matched_txn_ids.add(txn_info.transaction_id)
        else:
            duplicate_matches.append((txn_info, order))
            matched_txn_ids.add(txn_info.transaction_id)

    unmatched_txns = [t for t in transactions if t.transaction_id not in matched_txn_ids]
    unmatched_orders = find_unmatched_orders(
        orders, all_transactions, stage2_window, amount_tolerance
    )
    combo_matches = find_combo_matches(
        unmatched_txns, unmatched_orders, stage2_window, amount_tolerance
    )

    # Filter combo-matched items
    combo_order_ids = {order.order_id for order, _ in combo_matches}
    combo_txn_keys = {(t.date_str, t.amount) for _, txns in combo_matches for t in txns}

    return AmazonMatchResult(
        stage1_matches=stage1_matches,
        stage2_matches=stage2_matches,
        duplicate_matches=duplicate_matches,
        combo_matches=combo_matches,
        unmatched_transactions=[
            t for t in unmatched_txns if (t.date_str, t.amount) not in combo_txn_keys
        ],
        unmatched_orders=[o for o in unmatched_orders if o.order_id not in combo_order_ids],
    )


class AmazonOrderMatcher:
    """Service for matching YNAB transactions to Amazon orders."""

    def __init__(
        self,
        order_repo: Database,
        amazon_config: Optional[AmazonConfig] = None,
        stage1_window: Optional[int] = None,
        stage2_window: Optional[int] = None,
        amount_tolerance: Optional[float] = None,
    ):
        """Initialize matcher."""
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
        """Convert raw transaction dict to TransactionInfo."""
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
        """Find best matching order for a transaction within date window."""
        return find_best_order_match(
            txn_info, orders, window_days, self.amount_tolerance, exclude_order_ids
        )

    def match_transactions(
        self,
        transactions: list[TransactionInfo],
        orders: list[AmazonOrderCache],
        all_transactions: Optional[list[TransactionInfo]] = None,
    ) -> AmazonMatchResult:
        """Match transactions to orders using two-stage matching."""
        return match_transactions_two_stage(
            transactions,
            orders,
            self.stage1_window,
            self.stage2_window,
            self.amount_tolerance,
            all_transactions,
        )

    def _find_unmatched_orders(
        self, orders: list[AmazonOrderCache], all_transactions: list[TransactionInfo]
    ) -> list[AmazonOrderCache]:
        return find_unmatched_orders(
            orders, all_transactions, self.stage2_window, self.amount_tolerance
        )

    def _find_combo_matches(
        self, unmatched_txns: list[TransactionInfo], unmatched_orders: list[AmazonOrderCache]
    ):
        return find_combo_matches(
            unmatched_txns, unmatched_orders, self.stage2_window, self.amount_tolerance
        )

    def get_orders_for_date_range(
        self, transactions: list[TransactionInfo]
    ) -> list[AmazonOrderCache]:
        """Get orders from database for the date range of transactions."""
        if not transactions:
            return []
        start_date, end_date = calculate_date_range(transactions, self.stage2_window)
        return self._order_repo.get_cached_orders_by_date_range(start_date, end_date)
