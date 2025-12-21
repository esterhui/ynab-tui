"""Tests for CategoryMappingService.

Tests the category learning and prediction service.
"""

from datetime import datetime
from pathlib import Path

import pytest

from src.db.database import Database
from src.db.models import AmazonOrderCache
from src.services.category_mapping import (
    CategoryMappingService,
    ItemCategoryPrediction,
    LearningResult,
    OrderCategoryPrediction,
)


@pytest.fixture
def temp_db(tmp_path: Path) -> Database:
    """Create temporary database."""
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))
    yield db
    db.close()


@pytest.fixture
def mapping_service(temp_db: Database) -> CategoryMappingService:
    """Create category mapping service."""
    return CategoryMappingService(temp_db)


class TestLearningResult:
    """Tests for LearningResult dataclass."""

    def test_success_true_when_no_errors(self) -> None:
        """Success is True when no errors."""
        result = LearningResult(items_learned=10)
        assert result.success is True

    def test_success_false_when_errors(self) -> None:
        """Success is False when errors exist."""
        result = LearningResult(errors=["Error 1"])
        assert result.success is False


class TestItemCategoryPrediction:
    """Tests for ItemCategoryPrediction dataclass."""

    def test_create_prediction(self) -> None:
        """Can create prediction."""
        pred = ItemCategoryPrediction(
            item_name="USB Cable",
            category_id="cat-1",
            category_name="Electronics",
            confidence=0.9,
            occurrence_count=10,
        )
        assert pred.item_name == "USB Cable"
        assert pred.confidence == 0.9


class TestOrderCategoryPrediction:
    """Tests for OrderCategoryPrediction dataclass."""

    def test_has_any_predictions_false(self) -> None:
        """has_any_predictions returns False when no categories."""
        pred = OrderCategoryPrediction(
            order_id="order-1",
            item_predictions=[
                ItemCategoryPrediction("Item", None, None, 0.0, 0),
            ],
        )
        assert pred.has_any_predictions is False

    def test_has_any_predictions_true(self) -> None:
        """has_any_predictions returns True when has categories."""
        pred = OrderCategoryPrediction(
            order_id="order-1",
            item_predictions=[
                ItemCategoryPrediction("Item", "cat-1", "Electronics", 0.9, 5),
            ],
        )
        assert pred.has_any_predictions is True

    def test_dominant_category_none_when_empty(self) -> None:
        """dominant_category returns None when no predictions."""
        pred = OrderCategoryPrediction(
            order_id="order-1",
            item_predictions=[
                ItemCategoryPrediction("Item1", None, None, 0.0, 0),
                ItemCategoryPrediction("Item2", None, None, 0.0, 0),
            ],
        )
        assert pred.dominant_category is None

    def test_dominant_category_returns_most_common(self) -> None:
        """dominant_category returns most frequent category."""
        pred = OrderCategoryPrediction(
            order_id="order-1",
            item_predictions=[
                ItemCategoryPrediction("Item1", "cat-1", "Electronics", 0.9, 5),
                ItemCategoryPrediction("Item2", "cat-1", "Electronics", 0.8, 3),
                ItemCategoryPrediction("Item3", "cat-2", "Household", 0.7, 2),
            ],
        )
        result = pred.dominant_category
        assert result is not None
        cat_id, cat_name, avg_confidence = result
        assert cat_id == "cat-1"
        assert cat_name == "Electronics"
        assert avg_confidence == pytest.approx(0.85)


