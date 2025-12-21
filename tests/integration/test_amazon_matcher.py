"""Integration tests for AmazonOrderMatcher.

Tests the matcher service with mock repository.
"""

from datetime import datetime

import pytest

from ynab_tui.db.database import AmazonOrderCache
from ynab_tui.services.amazon_matcher import AmazonOrderMatcher, TransactionInfo


class MockAmazonOrderRepo:
    """Mock repository for testing."""

    def __init__(self, orders: list[AmazonOrderCache] | None = None):
        self.orders = orders or []

    def get_cached_orders_by_date_range(
        self, start: datetime, end: datetime
    ) -> list[AmazonOrderCache]:
        """Return orders within date range."""
        return [o for o in self.orders if start <= o.order_date <= end]

    def get_order_items_with_prices(self, order_id: str) -> list[dict]:
        """Return items for order (not used in these tests)."""
        return []


def make_order(
    order_id: str = "order-001",
    date: datetime | None = None,
    total: float = 44.99,
    items: list[str] | None = None,
) -> AmazonOrderCache:
    """Create test order."""
    return AmazonOrderCache(
        order_id=order_id,
        order_date=date or datetime(2025, 11, 24),
        total=total,
        items=items or [],
        fetched_at=datetime.now(),
    )


def make_txn_info(
    txn_id: str = "txn-001",
    amount: float = 44.99,
    date: datetime | None = None,
) -> TransactionInfo:
    """Create test transaction info."""
    d = date or datetime(2025, 11, 24)
    return TransactionInfo(
        transaction_id=txn_id,
        amount=amount,
        date=d,
        date_str=d.strftime("%Y-%m-%d"),
        display_amount=f"-${amount:,.2f}",
    )


