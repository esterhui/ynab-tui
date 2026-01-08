"""Tests for pure matching algorithms.

These tests verify the core matching logic without any database or I/O.
All functions tested here are pure - data in, data out.
"""

# Factory functions are defined in top-level conftest.py
import sys
from datetime import datetime
from pathlib import Path

from ynab_tui.services.amazon_matcher import (
    calculate_date_range,
    find_best_order_match,
    find_combo_matches,
    find_unmatched_orders,
    match_transactions_two_stage,
)

# Add tests/ to path for conftest import
_tests_path = str(Path(__file__).parent.parent.parent)
if _tests_path not in sys.path:
    sys.path.insert(0, _tests_path)

from conftest import make_amazon_order, make_transaction_info

# ============================================================================
# calculate_date_range tests
# ============================================================================


class TestCalculateDateRange:
    """Tests for calculate_date_range function."""

    def test_empty_transactions_returns_now(self) -> None:
        """Empty list should return current time for both start and end."""
        start, end = calculate_date_range([], window_days=7)
        now = datetime.now()
        # Should be within a second of now
        assert abs((start - now).total_seconds()) < 1
        assert abs((end - now).total_seconds()) < 1

    def test_single_transaction_extends_window(self) -> None:
        """Single transaction should extend window_days in each direction."""
        txn = make_transaction_info(date=datetime(2025, 11, 15))
        start, end = calculate_date_range([txn], window_days=7)

        assert start == datetime(2025, 11, 8)  # 15 - 7
        assert end == datetime(2025, 11, 22)  # 15 + 7

    def test_multiple_transactions_uses_min_max(self) -> None:
        """Multiple transactions should use min/max dates."""
        txns = [
            make_transaction_info(transaction_id="t1", date=datetime(2025, 11, 10)),
            make_transaction_info(transaction_id="t2", date=datetime(2025, 11, 20)),
            make_transaction_info(transaction_id="t3", date=datetime(2025, 11, 15)),
        ]
        start, end = calculate_date_range(txns, window_days=7)

        assert start == datetime(2025, 11, 3)  # 10 - 7
        assert end == datetime(2025, 11, 27)  # 20 + 7

    def test_window_days_parameter(self) -> None:
        """Different window_days values should produce different ranges."""
        txn = make_transaction_info(date=datetime(2025, 11, 15))

        start_7, end_7 = calculate_date_range([txn], window_days=7)
        start_24, end_24 = calculate_date_range([txn], window_days=24)

        assert start_7 == datetime(2025, 11, 8)
        assert start_24 == datetime(2025, 10, 22)
        assert end_7 == datetime(2025, 11, 22)
        assert end_24 == datetime(2025, 12, 9)


# ============================================================================
# find_best_order_match tests
# ============================================================================


