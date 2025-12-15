"""Tests for AmazonOrderMatcher service."""

from datetime import datetime

import pytest

from src.db.database import AmazonOrderCache
from src.services.amazon_matcher import AmazonMatchResult, AmazonOrderMatcher, TransactionInfo


class TestTransactionInfo:
    """Tests for TransactionInfo dataclass."""

    def test_basic_creation(self):
        """Test creating a TransactionInfo object."""
        txn = TransactionInfo(
            transaction_id="txn-123",
            amount=44.99,
            date=datetime(2025, 11, 27),
            date_str="2025-11-27",
            display_amount="-$44.99",
        )
        assert txn.transaction_id == "txn-123"
        assert txn.amount == 44.99
        assert txn.date_str == "2025-11-27"
        assert txn.display_amount == "-$44.99"
        assert txn.is_split is False
        assert txn.category_id is None
        assert txn.approved is False

    def test_with_all_fields(self):
        """Test TransactionInfo with all fields populated."""
        txn = TransactionInfo(
            transaction_id="txn-456",
            amount=100.0,
            date=datetime(2025, 11, 15),
            date_str="2025-11-15",
            display_amount="-$100.00",
            is_split=True,
            category_id="cat-123",
            category_name="Groceries",
            approved=True,
            raw_data={"id": "txn-456", "memo": "Test"},
        )
        assert txn.is_split is True
        assert txn.category_id == "cat-123"
        assert txn.category_name == "Groceries"
        assert txn.approved is True
        assert txn.raw_data["memo"] == "Test"


class TestAmazonMatchResult:
    """Tests for AmazonMatchResult dataclass."""

    def test_all_matches_property(self):
        """Test that all_matches combines stage1 and stage2."""
        txn1 = TransactionInfo(
            transaction_id="t1",
            amount=10.0,
            date=datetime(2025, 1, 1),
            date_str="2025-01-01",
            display_amount="-$10.00",
        )
        txn2 = TransactionInfo(
            transaction_id="t2",
            amount=20.0,
            date=datetime(2025, 1, 2),
            date_str="2025-01-02",
            display_amount="-$20.00",
        )
        order1 = AmazonOrderCache(
            order_id="o1",
            order_date=datetime(2025, 1, 1),
            total=10.0,
            items=["Item 1"],
            fetched_at=datetime.now(),
        )
        order2 = AmazonOrderCache(
            order_id="o2",
            order_date=datetime(2025, 1, 1),
            total=20.0,
            items=["Item 2"],
            fetched_at=datetime.now(),
        )

        result = AmazonMatchResult(
            stage1_matches=[(txn1, order1)],
            stage2_matches=[(txn2, order2)],
            duplicate_matches=[],
            combo_matches=[],
            unmatched_transactions=[],
            unmatched_orders=[],
        )

        assert len(result.all_matches) == 2
        assert result.total_matched == 2

    def test_empty_result(self):
        """Test empty result."""
        result = AmazonMatchResult(
            stage1_matches=[],
            stage2_matches=[],
            duplicate_matches=[],
            combo_matches=[],
            unmatched_transactions=[],
            unmatched_orders=[],
        )
        assert result.all_matches == []
        assert result.total_matched == 0