class TestGetSuggestedCategory:
    """Tests for get_suggested_category method."""

    def test_returns_none_for_unknown_item(self, mapping_service: CategoryMappingService) -> None:
        """Returns None for unknown item."""
        result = mapping_service.get_suggested_category("Unknown Item")
        assert result is None

    def test_returns_category_for_known_item(
        self, temp_db: Database, mapping_service: CategoryMappingService
    ) -> None:
        """Returns category for known item."""
        # Record some learning
        temp_db.record_item_category_learning("USB Cable", "cat-1", "Electronics")
        temp_db.record_item_category_learning("USB Cable", "cat-1", "Electronics")

        result = mapping_service.get_suggested_category("USB Cable")

        assert result is not None
        assert result["category_id"] == "cat-1"
        assert result["category_name"] == "Electronics"

    def test_respects_min_confidence(
        self, temp_db: Database, mapping_service: CategoryMappingService
    ) -> None:
        """Respects minimum confidence threshold."""
        # Split 50/50 - neither should pass 0.6 threshold
        temp_db.record_item_category_learning("Widget", "cat-1", "A")
        temp_db.record_item_category_learning("Widget", "cat-2", "B")

        result = mapping_service.get_suggested_category("Widget", min_confidence=0.6)

        assert result is None


class TestPredictItemCategory:
    """Tests for predict_item_category method."""

    def test_returns_empty_prediction_for_unknown(
        self, mapping_service: CategoryMappingService
    ) -> None:
        """Returns empty prediction for unknown item."""
        result = mapping_service.predict_item_category("Unknown")

        assert result.item_name == "Unknown"
        assert result.category_id is None
        assert result.confidence == 0.0

    def test_returns_prediction_for_known(
        self, temp_db: Database, mapping_service: CategoryMappingService
    ) -> None:
        """Returns prediction for known item."""
        temp_db.record_item_category_learning("Keyboard", "cat-1", "Electronics")
        temp_db.record_item_category_learning("Keyboard", "cat-1", "Electronics")

        result = mapping_service.predict_item_category("Keyboard")

        assert result.category_id == "cat-1"
        assert result.category_name == "Electronics"
        assert result.occurrence_count == 2


class TestPredictOrderCategories:
    """Tests for predict_order_categories method."""

    def test_predicts_for_all_items(
        self, temp_db: Database, mapping_service: CategoryMappingService
    ) -> None:
        """Predicts category for each item in order."""
        # Record some learning
        temp_db.record_item_category_learning("USB Cable", "cat-1", "Electronics")
        temp_db.record_item_category_learning("Mouse", "cat-1", "Electronics")

        order = AmazonOrderCache(
            order_id="order-1",
            order_date=datetime(2025, 11, 24),
            total=50.0,
            items=["USB Cable", "Mouse", "Unknown Item"],
            fetched_at=datetime.now(),
        )

        result = mapping_service.predict_order_categories(order)

        assert result.order_id == "order-1"
        assert len(result.item_predictions) == 3
        # Known items should have predictions
        usb_pred = result.item_predictions[0]
        assert usb_pred.category_id == "cat-1"


class TestGetStatistics:
    """Tests for get_statistics method."""

    def test_returns_empty_stats(self, mapping_service: CategoryMappingService) -> None:
        """Returns zero counts when no data."""
        result = mapping_service.get_statistics()

        assert result["total_mappings"] == 0
        assert result["unique_items"] == 0

    def test_returns_correct_stats(
        self, temp_db: Database, mapping_service: CategoryMappingService
    ) -> None:
        """Returns correct counts after learning."""
        temp_db.record_item_category_learning("Item A", "cat-1", "Cat1")
        temp_db.record_item_category_learning("Item B", "cat-2", "Cat2")
        temp_db.record_item_category_learning("Item A", "cat-2", "Cat2")  # Same item, diff cat

        result = mapping_service.get_statistics()

        assert result["total_mappings"] == 3
        assert result["unique_items"] == 2


class TestParseDate:
    """Tests for _parse_date method."""

    def test_parses_datetime(self, mapping_service: CategoryMappingService) -> None:
        """Parses datetime objects."""
        dt = datetime(2025, 11, 24)
        result = mapping_service._parse_date(dt)
        assert result == dt

    def test_parses_string(self, mapping_service: CategoryMappingService) -> None:
        """Parses date strings."""
        result = mapping_service._parse_date("2025-11-24")
        assert result == datetime(2025, 11, 24)

    def test_handles_invalid(self, mapping_service: CategoryMappingService) -> None:
        """Returns min date for invalid input."""
        result = mapping_service._parse_date(None)
        assert result == datetime.min