class TestAmazonOrderMatcher:
    """Tests for AmazonOrderMatcher service."""

    def test_init_with_defaults(self) -> None:
        """Initializes with default config values."""
        repo = MockAmazonOrderRepo()
        matcher = AmazonOrderMatcher(repo)

        assert matcher.stage1_window == 7
        assert matcher.stage2_window == 24
        assert matcher.amount_tolerance == 0.10

    def test_init_with_custom_values(self) -> None:
        """Can override window and tolerance values."""
        repo = MockAmazonOrderRepo()
        matcher = AmazonOrderMatcher(
            repo,
            stage1_window=5,
            stage2_window=30,
            amount_tolerance=0.50,
        )

        assert matcher.stage1_window == 5
        assert matcher.stage2_window == 30
        assert matcher.amount_tolerance == 0.50

    def test_normalize_transaction(self) -> None:
        """Can normalize raw transaction dict."""
        repo = MockAmazonOrderRepo()
        matcher = AmazonOrderMatcher(repo)

        raw_txn = {
            "id": "txn-123",
            "date": "2025-11-24",
            "amount": -4499,  # milliunits
            "payee_name": "Amazon",
            "approved": False,
            "is_split": False,
            "category_id": None,
            "category_name": None,
        }

        info = matcher.normalize_transaction(raw_txn)

        assert info.transaction_id == "txn-123"
        assert info.amount == 4499
        assert info.date == datetime(2025, 11, 24)
        assert info.date_str == "2025-11-24"
        assert info.approved is False

    def test_normalize_transaction_with_datetime_date(self) -> None:
        """Handles datetime date object."""
        repo = MockAmazonOrderRepo()
        matcher = AmazonOrderMatcher(repo)

        raw_txn = {
            "id": "txn-123",
            "date": datetime(2025, 11, 24),
            "amount": -4499,
        }

        info = matcher.normalize_transaction(raw_txn)
        assert info.date_str == "2025-11-24"

    def test_find_order_match_exact(self) -> None:
        """Can find exact match."""
        repo = MockAmazonOrderRepo()
        matcher = AmazonOrderMatcher(repo)

        order = make_order(total=44.99)
        txn = make_txn_info(amount=44.99)

        result = matcher.find_order_match(txn, [order], window_days=7)

        assert result is not None
        assert result.order_id == "order-001"

    def test_find_order_match_within_tolerance(self) -> None:
        """Matches within amount tolerance."""
        repo = MockAmazonOrderRepo()
        matcher = AmazonOrderMatcher(repo, amount_tolerance=0.10)

        order = make_order(total=44.99)
        txn = make_txn_info(amount=45.05)  # $0.06 difference

        result = matcher.find_order_match(txn, [order], window_days=7)

        assert result is not None

    def test_find_order_match_outside_tolerance(self) -> None:
        """No match when outside tolerance."""
        repo = MockAmazonOrderRepo()
        matcher = AmazonOrderMatcher(repo, amount_tolerance=0.10)

        order = make_order(total=44.99)
        txn = make_txn_info(amount=46.00)  # $1.01 difference

        result = matcher.find_order_match(txn, [order], window_days=7)

        assert result is None

    def test_find_order_match_excludes_ids(self) -> None:
        """Can exclude already matched orders."""
        repo = MockAmazonOrderRepo()
        matcher = AmazonOrderMatcher(repo)

        order1 = make_order("order-1", total=44.99)
        order2 = make_order("order-2", total=44.99)
        txn = make_txn_info(amount=44.99)

        result = matcher.find_order_match(
            txn, [order1, order2], window_days=7, exclude_order_ids={"order-1"}
        )

        assert result is not None
        assert result.order_id == "order-2"

    def test_match_transactions_stage1(self) -> None:
        """Stage 1 matching works."""
        repo = MockAmazonOrderRepo()
        matcher = AmazonOrderMatcher(repo, stage1_window=7, stage2_window=24)

        orders = [make_order("o1", datetime(2025, 11, 24), 44.99)]
        txns = [make_txn_info("t1", 44.99, datetime(2025, 11, 24))]

        result = matcher.match_transactions(txns, orders)

        assert len(result.stage1_matches) == 1
        assert result.stage1_matches[0][0].transaction_id == "t1"
        assert result.stage1_matches[0][1].order_id == "o1"

    def test_match_transactions_stage2(self) -> None:
        """Stage 2 catches matches outside stage1 window."""
        repo = MockAmazonOrderRepo()
        matcher = AmazonOrderMatcher(repo, stage1_window=7, stage2_window=24)

        # Order 15 days before transaction (outside 7 day window, inside 24)
        orders = [make_order("o1", datetime(2025, 11, 9), 44.99)]
        txns = [make_txn_info("t1", 44.99, datetime(2025, 11, 24))]

        result = matcher.match_transactions(txns, orders)

        assert len(result.stage1_matches) == 0
        assert len(result.stage2_matches) == 1

    def test_match_transactions_duplicate_detection(self) -> None:
        """Detects when same order matches multiple transactions."""
        repo = MockAmazonOrderRepo()
        matcher = AmazonOrderMatcher(repo, stage1_window=7)

        order = make_order("o1", datetime(2025, 11, 24), 44.99)
        txn1 = make_txn_info("t1", 44.99, datetime(2025, 11, 24))
        txn2 = make_txn_info("t2", 44.99, datetime(2025, 11, 25))

        result = matcher.match_transactions([txn1, txn2], [order])

        # Should have one match and one duplicate
        assert len(result.stage1_matches) == 1
        assert len(result.duplicate_matches) == 1

    def test_match_transactions_unmatched(self) -> None:
        """Reports unmatched transactions."""
        repo = MockAmazonOrderRepo()
        matcher = AmazonOrderMatcher(repo)

        orders = [make_order("o1", datetime(2025, 11, 24), 44.99)]
        txns = [make_txn_info("t1", 99.99, datetime(2025, 11, 24))]  # Different amount

        result = matcher.match_transactions(txns, orders)

        assert len(result.stage1_matches) == 0
        assert len(result.stage2_matches) == 0
        assert len(result.unmatched_transactions) == 1

    def test_get_orders_for_date_range(self) -> None:
        """Queries orders for transaction date range."""
        orders = [
            make_order("o1", datetime(2025, 11, 10), 10.00),
            make_order("o2", datetime(2025, 11, 24), 44.99),
            make_order("o3", datetime(2025, 12, 15), 30.00),
        ]
        repo = MockAmazonOrderRepo(orders)
        matcher = AmazonOrderMatcher(repo, stage2_window=7)

        txns = [make_txn_info("t1", 44.99, datetime(2025, 11, 24))]

        result = matcher.get_orders_for_date_range(txns)

        # Should get orders within 7-day window of Nov 24
        assert len(result) == 1
        assert result[0].order_id == "o2"

    def test_get_orders_for_date_range_empty(self) -> None:
        """Returns empty list for empty transactions."""
        repo = MockAmazonOrderRepo([make_order()])
        matcher = AmazonOrderMatcher(repo)

        result = matcher.get_orders_for_date_range([])

        assert result == []

    def test_find_unmatched_orders(self) -> None:
        """Can find orders with no matching transactions."""
        repo = MockAmazonOrderRepo()
        matcher = AmazonOrderMatcher(repo, stage2_window=7)

        orders = [
            make_order("o1", datetime(2025, 11, 24), 44.99),
            make_order("o2", datetime(2025, 11, 24), 99.99),
        ]
        txns = [make_txn_info("t1", 44.99, datetime(2025, 11, 24))]

        result = matcher._find_unmatched_orders(orders, txns)

        assert len(result) == 1
        assert result[0].order_id == "o2"

    def test_find_combo_matches(self) -> None:
        """Can find combo matches (multiple txns = one order)."""
        repo = MockAmazonOrderRepo()
        matcher = AmazonOrderMatcher(repo, stage2_window=7, amount_tolerance=0.10)

        order = make_order("o1", datetime(2025, 11, 24), 100.00)
        txn1 = make_txn_info("t1", 60.00, datetime(2025, 11, 24))
        txn2 = make_txn_info("t2", 40.00, datetime(2025, 11, 24))

        result = matcher._find_combo_matches([txn1, txn2], [order])

        assert len(result) == 1
        order_match, txn_combo = result[0]
        assert order_match.order_id == "o1"
        assert len(txn_combo) == 2


