"""Pure matching algorithms for Amazon order matching.

All functions in this module are pure - they take data in and return data out
with no side effects or I/O operations. This makes them fully testable without
any mocks or database setup.
"""

from datetime import datetime, timedelta
from itertools import combinations
from typing import Optional

from ...db.database import AmazonOrderCache
from .types import AmazonMatchResult, TransactionInfo


def calculate_date_range(
    transactions: list[TransactionInfo],
    window_days: int,
) -> tuple[datetime, datetime]:
    """Calculate date range for order lookup based on transactions.

    Args:
        transactions: Transactions to get date range from.
        window_days: Number of days to extend the range on each side.

    Returns:
        Tuple of (start_date, end_date) for the query window.
    """
    if not transactions:
        now = datetime.now()
        return (now, now)

    dates = [t.date for t in transactions]
    earliest_date = min(dates)
    latest_date = max(dates)

    start_date = earliest_date - timedelta(days=window_days)
    end_date = latest_date + timedelta(days=window_days)

    return (start_date, end_date)


def find_best_order_match(
    txn_info: TransactionInfo,
    orders: list[AmazonOrderCache],
    window_days: int,
    amount_tolerance: float,
    exclude_order_ids: Optional[set[str]] = None,
) -> Optional[AmazonOrderCache]:
    """Find best matching order for a transaction within date window.

    Matches by amount (within tolerance) and date (within window).
    Returns the order with the smallest date difference if multiple match.

    Args:
        txn_info: Transaction to match.
        orders: List of orders to search.
        window_days: Maximum days between transaction and order date.
        amount_tolerance: Maximum difference in amounts (dollars).
        exclude_order_ids: Order IDs to skip (already matched).

    Returns:
        Best matching order or None if no match found.
    """
    exclude_order_ids = exclude_order_ids or set()
    best_match: Optional[AmazonOrderCache] = None
    best_date_diff = float("inf")

    for order in orders:
        if order.order_id in exclude_order_ids:
            continue
        if abs(order.total - txn_info.amount) <= amount_tolerance:
            date_diff = abs((txn_info.date - order.order_date).days)
            if date_diff <= window_days and date_diff < best_date_diff:
                best_match = order
                best_date_diff = date_diff

    return best_match


def find_unmatched_orders(
    orders: list[AmazonOrderCache],
    all_transactions: list[TransactionInfo],
    window_days: int,
    amount_tolerance: float,
) -> list[AmazonOrderCache]:
    """Find orders that don't match any transaction.

    Args:
        orders: Orders to check.
        all_transactions: All Amazon transactions to check against.
        window_days: Maximum days between transaction and order date.
        amount_tolerance: Maximum difference in amounts (dollars).

    Returns:
        List of orders without matching transactions.
    """
    unmatched_orders = []

    for order in orders:
        if order.total == 0:
            continue

        has_match = False
        for txn in all_transactions:
            if abs(order.total - txn.amount) <= amount_tolerance:
                date_diff = abs((txn.date - order.order_date).days)
                if date_diff <= window_days:
                    has_match = True
                    break

        if not has_match:
            unmatched_orders.append(order)

    return unmatched_orders


def find_combo_matches(
    unmatched_txns: list[TransactionInfo],
    unmatched_orders: list[AmazonOrderCache],
    window_days: int,
    amount_tolerance: float,
) -> list[tuple[AmazonOrderCache, tuple[TransactionInfo, ...]]]:
    """Find combinations of transactions that sum to an order total.

    Tries combinations of 2-4 transactions that are within the date window
    and sum to an order's total within the tolerance.

    Args:
        unmatched_txns: Transactions without matches.
        unmatched_orders: Orders without matches.
        window_days: Maximum days between transaction and order date.
        amount_tolerance: Maximum difference in amounts (dollars).

    Returns:
        List of (order, tuple of transactions) for combo matches.
    """
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
                combo_total = sum(t.amount for t in txn_combo)
                if abs(combo_total - order.total) <= amount_tolerance:
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
    """Match transactions to orders using two-stage matching.

    Stage 1: Strict window matching (typically 7 days)
    Stage 2: Extended window for remaining unmatched (typically 24 days)

    Also detects duplicate matches (same order matching multiple transactions)
    and combo matches (multiple transactions summing to one order).

    Args:
        transactions: Transactions to match (typically unapproved Amazon txns).
        orders: Amazon orders to match against.
        stage1_window: Days for first-pass strict matching.
        stage2_window: Days for extended matching window.
        amount_tolerance: Maximum difference in amounts (dollars).
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
            if amount_diff <= amount_tolerance:
                date_diff = abs((txn_info.date - order.order_date).days)
                if date_diff <= stage1_window:
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
            if amount_diff <= amount_tolerance:
                date_diff = abs((txn_info.date - order.order_date).days)
                if date_diff <= stage2_window:
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
    unmatched_orders = find_unmatched_orders(
        orders, all_transactions, stage2_window, amount_tolerance
    )

    # Combination matching: try summing unmatched transactions
    combo_matches = find_combo_matches(
        unmatched_txns, unmatched_orders, stage2_window, amount_tolerance
    )

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