class TestLearnFromApprovedTransactions:
    """Tests for learn_from_approved_transactions method."""

    def test_returns_empty_when_no_transactions(
        self, mapping_service: CategoryMappingService
    ) -> None:
        """Returns empty result when no approved transactions."""
        result = mapping_service.learn_from_approved_transactions()

        assert result.success is True
        assert result.transactions_processed == 0
        assert result.items_learned == 0

    def test_returns_empty_when_no_amazon_transactions(
        self, temp_db: Database, mapping_service: CategoryMappingService
    ) -> None:
        """Returns empty when no Amazon transactions found."""
        from src.models import Transaction

        # Add non-Amazon approved transaction
        txn = Transaction(
            id="txn-1",
            date=datetime(2025, 11, 24),
            amount=-50.0,
            payee_name="Walmart",
            account_name="Checking",
            approved=True,
            category_id="cat-1",
            category_name="Groceries",
        )
        temp_db.upsert_ynab_transaction(txn)

        result = mapping_service.learn_from_approved_transactions()

        assert result.transactions_processed == 0

    def test_processes_amazon_transactions(
        self, temp_db: Database, mapping_service: CategoryMappingService
    ) -> None:
        """Processes approved Amazon transactions."""
        from src.models import Transaction

        # Add approved Amazon transaction
        txn = Transaction(
            id="txn-1",
            date=datetime(2025, 11, 24),
            amount=-44.99,
            payee_name="Amazon.com",
            account_name="Checking",
            approved=True,
            category_id="cat-1",
            category_name="Electronics",
        )
        temp_db.upsert_ynab_transaction(txn)

        # Add matching Amazon order
        temp_db.cache_amazon_order("order-1", datetime(2025, 11, 24), 44.99)
        temp_db.upsert_amazon_order_items("order-1", [{"name": "USB Cable", "price": 44.99}])

        result = mapping_service.learn_from_approved_transactions()

        assert result.transactions_processed == 1
        assert result.transactions_matched == 1
        assert result.items_learned == 1

    def test_respects_since_date(
        self, temp_db: Database, mapping_service: CategoryMappingService
    ) -> None:
        """Respects since_date filter."""
        from src.models import Transaction

        # Old transaction
        old_txn = Transaction(
            id="txn-1",
            date=datetime(2025, 1, 1),
            amount=-44.99,
            payee_name="Amazon.com",
            account_name="Checking",
            approved=True,
            category_id="cat-1",
            category_name="Electronics",
        )
        temp_db.upsert_ynab_transaction(old_txn)

        # Recent transaction
        new_txn = Transaction(
            id="txn-2",
            date=datetime(2025, 11, 24),
            amount=-50.0,
            payee_name="Amazon.com",
            account_name="Checking",
            approved=True,
            category_id="cat-1",
            category_name="Electronics",
        )
        temp_db.upsert_ynab_transaction(new_txn)

        result = mapping_service.learn_from_approved_transactions(since_date=datetime(2025, 6, 1))

        # Only the recent transaction should be processed
        assert result.transactions_processed == 1

    def test_dry_run_does_not_record(
        self, temp_db: Database, mapping_service: CategoryMappingService
    ) -> None:
        """Dry run doesn't record learnings."""
        from src.models import Transaction

        txn = Transaction(
            id="txn-1",
            date=datetime(2025, 11, 24),
            amount=-44.99,
            payee_name="Amazon.com",
            account_name="Checking",
            approved=True,
            category_id="cat-1",
            category_name="Electronics",
        )
        temp_db.upsert_ynab_transaction(txn)

        temp_db.cache_amazon_order("order-1", datetime(2025, 11, 24), 44.99)
        temp_db.upsert_amazon_order_items("order-1", [{"name": "USB Cable", "price": 44.99}])

        result = mapping_service.learn_from_approved_transactions(dry_run=True)

        assert result.items_learned >= 0  # May be counted in dry run
        # But no actual records
        stats = mapping_service.get_statistics()
        assert stats["total_mappings"] == 0

    def test_skips_uncategorized_transactions(
        self, temp_db: Database, mapping_service: CategoryMappingService
    ) -> None:
        """Skips transactions without category."""
        from src.models import Transaction

        # Approved but uncategorized
        txn = Transaction(
            id="txn-1",
            date=datetime(2025, 11, 24),
            amount=-44.99,
            payee_name="Amazon.com",
            account_name="Checking",
            approved=True,
            category_id=None,
            category_name=None,
        )
        temp_db.upsert_ynab_transaction(txn)

        result = mapping_service.learn_from_approved_transactions()

        # Should not process uncategorized
        assert result.transactions_processed == 0


