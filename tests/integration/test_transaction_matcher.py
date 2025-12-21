"""Integration tests for TransactionMatcher.

Tests the matcher service with mock/real dependencies.
"""

from datetime import datetime
from pathlib import Path

import pytest

from src.config import CategorizationConfig, PayeesConfig
from src.db.database import AmazonOrderCache, Database
from src.models import Transaction
from src.services.amazon_matcher import TransactionInfo
from src.services.matcher import TransactionMatcher
from src.services.matching import AmazonMatchResult


class MockAmazonMatcher:
    """Mock AmazonOrderMatcher for isolated testing."""

    def __init__(self, matches: dict[str, AmazonOrderCache] | None = None):
        self.matches = matches or {}
        self.get_orders_calls = []
        self.match_calls = []

    def get_orders_for_date_range(
        self, transactions: list[TransactionInfo]
    ) -> list[AmazonOrderCache]:
        """Return predefined orders."""
        self.get_orders_calls.append(transactions)
        return list(self.matches.values())

    def match_transactions(
        self,
        transactions: list[TransactionInfo],
        orders: list[AmazonOrderCache],
        all_transactions: list[TransactionInfo] | None = None,
    ) -> AmazonMatchResult:
        """Return predefined matches."""
        self.match_calls.append((transactions, orders))
        stage1 = []
        for txn in transactions:
            if txn.transaction_id in self.matches:
                stage1.append((txn, self.matches[txn.transaction_id]))
        return AmazonMatchResult(
            stage1_matches=stage1,
            stage2_matches=[],
            duplicate_matches=[],
            combo_matches=[],
            unmatched_transactions=[],
            unmatched_orders=[],
        )

    def normalize_transaction(self, txn: dict) -> TransactionInfo:
        """Convert dict to TransactionInfo."""
        d = txn.get("date")
        if isinstance(d, str):
            date = datetime.strptime(d[:10], "%Y-%m-%d")
        else:
            date = d or datetime.now()
        return TransactionInfo(
            transaction_id=txn.get("id", ""),
            amount=abs(txn.get("amount", 0)),
            date=date,
            date_str=date.strftime("%Y-%m-%d"),
            display_amount=f"${abs(txn.get('amount', 0)):,.2f}",
        )


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
        items=items or ["Test Item"],
        fetched_at=datetime.now(),
    )


def make_transaction(
    id: str = "txn-001",
    date: datetime | None = None,
    amount: float = -44.99,  # In dollars (negative for outflows)
    payee_name: str = "Amazon.com",
    category_id: str | None = None,
    category_name: str | None = None,
    approved: bool = False,
) -> Transaction:
    """Create test transaction."""
    return Transaction(
        id=id,
        date=date or datetime(2025, 11, 24),
        amount=amount,
        payee_name=payee_name,
        account_name="Checking",
        category_id=category_id,
        category_name=category_name,
        approved=approved,
    )


@pytest.fixture
def temp_db(tmp_path: Path) -> Database:
    """Create temporary database."""
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))
    yield db
    db.close()


@pytest.fixture
def default_configs() -> tuple[CategorizationConfig, PayeesConfig]:
    """Default config objects."""
    return CategorizationConfig(), PayeesConfig()