class TestFindBestOrderMatch:
    """Tests for find_best_order_match function."""

    def test_exact_amount_match(self) -> None:
        """Exact amount should match."""
        txn = make_transaction_info(amount=44.99, date=datetime(2025, 11, 27))
        orders = [make_amazon_order(total=44.99, order_date=datetime(2025, 11, 24))]

        result = find_best_order_match(txn, orders, window_days=7, amount_tolerance=0.10)

        assert result is not None
        assert result.total == 44.99

    def test_amount_within_tolerance(self) -> None:
        """Amount within tolerance should match."""
        txn = make_transaction_info(amount=45.05, date=datetime(2025, 11, 27))
        orders = [make_amazon_order(total=44.99, order_date=datetime(2025, 11, 24))]

        result = find_best_order_match(txn, orders, window_days=7, amount_tolerance=0.10)

        assert result is not None
        assert result.total == 44.99

    def test_amount_outside_tolerance(self) -> None:
        """Amount outside tolerance should not match."""
        txn = make_transaction_info(amount=45.20, date=datetime(2025, 11, 27))
        orders = [make_amazon_order(total=44.99, order_date=datetime(2025, 11, 24))]

        result = find_best_order_match(txn, orders, window_days=7, amount_tolerance=0.10)

        assert result is None

    def test_date_within_window(self) -> None:
        """Date within window should match."""
        txn = make_transaction_info(amount=44.99, date=datetime(2025, 11, 27))
        orders = [make_amazon_order(total=44.99, order_date=datetime(2025, 11, 21))]

        result = find_best_order_match(txn, orders, window_days=7, amount_tolerance=0.10)

        assert result is not None

    def test_date_outside_window(self) -> None:
        """Date outside window should not match."""
        txn = make_transaction_info(amount=44.99, date=datetime(2025, 11, 27))
        orders = [make_amazon_order(total=44.99, order_date=datetime(2025, 11, 15))]

        result = find_best_order_match(txn, orders, window_days=7, amount_tolerance=0.10)

        assert result is None

    def test_best_match_by_date_difference(self) -> None:
        """Should return order with smallest date difference."""
        txn = make_transaction_info(amount=44.99, date=datetime(2025, 11, 27))
        orders = [
            make_amazon_order(order_id="far", total=44.99, order_date=datetime(2025, 11, 21)),
            make_amazon_order(order_id="close", total=44.99, order_date=datetime(2025, 11, 25)),
        ]

        result = find_best_order_match(txn, orders, window_days=7, amount_tolerance=0.10)

        assert result is not None
        assert result.order_id == "close"

    def test_exclude_order_ids(self) -> None:
        """Should skip orders in exclude list."""
        txn = make_transaction_info(amount=44.99, date=datetime(2025, 11, 27))
        orders = [
            make_amazon_order(order_id="excluded", total=44.99, order_date=datetime(2025, 11, 25)),
            make_amazon_order(order_id="available", total=44.99, order_date=datetime(2025, 11, 24)),
        ]

        result = find_best_order_match(
            txn, orders, window_days=7, amount_tolerance=0.10, exclude_order_ids={"excluded"}
        )

        assert result is not None
        assert result.order_id == "available"

    def test_empty_orders_returns_none(self) -> None:
        """Empty orders list should return None."""
        txn = make_transaction_info()

        result = find_best_order_match(txn, [], window_days=7, amount_tolerance=0.10)

        assert result is None


# ============================================================================
# find_unmatched_orders tests
# ============================================================================


class TestFindUnmatchedOrders:
    """Tests for find_unmatched_orders function."""

    def test_all_orders_matched(self) -> None:
        """All orders with matching transactions should return empty list."""
        txns = [make_transaction_info(amount=44.99, date=datetime(2025, 11, 27))]
        orders = [make_amazon_order(total=44.99, order_date=datetime(2025, 11, 24))]

        result = find_unmatched_orders(orders, txns, window_days=24, amount_tolerance=0.10)

        assert result == []

    def test_unmatched_by_amount(self) -> None:
        """Order with no matching amount should be unmatched."""
        txns = [make_transaction_info(amount=44.99, date=datetime(2025, 11, 27))]
        orders = [make_amazon_order(total=100.00, order_date=datetime(2025, 11, 24))]

        result = find_unmatched_orders(orders, txns, window_days=24, amount_tolerance=0.10)

        assert len(result) == 1
        assert result[0].total == 100.00

    def test_unmatched_by_date(self) -> None:
        """Order outside date window should be unmatched."""
        txns = [make_transaction_info(amount=44.99, date=datetime(2025, 11, 27))]
        orders = [make_amazon_order(total=44.99, order_date=datetime(2025, 10, 1))]

        result = find_unmatched_orders(orders, txns, window_days=24, amount_tolerance=0.10)

        assert len(result) == 1

    def test_zero_total_orders_skipped(self) -> None:
        """Orders with zero total should be skipped."""
        txns = [make_transaction_info(amount=44.99, date=datetime(2025, 11, 27))]
        orders = [make_amazon_order(total=0, order_date=datetime(2025, 11, 24))]

        result = find_unmatched_orders(orders, txns, window_days=24, amount_tolerance=0.10)

        assert result == []

    def test_mixed_matched_and_unmatched(self) -> None:
        """Should return only unmatched orders."""
        txns = [
            make_transaction_info(transaction_id="t1", amount=44.99, date=datetime(2025, 11, 27)),
        ]
        orders = [
            make_amazon_order(order_id="matched", total=44.99, order_date=datetime(2025, 11, 24)),
            make_amazon_order(
                order_id="unmatched", total=100.00, order_date=datetime(2025, 11, 24)
            ),
        ]

        result = find_unmatched_orders(orders, txns, window_days=24, amount_tolerance=0.10)

        assert len(result) == 1
        assert result[0].order_id == "unmatched"