class TestAmazonOrderMatcher:
    """Tests for AmazonOrderMatcher service."""

    @pytest.fixture
    def sample_orders(self):
        """Create sample orders for testing."""
        now = datetime.now()
        return [
            AmazonOrderCache(
                order_id="order-001",
                order_date=datetime(2025, 11, 24),
                total=44.99,
                items=["Huggies Diapers"],
                fetched_at=now,
            ),
            AmazonOrderCache(
                order_id="order-002",
                order_date=datetime(2025, 11, 21),
                total=217.66,
                items=["Inglesina Stroller"],
                fetched_at=now,
            ),
            AmazonOrderCache(
                order_id="order-003",
                order_date=datetime(2025, 11, 3),
                total=33.36,
                items=["BioFe Iron Drops"],
                fetched_at=now,
            ),
            AmazonOrderCache(
                order_id="order-004",
                order_date=datetime(2025, 11, 21),
                total=59.48,
                items=["KYOCERA Knife Set"],
                fetched_at=now,
            ),
        ]

    def test_normalize_transaction(self, amazon_order_matcher):
        """Test normalizing a raw transaction dict."""
        raw_txn = {
            "id": "txn-123",
            "date": "2025-11-27",
            "amount": -44.99,
            "payee_name": "Amazon",
            "category_id": "cat-001",
            "category_name": "Baby Gear",
            "approved": True,
            "is_split": False,
        }

        txn_info = amazon_order_matcher.normalize_transaction(raw_txn)

        assert txn_info.transaction_id == "txn-123"
        assert txn_info.amount == 44.99  # Absolute value
        assert txn_info.date_str == "2025-11-27"
        assert txn_info.display_amount == "-$44.99"
        assert txn_info.category_id == "cat-001"
        assert txn_info.category_name == "Baby Gear"
        assert txn_info.approved is True
        assert txn_info.raw_data == raw_txn

    def test_normalize_transaction_positive_amount(self, amazon_order_matcher):
        """Test normalizing a positive amount (refund)."""
        raw_txn = {
            "id": "txn-refund",
            "date": "2025-11-15",
            "amount": 50.0,
        }

        txn_info = amazon_order_matcher.normalize_transaction(raw_txn)

        assert txn_info.amount == 50.0
        assert txn_info.display_amount == "$50.00"

    def test_normalize_transaction_datetime_date(self, amazon_order_matcher):
        """Test normalizing when date is already datetime."""
        raw_txn = {
            "id": "txn-dt",
            "date": datetime(2025, 11, 20),
            "amount": -25.0,
        }

        txn_info = amazon_order_matcher.normalize_transaction(raw_txn)

        assert txn_info.date_str == "2025-11-20"
        assert txn_info.date == datetime(2025, 11, 20)

    def test_find_order_match_exact(self, amazon_order_matcher, sample_orders):
        """Test finding an exact price match within window."""
        txn = TransactionInfo(
            transaction_id="t1",
            amount=44.99,
            date=datetime(2025, 11, 27),
            date_str="2025-11-27",
            display_amount="-$44.99",
        )

        match = amazon_order_matcher.find_order_match(txn, sample_orders, window_days=7)

        assert match is not None
        assert match.order_id == "order-001"
        assert match.total == 44.99

    def test_find_order_match_within_tolerance(self, amazon_order_matcher, sample_orders):
        """Test finding a match within amount tolerance."""
        txn = TransactionInfo(
            transaction_id="t1",
            amount=45.05,  # 0.06 off from 44.99
            date=datetime(2025, 11, 27),
            date_str="2025-11-27",
            display_amount="-$45.05",
        )

        match = amazon_order_matcher.find_order_match(txn, sample_orders, window_days=7)

        assert match is not None
        assert match.order_id == "order-001"

    def test_find_order_match_outside_tolerance(self, amazon_order_matcher, sample_orders):
        """Test no match when amount outside tolerance."""
        txn = TransactionInfo(
            transaction_id="t1",
            amount=45.15,  # 0.16 off, outside $0.10 tolerance
            date=datetime(2025, 11, 27),
            date_str="2025-11-27",
            display_amount="-$45.15",
        )

        match = amazon_order_matcher.find_order_match(txn, sample_orders, window_days=7)

        assert match is None

    def test_find_order_match_outside_window(self, amazon_order_matcher, sample_orders):
        """Test no match when outside date window."""
        txn = TransactionInfo(
            transaction_id="t1",
            amount=33.36,  # Matches order-003
            date=datetime(2025, 11, 26),
            date_str="2025-11-26",
            display_amount="-$33.36",
        )

        # 23 days apart - outside 7-day window
        match = amazon_order_matcher.find_order_match(txn, sample_orders, window_days=7)
        assert match is None

        # But within 24-day window
        match = amazon_order_matcher.find_order_match(txn, sample_orders, window_days=24)
        assert match is not None
        assert match.order_id == "order-003"

    def test_find_order_match_best_date(self, amazon_order_matcher):
        """Test selecting the order with closest date when multiple match."""
        now = datetime.now()
        orders = [
            AmazonOrderCache(
                order_id="far",
                order_date=datetime(2025, 11, 10),
                total=50.0,
                items=["Item A"],
                fetched_at=now,
            ),
            AmazonOrderCache(
                order_id="close",
                order_date=datetime(2025, 11, 18),
                total=50.0,
                items=["Item B"],
                fetched_at=now,
            ),
        ]

        txn = TransactionInfo(
            transaction_id="t1",
            amount=50.0,
            date=datetime(2025, 11, 20),
            date_str="2025-11-20",
            display_amount="-$50.00",
        )

        match = amazon_order_matcher.find_order_match(txn, orders, window_days=14)

        assert match.order_id == "close"  # 2 days vs 10 days

    def test_find_order_match_with_exclusion(self, amazon_order_matcher, sample_orders):
        """Test excluding already-matched orders."""
        txn = TransactionInfo(
            transaction_id="t1",
            amount=44.99,
            date=datetime(2025, 11, 27),
            date_str="2025-11-27",
            display_amount="-$44.99",
        )

        # Exclude order-001
        match = amazon_order_matcher.find_order_match(
            txn, sample_orders, window_days=7, exclude_order_ids={"order-001"}
        )

        assert match is None

    def test_match_transactions_two_stage(self, amazon_order_matcher, sample_orders):
        """Test two-stage matching."""
        txns = [
            # Stage 1 match (3 days apart)
            TransactionInfo(
                transaction_id="t1",
                amount=44.99,
                date=datetime(2025, 11, 27),
                date_str="2025-11-27",
                display_amount="-$44.99",
            ),
            # Stage 2 match (23 days apart)
            TransactionInfo(
                transaction_id="t2",
                amount=33.36,
                date=datetime(2025, 11, 26),
                date_str="2025-11-26",
                display_amount="-$33.36",
            ),
        ]

        result = amazon_order_matcher.match_transactions(txns, sample_orders)

        assert len(result.stage1_matches) == 1
        assert result.stage1_matches[0][0].transaction_id == "t1"
        assert result.stage1_matches[0][1].order_id == "order-001"

        assert len(result.stage2_matches) == 1
        assert result.stage2_matches[0][0].transaction_id == "t2"
        assert result.stage2_matches[0][1].order_id == "order-003"

    def test_match_transactions_duplicate_detection(self, amazon_order_matcher):
        """Test detecting duplicate matches."""
        now = datetime.now()
        orders = [
            AmazonOrderCache(
                order_id="single-order",
                order_date=datetime(2025, 11, 20),
                total=50.0,
                items=["Single Item"],
                fetched_at=now,
            ),
        ]

        # Two transactions with same amount
        txns = [
            TransactionInfo(
                transaction_id="t1",
                amount=50.0,
                date=datetime(2025, 11, 22),
                date_str="2025-11-22",
                display_amount="-$50.00",
            ),
            TransactionInfo(
                transaction_id="t2",
                amount=50.0,
                date=datetime(2025, 11, 23),
                date_str="2025-11-23",
                display_amount="-$50.00",
            ),
        ]

        result = amazon_order_matcher.match_transactions(txns, orders)

        # First one gets matched
        assert len(result.stage1_matches) == 1
        assert result.stage1_matches[0][0].transaction_id == "t1"

        # Second is flagged as duplicate
        assert len(result.duplicate_matches) == 1
        assert result.duplicate_matches[0][0].transaction_id == "t2"
        assert result.duplicate_matches[0][1].order_id == "single-order"

    def test_exact_match_priority_over_fuzzy(self, amazon_order_matcher):
        """Test that exact amount matches are prioritized over fuzzy matches.

        When multiple transactions match the same order within tolerance,
        the exact match should win, regardless of transaction date order.
        """
        now = datetime.now()
        orders = [
            AmazonOrderCache(
                order_id="order-33",
                order_date=datetime(2025, 11, 21),
                total=33.33,
                items=["Green Toys Recycling Truck"],
                fetched_at=now,
            ),
        ]

        # Transaction order: fuzzy match first (by date), then exact match
        # The algorithm should prioritize exact match despite date order
        txns = [
            TransactionInfo(
                transaction_id="txn-fuzzy",
                amount=33.36,  # 3 cents off
                date=datetime(2025, 11, 26),
                date_str="2025-11-26",
                display_amount="-$33.36",
            ),
            TransactionInfo(
                transaction_id="txn-exact",
                amount=33.33,  # Exact match
                date=datetime(2025, 11, 23),
                date_str="2025-11-23",
                display_amount="-$33.33",
            ),
        ]

        result = amazon_order_matcher.match_transactions(txns, orders)

        # Exact match should win
        assert len(result.stage1_matches) == 1
        assert result.stage1_matches[0][0].transaction_id == "txn-exact"
        assert result.stage1_matches[0][1].order_id == "order-33"

        # Fuzzy match should be flagged as duplicate
        assert len(result.duplicate_matches) == 1
        assert result.duplicate_matches[0][0].transaction_id == "txn-fuzzy"

    def test_match_transactions_combo_match(self, amazon_order_matcher):
        """Test combination matching (split shipments)."""
        now = datetime.now()
        orders = [
            AmazonOrderCache(
                order_id="combo-order",
                order_date=datetime(2025, 11, 15),
                total=100.0,
                items=["Item A", "Item B"],
                fetched_at=now,
            ),
        ]

        # Two transactions that sum to order total
        txns = [
            TransactionInfo(
                transaction_id="t1",
                amount=60.0,
                date=datetime(2025, 11, 18),
                date_str="2025-11-18",
                display_amount="-$60.00",
            ),
            TransactionInfo(
                transaction_id="t2",
                amount=40.0,
                date=datetime(2025, 11, 19),
                date_str="2025-11-19",
                display_amount="-$40.00",
            ),
        ]

        result = amazon_order_matcher.match_transactions(txns, orders)

        assert len(result.combo_matches) == 1
        order, combo_txns = result.combo_matches[0]
        assert order.order_id == "combo-order"
        assert len(combo_txns) == 2
        assert sum(t.amount for t in combo_txns) == 100.0

    def test_match_transactions_unmatched(self, amazon_order_matcher, sample_orders):
        """Test identifying unmatched transactions and orders."""
        txns = [
            TransactionInfo(
                transaction_id="no-match",
                amount=999.99,  # No matching order
                date=datetime(2025, 11, 20),
                date_str="2025-11-20",
                display_amount="-$999.99",
            ),
        ]

        result = amazon_order_matcher.match_transactions(txns, sample_orders)

        assert len(result.unmatched_transactions) == 1
        assert result.unmatched_transactions[0].transaction_id == "no-match"

        # All orders should be unmatched since no transactions match them
        assert len(result.unmatched_orders) == len(sample_orders)

    def test_custom_windows(self, database):
        """Test matcher with custom window sizes."""
        custom_matcher = AmazonOrderMatcher(
            database, stage1_window=3, stage2_window=10, amount_tolerance=0.05
        )

        assert custom_matcher.stage1_window == 3
        assert custom_matcher.stage2_window == 10
        assert custom_matcher.amount_tolerance == 0.05