class TestTransactionMatcher:
    """Tests for TransactionMatcher service."""

    def test_is_amazon_transaction_true(self, temp_db: Database, default_configs: tuple) -> None:
        """Identifies Amazon transactions."""
        cat_config, payees_config = default_configs
        matcher = TransactionMatcher(temp_db, cat_config, payees_config)

        txn = make_transaction(payee_name="Amazon.com")
        assert matcher.is_amazon_transaction(txn) is True

    def test_is_amazon_transaction_amzn(self, temp_db: Database, default_configs: tuple) -> None:
        """Identifies AMZN* variant."""
        cat_config, payees_config = default_configs
        matcher = TransactionMatcher(temp_db, cat_config, payees_config)

        txn = make_transaction(payee_name="AMZN Mktp US")
        assert matcher.is_amazon_transaction(txn) is True

    def test_is_amazon_transaction_false(self, temp_db: Database, default_configs: tuple) -> None:
        """Non-Amazon payees return False."""
        cat_config, payees_config = default_configs
        matcher = TransactionMatcher(temp_db, cat_config, payees_config)

        txn = make_transaction(payee_name="Walmart")
        assert matcher.is_amazon_transaction(txn) is False

    def test_enrich_non_amazon(self, temp_db: Database, default_configs: tuple) -> None:
        """Non-Amazon transactions get is_amazon=False."""
        cat_config, payees_config = default_configs
        matcher = TransactionMatcher(temp_db, cat_config, payees_config)

        txn = make_transaction(payee_name="Walmart")
        result = matcher.enrich_transaction(txn)

        assert result.is_amazon is False
        assert result.amazon_order_id is None

    def test_enrich_amazon_no_match(self, temp_db: Database, default_configs: tuple) -> None:
        """Amazon transaction without matching order."""
        cat_config, payees_config = default_configs
        mock_matcher = MockAmazonMatcher(matches={})
        matcher = TransactionMatcher(
            temp_db, cat_config, payees_config, amazon_matcher=mock_matcher
        )

        txn = make_transaction(payee_name="Amazon.com")
        result = matcher.enrich_transaction(txn)

        assert result.is_amazon is True
        assert result.amazon_order_id is None

    def test_enrich_amazon_with_match(self, temp_db: Database, default_configs: tuple) -> None:
        """Amazon transaction with matching order."""
        cat_config, payees_config = default_configs
        order = make_order(items=["Widget A", "Widget B"])
        mock_matcher = MockAmazonMatcher(matches={"txn-001": order})
        matcher = TransactionMatcher(
            temp_db, cat_config, payees_config, amazon_matcher=mock_matcher
        )

        txn = make_transaction(id="txn-001", payee_name="Amazon.com")
        result = matcher.enrich_transaction(txn)

        assert result.is_amazon is True
        assert result.amazon_order_id == "order-001"
        assert result.amazon_items == ["Widget A", "Widget B"]

    def test_enrich_transactions_batch(self, temp_db: Database, default_configs: tuple) -> None:
        """Batch enrich multiple transactions."""
        cat_config, payees_config = default_configs
        order = make_order()
        mock_matcher = MockAmazonMatcher(matches={"txn-1": order})
        matcher = TransactionMatcher(
            temp_db, cat_config, payees_config, amazon_matcher=mock_matcher
        )

        txns = [
            make_transaction(id="txn-1", payee_name="Amazon.com"),
            make_transaction(id="txn-2", payee_name="Walmart"),
        ]

        result = matcher.enrich_transactions(txns)

        assert len(result) == 2
        assert result[0].is_amazon is True
        assert result[0].amazon_order_id == "order-001"
        assert result[1].is_amazon is False

    def test_enrich_transactions_empty(self, temp_db: Database, default_configs: tuple) -> None:
        """Empty list returns empty list."""
        cat_config, payees_config = default_configs
        matcher = TransactionMatcher(temp_db, cat_config, payees_config)

        result = matcher.enrich_transactions([])
        assert result == []

    def test_enrich_transactions_no_amazon(self, temp_db: Database, default_configs: tuple) -> None:
        """All non-Amazon transactions just get marked."""
        cat_config, payees_config = default_configs
        matcher = TransactionMatcher(temp_db, cat_config, payees_config)

        txns = [
            make_transaction(id="txn-1", payee_name="Walmart"),
            make_transaction(id="txn-2", payee_name="Target"),
        ]

        result = matcher.enrich_transactions(txns)

        assert len(result) == 2
        assert all(t.is_amazon is False for t in result)


class TestWithRealMatcher:
    """Tests using real AmazonOrderMatcher and database."""

    @pytest.fixture
    def db_with_orders(self, tmp_path: Path) -> Database:
        """Create database with test orders."""
        db_path = tmp_path / "test.db"
        db = Database(str(db_path))

        # Add test orders
        db.cache_amazon_order("o1", datetime(2025, 11, 24), 44.99)
        db.upsert_amazon_order_items(
            "o1",
            [
                {"name": "Widget A", "price": 24.99, "quantity": 1},
                {"name": "Widget B", "price": 20.00, "quantity": 1},
            ],
        )

        db.cache_amazon_order("o2", datetime(2025, 11, 20), 99.99)

        yield db
        db.close()

    def test_find_order_match(self, db_with_orders: Database, default_configs: tuple) -> None:
        """Can find matching order."""
        cat_config, payees_config = default_configs
        matcher = TransactionMatcher(db_with_orders, cat_config, payees_config)

        txn = make_transaction(
            id="txn-1",
            payee_name="Amazon.com",
            amount=-44.99,  # In dollars
            date=datetime(2025, 11, 24),
        )

        result = matcher.find_order_match(txn)

        assert result is not None
        assert result.order.order_id == "o1"
        assert result.transaction_id == "txn-1"

    def test_find_order_match_non_amazon(
        self, db_with_orders: Database, default_configs: tuple
    ) -> None:
        """Non-Amazon transaction returns None."""
        cat_config, payees_config = default_configs
        matcher = TransactionMatcher(db_with_orders, cat_config, payees_config)

        txn = make_transaction(payee_name="Walmart")

        result = matcher.find_order_match(txn)

        assert result is None

    def test_find_order_match_no_match(
        self, db_with_orders: Database, default_configs: tuple
    ) -> None:
        """No matching order returns None."""
        cat_config, payees_config = default_configs
        matcher = TransactionMatcher(db_with_orders, cat_config, payees_config)

        txn = make_transaction(
            payee_name="Amazon.com",
            amount=-12345,  # No matching order
        )

        result = matcher.find_order_match(txn)

        assert result is None

    def test_match_batch(self, db_with_orders: Database, default_configs: tuple) -> None:
        """Can batch match transactions."""
        cat_config, payees_config = default_configs
        matcher = TransactionMatcher(db_with_orders, cat_config, payees_config)

        txns = [
            make_transaction(
                id="t1",
                payee_name="Amazon.com",
                amount=-44.99,  # Matches order o1
                date=datetime(2025, 11, 24),
            ),
            make_transaction(
                id="t2",
                payee_name="Amazon.com",
                amount=-99.99,  # Matches order o2
                date=datetime(2025, 11, 20),
            ),
        ]

        result = matcher.match_batch(txns)

        assert len(result) == 2
        assert result["t1"].order.order_id == "o1"
        assert result["t2"].order.order_id == "o2"