# ============================================================================
# find_combo_matches tests
# ============================================================================


class TestFindComboMatches:
    """Tests for find_combo_matches function."""

    def test_two_transactions_sum_to_order(self) -> None:
        """Two transactions summing to order total should match."""
        txns = [
            make_transaction_info(transaction_id="t1", amount=20.00, date=datetime(2025, 11, 27)),
            make_transaction_info(transaction_id="t2", amount=30.00, date=datetime(2025, 11, 27)),
        ]
        orders = [make_amazon_order(total=50.00, order_date=datetime(2025, 11, 24))]

        result = find_combo_matches(txns, orders, window_days=24, amount_tolerance=0.10)

        assert len(result) == 1
        order, combo_txns = result[0]
        assert order.total == 50.00
        assert len(combo_txns) == 2

    def test_three_transactions_combo(self) -> None:
        """Three transactions summing to order total should match."""
        txns = [
            make_transaction_info(transaction_id="t1", amount=10.00, date=datetime(2025, 11, 27)),
            make_transaction_info(transaction_id="t2", amount=20.00, date=datetime(2025, 11, 27)),
            make_transaction_info(transaction_id="t3", amount=20.00, date=datetime(2025, 11, 27)),
        ]
        orders = [make_amazon_order(total=50.00, order_date=datetime(2025, 11, 24))]

        result = find_combo_matches(txns, orders, window_days=24, amount_tolerance=0.10)

        assert len(result) == 1
        _, combo_txns = result[0]
        assert len(combo_txns) == 3

    def test_no_combo_when_sum_doesnt_match(self) -> None:
        """No combo match when transactions don't sum to order."""
        txns = [
            make_transaction_info(transaction_id="t1", amount=10.00, date=datetime(2025, 11, 27)),
            make_transaction_info(transaction_id="t2", amount=15.00, date=datetime(2025, 11, 27)),
        ]
        orders = [make_amazon_order(total=50.00, order_date=datetime(2025, 11, 24))]

        result = find_combo_matches(txns, orders, window_days=24, amount_tolerance=0.10)

        assert result == []

    def test_transactions_must_be_within_window(self) -> None:
        """Transactions outside date window should not combo match."""
        txns = [
            make_transaction_info(transaction_id="t1", amount=25.00, date=datetime(2025, 11, 27)),
            make_transaction_info(
                transaction_id="t2", amount=25.00, date=datetime(2025, 10, 1)
            ),  # Far away
        ]
        orders = [make_amazon_order(total=50.00, order_date=datetime(2025, 11, 24))]

        result = find_combo_matches(txns, orders, window_days=7, amount_tolerance=0.10)

        assert result == []

    def test_empty_transactions_returns_empty(self) -> None:
        """Empty transactions list should return empty."""
        orders = [make_amazon_order(total=50.00)]

        result = find_combo_matches([], orders, window_days=24, amount_tolerance=0.10)

        assert result == []

    def test_empty_orders_returns_empty(self) -> None:
        """Empty orders list should return empty."""
        txns = [make_transaction_info()]

        result = find_combo_matches(txns, [], window_days=24, amount_tolerance=0.10)

        assert result == []

    def test_single_transaction_not_combo(self) -> None:
        """Single nearby transaction should not create combo (needs 2+)."""
        txns = [make_transaction_info(amount=50.00, date=datetime(2025, 11, 27))]
        orders = [make_amazon_order(total=50.00, order_date=datetime(2025, 11, 24))]

        result = find_combo_matches(txns, orders, window_days=24, amount_tolerance=0.10)

        # Combo matching requires 2+ transactions
        assert result == []

    def test_transaction_not_reused_across_combos(self) -> None:
        """A transaction used in one combo should not be used in another.

        Real-world bug scenario:
        - Combo 1: $36.08 + $46.79 = $82.87 (matches toilet supplies order, Jan 3)
        - Combo 2: $36.08 + $24.05 + $11.87 = $72.00 ≈ $71.99 (should NOT match)

        The $36.08 transaction should only be used in the first combo.
        Without this fix, $11.87 incorrectly shows items from the mattress topper order.

        IMPORTANT: Orders are passed in DESCENDING date order (as returned by DB)
        to verify the algorithm correctly sorts them and processes oldest first.
        """
        txns = [
            make_transaction_info(transaction_id="t1", amount=36.08, date=datetime(2026, 1, 4)),
            make_transaction_info(transaction_id="t2", amount=46.79, date=datetime(2026, 1, 5)),
            make_transaction_info(transaction_id="t3", amount=11.87, date=datetime(2026, 1, 6)),
            make_transaction_info(transaction_id="t4", amount=24.05, date=datetime(2025, 12, 22)),
        ]
        # Orders in DESCENDING date order (as database returns them)
        # This tests that the algorithm sorts by date ascending before processing
        orders = [
            make_amazon_order(
                order_id="mattress-topper",
                total=71.99,
                order_date=datetime(2026, 1, 6),  # Newer order first (as DB returns)
                items=["Mattress Topper"],
            ),
            make_amazon_order(
                order_id="toilet-supplies",
                total=82.87,
                order_date=datetime(2026, 1, 3),  # Older order second
                items=["Toilet Seat"],
            ),
        ]

        result = find_combo_matches(txns, orders, window_days=24, amount_tolerance=0.10)

        # Should only find ONE combo (the $82.87 one from Jan 3)
        # The $71.99 combo should NOT be found because $36.08 is already used
        # by the older order (algorithm processes oldest first)
        assert len(result) == 1
        order, combo_txns = result[0]
        assert order.order_id == "toilet-supplies"

        # The $11.87 transaction should NOT be in any combo
        all_combo_txn_ids = {t.transaction_id for _, txns in result for t in txns}
        assert "t3" not in all_combo_txn_ids  # $11.87 should not be matched