class TestAmazonOrderMatcherWithMockData:
    """Tests using realistic mock data patterns."""

    @pytest.fixture
    def mock_orders(self):
        """Orders matching patterns from mock_data/orders.csv."""
        now = datetime.now()
        return [
            AmazonOrderCache(
                order_id="114-3053829-2667440",
                order_date=datetime(2025, 11, 24),
                total=44.99,
                items=["Huggies Size 4 Diapers, Little Snugglers Baby Diapers"],
                fetched_at=now,
            ),
            AmazonOrderCache(
                order_id="112-9352464-5661005",
                order_date=datetime(2025, 11, 21),
                total=217.66,
                items=["Inglesina Quid 2 Stroller - Alpaca Beige"],
                fetched_at=now,
            ),
            AmazonOrderCache(
                order_id="112-6023589-9314641",
                order_date=datetime(2025, 11, 3),
                total=33.36,
                items=["BioFe Pure Iron Drops, Unflavored, for Infants"],
                fetched_at=now,
            ),
            AmazonOrderCache(
                order_id="114-4106648-0573835",
                order_date=datetime(2025, 11, 21),
                total=59.48,
                items=["KYOCERA Revolution 2-Piece Ceramic Knife Set"],
                fetched_at=now,
            ),
        ]

    @pytest.fixture
    def mock_transactions(self):
        """Transactions matching patterns from mock_data/transactions.csv."""
        return [
            TransactionInfo(
                transaction_id="5c58c34a-f483-4539-91ef-2cfd6b076381",
                amount=44.99,
                date=datetime(2025, 11, 27),
                date_str="2025-11-27",
                display_amount="-$44.99",
                category_id="03b5e7b1-3485-41d2-98dd-34d9f4ffad33",
                category_name="Reimburse",
            ),
            TransactionInfo(
                transaction_id="104d8349-b602-4f7d-b1ad-c704aad0871f",
                amount=33.36,
                date=datetime(2025, 11, 26),
                date_str="2025-11-26",
                display_amount="-$33.36",
                category_id="03b5e7b1-3485-41d2-98dd-34d9f4ffad33",
                category_name="Reimburse",
            ),
            TransactionInfo(
                transaction_id="8ed61813-9fb9-41c7-94f4-b22acd74f02a",
                amount=217.66,
                date=datetime(2025, 11, 23),
                date_str="2025-11-23",
                display_amount="-$217.66",
                category_id="03b5e7b1-3485-41d2-98dd-34d9f4ffad33",
                category_name="Reimburse",
            ),
            TransactionInfo(
                transaction_id="c8755c02-8c36-4158-917b-6120dacf6b08",
                amount=59.48,
                date=datetime(2025, 11, 23),
                date_str="2025-11-23",
                display_amount="-$59.48",
                category_id="03b5e7b1-3485-41d2-98dd-34d9f4ffad33",
                category_name="Reimburse",
            ),
        ]

    def test_mock_data_stage1_matches(self, amazon_order_matcher, mock_transactions, mock_orders):
        """Test that mock data produces expected Stage 1 matches."""
        result = amazon_order_matcher.match_transactions(mock_transactions, mock_orders)

        # Stage 1 (7-day window): $44.99 (3 days), $217.66 (2 days), $59.48 (2 days)
        assert len(result.stage1_matches) == 3

        stage1_order_ids = {m[1].order_id for m in result.stage1_matches}
        assert "114-3053829-2667440" in stage1_order_ids  # Huggies
        assert "112-9352464-5661005" in stage1_order_ids  # Stroller
        assert "114-4106648-0573835" in stage1_order_ids  # Knives

    def test_mock_data_stage2_match(self, amazon_order_matcher, mock_transactions, mock_orders):
        """Test that mock data produces expected Stage 2 match (BioFe)."""
        result = amazon_order_matcher.match_transactions(mock_transactions, mock_orders)

        # Stage 2 (24-day window): $33.36 (23 days apart)
        assert len(result.stage2_matches) == 1
        assert result.stage2_matches[0][1].order_id == "112-6023589-9314641"
        assert result.stage2_matches[0][1].items[0].startswith("BioFe")

    def test_mock_data_total_matched(self, amazon_order_matcher, mock_transactions, mock_orders):
        """Test that all mock transactions find matches."""
        result = amazon_order_matcher.match_transactions(mock_transactions, mock_orders)

        assert result.total_matched == 4
        assert len(result.unmatched_transactions) == 0
        assert len(result.unmatched_orders) == 0

    def test_mock_data_preserves_category_info(
        self, amazon_order_matcher, mock_transactions, mock_orders
    ):
        """Test that matched transactions retain category information."""
        result = amazon_order_matcher.match_transactions(mock_transactions, mock_orders)

        for txn, _ in result.all_matches:
            assert txn.category_id == "03b5e7b1-3485-41d2-98dd-34d9f4ffad33"
            assert txn.category_name == "Reimburse"