class TestLearnFromNonSplit:
    """Tests for _learn_from_non_split method."""

    def test_learns_from_all_items(
        self, temp_db: Database, mapping_service: CategoryMappingService
    ) -> None:
        """Learns from all items in order."""
        from src.services.amazon_matcher import TransactionInfo

        temp_db.cache_amazon_order("order-1", datetime(2025, 11, 24), 100.0)
        temp_db.upsert_amazon_order_items(
            "order-1",
            [
                {"name": "Item A", "price": 50.0},
                {"name": "Item B", "price": 50.0},
            ],
        )

        order = AmazonOrderCache(
            order_id="order-1",
            order_date=datetime(2025, 11, 24),
            total=100.0,
            items=["Item A", "Item B"],
            fetched_at=datetime.now(),
        )

        txn_info = TransactionInfo(
            transaction_id="txn-1",
            amount=100.0,
            date=datetime(2025, 11, 24),
            date_str="2025-11-24",
            display_amount="$100.00",
            category_id="cat-1",
            category_name="Electronics",
        )

        counts = mapping_service._learn_from_non_split(txn_info, order)

        assert counts["new"] == 2
        assert counts["duplicate"] == 0
        assert counts["no_category"] == 0

    def test_reports_no_category(
        self, temp_db: Database, mapping_service: CategoryMappingService
    ) -> None:
        """Reports items without category."""
        from src.services.amazon_matcher import TransactionInfo

        order = AmazonOrderCache(
            order_id="order-1",
            order_date=datetime(2025, 11, 24),
            total=50.0,
            items=["Item A"],
            fetched_at=datetime.now(),
        )

        txn_info = TransactionInfo(
            transaction_id="txn-1",
            amount=50.0,
            date=datetime(2025, 11, 24),
            date_str="2025-11-24",
            display_amount="$50.00",
            category_id=None,  # No category
            category_name=None,
        )

        counts = mapping_service._learn_from_non_split(txn_info, order)

        assert counts["no_category"] == 1

    def test_skips_empty_items(
        self, temp_db: Database, mapping_service: CategoryMappingService
    ) -> None:
        """Skips empty item names."""
        from src.services.amazon_matcher import TransactionInfo

        order = AmazonOrderCache(
            order_id="order-1",
            order_date=datetime(2025, 11, 24),
            total=50.0,
            items=["Valid Item", "", "   "],  # Some empty items
            fetched_at=datetime.now(),
        )

        txn_info = TransactionInfo(
            transaction_id="txn-1",
            amount=50.0,
            date=datetime(2025, 11, 24),
            date_str="2025-11-24",
            display_amount="$50.00",
            category_id="cat-1",
            category_name="Electronics",
        )

        counts = mapping_service._learn_from_non_split(txn_info, order)

        assert counts["new"] == 1  # Only valid item