# ============================================================================
# match_transactions_two_stage tests
# ============================================================================


class TestMatchTransactionsTwoStage:
    """Tests for match_transactions_two_stage function."""

    def test_stage1_matches_within_strict_window(self) -> None:
        """Transactions matching in stage 1 window should be stage1 matches."""
        txns = [make_transaction_info(amount=44.99, date=datetime(2025, 11, 27))]
        orders = [make_amazon_order(total=44.99, order_date=datetime(2025, 11, 24))]  # 3 days

        result = match_transactions_two_stage(
            txns, orders, stage1_window=7, stage2_window=24, amount_tolerance=0.10
        )

        assert len(result.stage1_matches) == 1
        assert len(result.stage2_matches) == 0

    def test_stage2_matches_outside_strict_window(self) -> None:
        """Transactions matching only in extended window should be stage2 matches."""
        txns = [make_transaction_info(amount=44.99, date=datetime(2025, 11, 27))]
        orders = [make_amazon_order(total=44.99, order_date=datetime(2025, 11, 10))]  # 17 days

        result = match_transactions_two_stage(
            txns, orders, stage1_window=7, stage2_window=24, amount_tolerance=0.10
        )

        assert len(result.stage1_matches) == 0
        assert len(result.stage2_matches) == 1

    def test_duplicate_matches_detected(self) -> None:
        """Multiple transactions matching same order should be duplicates."""
        txns = [
            make_transaction_info(transaction_id="t1", amount=44.99, date=datetime(2025, 11, 27)),
            make_transaction_info(transaction_id="t2", amount=44.99, date=datetime(2025, 11, 26)),
        ]
        orders = [make_amazon_order(total=44.99, order_date=datetime(2025, 11, 24))]

        result = match_transactions_two_stage(
            txns, orders, stage1_window=7, stage2_window=24, amount_tolerance=0.10
        )

        assert len(result.stage1_matches) == 1
        assert len(result.duplicate_matches) == 1

    def test_unmatched_transactions(self) -> None:
        """Transactions with no matching orders should be unmatched."""
        txns = [
            make_transaction_info(
                transaction_id="matched", amount=44.99, date=datetime(2025, 11, 27)
            ),
            make_transaction_info(
                transaction_id="unmatched", amount=100.00, date=datetime(2025, 11, 27)
            ),
        ]
        orders = [make_amazon_order(total=44.99, order_date=datetime(2025, 11, 24))]

        result = match_transactions_two_stage(
            txns, orders, stage1_window=7, stage2_window=24, amount_tolerance=0.10
        )

        assert len(result.stage1_matches) == 1
        assert len(result.unmatched_transactions) == 1
        assert result.unmatched_transactions[0].transaction_id == "unmatched"

    def test_unmatched_orders(self) -> None:
        """Orders with no matching transactions should be unmatched."""
        txns = [make_transaction_info(amount=44.99, date=datetime(2025, 11, 27))]
        orders = [
            make_amazon_order(order_id="matched", total=44.99, order_date=datetime(2025, 11, 24)),
            make_amazon_order(
                order_id="unmatched", total=100.00, order_date=datetime(2025, 11, 24)
            ),
        ]

        result = match_transactions_two_stage(
            txns, orders, stage1_window=7, stage2_window=24, amount_tolerance=0.10
        )

        assert len(result.unmatched_orders) == 1
        assert result.unmatched_orders[0].order_id == "unmatched"

    def test_combo_matches_found(self) -> None:
        """Combo matches should be detected from unmatched items."""
        txns = [
            make_transaction_info(
                transaction_id="combo1", amount=20.00, date=datetime(2025, 11, 27)
            ),
            make_transaction_info(
                transaction_id="combo2", amount=30.00, date=datetime(2025, 11, 27)
            ),
        ]
        orders = [make_amazon_order(total=50.00, order_date=datetime(2025, 11, 24))]

        result = match_transactions_two_stage(
            txns, orders, stage1_window=7, stage2_window=24, amount_tolerance=0.10
        )

        assert len(result.combo_matches) == 1

    def test_all_matches_property(self) -> None:
        """all_matches should combine stage1 and stage2."""
        txns = [
            make_transaction_info(transaction_id="t1", amount=44.99, date=datetime(2025, 11, 27)),
            make_transaction_info(transaction_id="t2", amount=29.99, date=datetime(2025, 11, 27)),
        ]
        orders = [
            make_amazon_order(
                order_id="o1", total=44.99, order_date=datetime(2025, 11, 24)
            ),  # stage1
            make_amazon_order(
                order_id="o2", total=29.99, order_date=datetime(2025, 11, 10)
            ),  # stage2
        ]

        result = match_transactions_two_stage(
            txns, orders, stage1_window=7, stage2_window=24, amount_tolerance=0.10
        )

        assert len(result.all_matches) == 2

    def test_total_matched_property(self) -> None:
        """total_matched should count stage1 + stage2."""
        txns = [
            make_transaction_info(transaction_id="t1", amount=44.99, date=datetime(2025, 11, 27)),
            make_transaction_info(transaction_id="t2", amount=29.99, date=datetime(2025, 11, 27)),
        ]
        orders = [
            make_amazon_order(order_id="o1", total=44.99, order_date=datetime(2025, 11, 24)),
            make_amazon_order(order_id="o2", total=29.99, order_date=datetime(2025, 11, 10)),
        ]

        result = match_transactions_two_stage(
            txns, orders, stage1_window=7, stage2_window=24, amount_tolerance=0.10
        )

        assert result.total_matched == 2

    def test_best_match_wins_when_multiple_options(self) -> None:
        """Exact amount match should beat near-tolerance match."""
        txn = make_transaction_info(amount=44.99, date=datetime(2025, 11, 27))
        orders = [
            make_amazon_order(order_id="exact", total=44.99, order_date=datetime(2025, 11, 25)),
            make_amazon_order(order_id="close", total=45.05, order_date=datetime(2025, 11, 25)),
        ]

        result = match_transactions_two_stage(
            [txn], orders, stage1_window=7, stage2_window=24, amount_tolerance=0.10
        )

        assert len(result.stage1_matches) == 1
        _, matched_order = result.stage1_matches[0]
        assert matched_order.order_id == "exact"

    def test_empty_transactions_returns_empty_result(self) -> None:
        """Empty transactions should return empty result."""
        orders = [make_amazon_order()]

        result = match_transactions_two_stage(
            [], orders, stage1_window=7, stage2_window=24, amount_tolerance=0.10
        )

        assert len(result.stage1_matches) == 0
        assert len(result.stage2_matches) == 0
        assert len(result.unmatched_transactions) == 0

    def test_empty_orders_returns_all_unmatched(self) -> None:
        """Empty orders should result in all transactions unmatched."""
        txns = [make_transaction_info(), make_transaction_info(transaction_id="t2")]

        result = match_transactions_two_stage(
            txns, [], stage1_window=7, stage2_window=24, amount_tolerance=0.10
        )

        assert len(result.stage1_matches) == 0
        assert len(result.stage2_matches) == 0
        assert len(result.unmatched_transactions) == 2