class TestMatcherWithRealDB:
    """Tests using real temp database."""

    @pytest.fixture
    def matcher_with_db(self, tmp_path) -> AmazonOrderMatcher:
        """Create matcher with real temp database."""
        from ynab_tui.db.database import Database

        db_path = tmp_path / "test.db"
        db = Database(str(db_path))

        # Add some orders
        db.cache_amazon_order("o1", datetime(2025, 11, 24), 44.99)
        db.cache_amazon_order("o2", datetime(2025, 11, 20), 99.99)

        return AmazonOrderMatcher(db, stage1_window=7, stage2_window=24)

    def test_get_orders_with_real_db(self, matcher_with_db: AmazonOrderMatcher) -> None:
        """Can get orders from real database."""
        txns = [make_txn_info("t1", 44.99, datetime(2025, 11, 24))]

        orders = matcher_with_db.get_orders_for_date_range(txns)

        assert len(orders) >= 1
        order_ids = {o.order_id for o in orders}
        assert "o1" in order_ids

    def test_full_matching_flow_with_db(self, matcher_with_db: AmazonOrderMatcher) -> None:
        """Full matching flow with real database."""
        txns = [
            make_txn_info("t1", 44.99, datetime(2025, 11, 24)),
            make_txn_info("t2", 99.99, datetime(2025, 11, 21)),
        ]

        orders = matcher_with_db.get_orders_for_date_range(txns)
        result = matcher_with_db.match_transactions(txns, orders)

        # Both should match
        total_matches = len(result.stage1_matches) + len(result.stage2_matches)
        assert total_matches == 2