class TestEnrichTransactionsCombo:
    """Tests for combo match enrichment."""

    def test_enrich_with_combo_match(self, temp_db: Database, default_configs: tuple) -> None:
        """Enriches transactions from combo matches with distributed items."""
        cat_config, payees_config = default_configs

        # Create order with items that will be distributed
        temp_db.cache_amazon_order("combo-order", datetime(2025, 11, 24), 100.00)
        temp_db.upsert_amazon_order_items(
            "combo-order",
            [
                {"name": "Item A", "price": 60.00, "quantity": 1},
                {"name": "Item B", "price": 40.00, "quantity": 1},
            ],
        )

        matcher = TransactionMatcher(temp_db, cat_config, payees_config)

        # Two transactions that together match the order
        txns = [
            make_transaction(
                id="t1",
                payee_name="Amazon.com",
                amount=-60.00,
                date=datetime(2025, 11, 24),
            ),
            make_transaction(
                id="t2",
                payee_name="Amazon.com",
                amount=-40.00,
                date=datetime(2025, 11, 24),
            ),
        ]

        result = matcher.enrich_transactions(txns)

        assert len(result) == 2
        # Both should be marked as Amazon
        assert all(t.is_amazon for t in result)


class TestDistributeItems:
    """Tests for item distribution in combo matches."""

    @pytest.fixture
    def db_with_items(self, tmp_path: Path) -> Database:
        """Database with order items for distribution tests."""
        db_path = tmp_path / "test.db"
        db = Database(str(db_path))

        # Order with multiple items totaling $100
        db.cache_amazon_order("combo-order", datetime(2025, 11, 24), 100.00)
        db.upsert_amazon_order_items(
            "combo-order",
            [
                {"name": "Item A", "price": 60.00, "quantity": 1},
                {"name": "Item B", "price": 25.00, "quantity": 1},
                {"name": "Item C", "price": 15.00, "quantity": 1},
            ],
        )

        yield db
        db.close()

    def test_distribute_items_by_amount(
        self, db_with_items: Database, default_configs: tuple
    ) -> None:
        """Items are distributed to matching transaction amounts."""
        cat_config, payees_config = default_configs
        matcher = TransactionMatcher(db_with_items, cat_config, payees_config)

        # Two transactions that sum to $100
        txn_infos = (
            TransactionInfo(
                transaction_id="t1",
                amount=60.00,
                date=datetime(2025, 11, 24),
                date_str="2025-11-24",
                display_amount="-$60.00",
            ),
            TransactionInfo(
                transaction_id="t2",
                amount=40.00,
                date=datetime(2025, 11, 24),
                date_str="2025-11-24",
                display_amount="-$40.00",
            ),
        )

        result = matcher._distribute_items_by_amount("combo-order", txn_infos)

        # $60 item should go to $60 transaction
        assert "Item A" in result.get("t1", [])
        # $25 and $15 items should go to $40 transaction
        t2_items = result.get("t2", [])
        assert "Item B" in t2_items or "Item C" in t2_items

    def test_distribute_items_empty(self, temp_db: Database, default_configs: tuple) -> None:
        """No items returns empty dict."""
        cat_config, payees_config = default_configs
        matcher = TransactionMatcher(temp_db, cat_config, payees_config)

        txn_infos = (
            TransactionInfo(
                transaction_id="t1",
                amount=60.00,
                date=datetime(2025, 11, 24),
                date_str="2025-11-24",
                display_amount="-$60.00",
            ),
        )

        result = matcher._distribute_items_by_amount("nonexistent-order", txn_infos)

        assert result == {}
