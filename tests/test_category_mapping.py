"""Tests for CategoryMappingService."""

from datetime import datetime

import pytest

from ynab_tui.db.database import AmazonOrderCache
from ynab_tui.models import Transaction
from ynab_tui.services.category_mapping import (
    ItemCategoryPrediction,
    LearningResult,
    OrderCategoryPrediction,
)
from ynab_tui.utils import is_amazon_payee


class TestLearningResult:
    """Tests for LearningResult dataclass."""

    def test_success_when_no_errors(self):
        """Test success property when no errors."""
        result = LearningResult()
        assert result.success is True

    def test_failure_when_errors(self):
        """Test success property when errors present."""
        result = LearningResult(errors=["Something went wrong"])
        assert result.success is False

    def test_default_values(self):
        """Test default values are zero."""
        result = LearningResult()
        assert result.transactions_processed == 0
        assert result.transactions_matched == 0
        assert result.items_learned == 0
        assert result.items_skipped_no_category == 0
        assert result.items_skipped_duplicate == 0
        assert result.split_transactions_skipped == 0


class TestCategoryMappingService:
    """Tests for CategoryMappingService."""

    @pytest.fixture
    def setup_approved_amazon_transaction(self, database):
        """Create an approved Amazon transaction with matching order."""
        # Create approved Amazon transaction
        txn = Transaction(
            id="txn-amazon-approved",
            date=datetime(2025, 11, 23),
            amount=-59.48,
            payee_name="Amazon",
            category_id="cat-kitchen",
            category_name="Kitchen",
            approved=True,
        )
        database.upsert_ynab_transaction(txn)

        # Create matching Amazon order
        database.cache_amazon_order(
            order_id="order-114-kitchen",
            order_date=datetime(2025, 11, 21),
            total=59.48,
        )
        database.upsert_amazon_order_items(
            "order-114-kitchen",
            [{"name": "KYOCERA Ceramic Knife Set"}, {"name": "Kitchen Towels"}],
        )

        return txn

    @pytest.fixture
    def setup_multiple_transactions(self, database):
        """Create multiple approved Amazon transactions with orders."""
        # Transaction 1: Kitchen items
        txn1 = Transaction(
            id="txn-kitchen",
            date=datetime(2025, 11, 23),
            amount=-59.48,
            payee_name="Amazon",
            category_id="cat-kitchen",
            category_name="Kitchen",
            approved=True,
        )
        database.upsert_ynab_transaction(txn1)
        database.cache_amazon_order(
            order_id="order-kitchen",
            order_date=datetime(2025, 11, 21),
            total=59.48,
        )
        database.upsert_amazon_order_items("order-kitchen", [{"name": "KYOCERA Knife Set"}])

        # Transaction 2: Baby items
        txn2 = Transaction(
            id="txn-baby",
            date=datetime(2025, 11, 27),
            amount=-44.99,
            payee_name="Amazon",
            category_id="cat-baby",
            category_name="Baby Gear",
            approved=True,
        )
        database.upsert_ynab_transaction(txn2)
        database.cache_amazon_order(
            order_id="order-baby",
            order_date=datetime(2025, 11, 24),
            total=44.99,
        )
        database.upsert_amazon_order_items("order-baby", [{"name": "Huggies Diapers Size 4"}])

        # Transaction 3: Pet items (same item as grocery below for testing distribution)
        txn3 = Transaction(
            id="txn-pet",
            date=datetime(2025, 11, 25),
            amount=-38.50,
            payee_name="AMZN MKTPLACE",
            category_id="cat-pet",
            category_name="Pet Supplies",
            approved=True,
        )
        database.upsert_ynab_transaction(txn3)
        database.cache_amazon_order(
            order_id="order-pet",
            order_date=datetime(2025, 11, 24),
            total=38.50,
        )
        database.upsert_amazon_order_items("order-pet", [{"name": "Cat Food"}])

        return [txn1, txn2, txn3]

    def test_is_amazon_payee(self, category_mapping_service):
        """Test Amazon payee detection."""
        patterns = category_mapping_service._amazon_patterns
        assert is_amazon_payee("Amazon", patterns) is True
        assert is_amazon_payee("AMAZON", patterns) is True
        assert is_amazon_payee("AMZN MKTPLACE", patterns) is True
        assert is_amazon_payee("Amazon.com", patterns) is True
        assert is_amazon_payee("Walmart", patterns) is False
        assert is_amazon_payee("", patterns) is False
        assert is_amazon_payee(None, patterns) is False

    def test_learn_no_transactions(self, category_mapping_service):
        """Test learning with no transactions."""
        result = category_mapping_service.learn_from_approved_transactions()
        assert result.transactions_processed == 0
        assert result.items_learned == 0
        assert result.success is True

    def test_learn_from_approved_transaction(
        self, category_mapping_service, setup_approved_amazon_transaction, database
    ):
        """Test learning from a single approved Amazon transaction."""
        result = category_mapping_service.learn_from_approved_transactions()

        assert result.transactions_processed == 1
        assert result.transactions_matched == 1
        assert result.items_learned == 2  # KYOCERA + Kitchen Towels
        assert result.success is True

        # Verify mappings were recorded
        assert database.get_item_category_history_count() == 2

    def test_learn_dry_run(
        self, category_mapping_service, setup_approved_amazon_transaction, database
    ):
        """Test dry run doesn't record anything."""
        result = category_mapping_service.learn_from_approved_transactions(dry_run=True)

        assert result.transactions_processed == 1
        assert result.transactions_matched == 1
        assert result.items_learned == 2  # Would have learned 2
        assert result.success is True

        # But nothing was actually recorded
        assert database.get_item_category_history_count() == 0

    def test_learn_respects_since_date(
        self, category_mapping_service, setup_multiple_transactions, database
    ):
        """Test that since_date filter works."""
        # Only learn from transactions after Nov 25
        result = category_mapping_service.learn_from_approved_transactions(
            since_date=datetime(2025, 11, 26)
        )

        # Only txn-baby (Nov 27) should match
        assert result.transactions_processed == 1
        assert result.transactions_matched == 1
        assert result.items_learned == 1  # Huggies Diapers

    def test_learn_skips_unapproved(self, category_mapping_service, database):
        """Test that unapproved transactions are skipped."""
        # Create unapproved Amazon transaction
        txn = Transaction(
            id="txn-unapproved",
            date=datetime(2025, 11, 23),
            amount=-50.00,
            payee_name="Amazon",
            category_id="cat-test",
            category_name="Test",
            approved=False,  # Not approved!
        )
        database.upsert_ynab_transaction(txn)
        database.cache_amazon_order(
            order_id="order-unapproved",
            order_date=datetime(2025, 11, 21),
            total=50.00,
        )
        database.upsert_amazon_order_items("order-unapproved", [{"name": "Test Item"}])

        result = category_mapping_service.learn_from_approved_transactions()

        assert result.transactions_processed == 0  # Skipped
        assert result.items_learned == 0

    def test_learn_skips_no_category(self, category_mapping_service, database):
        """Test that transactions without category are skipped."""
        # Create approved Amazon transaction without category
        txn = Transaction(
            id="txn-no-cat",
            date=datetime(2025, 11, 23),
            amount=-50.00,
            payee_name="Amazon",
            category_id=None,  # No category
            approved=True,
        )
        database.upsert_ynab_transaction(txn)

        result = category_mapping_service.learn_from_approved_transactions()

        assert result.transactions_processed == 0  # Skipped (no category_id)

    def test_learn_detects_duplicates(self, category_mapping_service, database):
        """Test that duplicate mappings are tracked."""
        # Create same transaction/order twice (simulating re-run)
        txn = Transaction(
            id="txn-dup",
            date=datetime(2025, 11, 23),
            amount=-50.00,
            payee_name="Amazon",
            category_id="cat-test",
            category_name="Test",
            approved=True,
        )
        database.upsert_ynab_transaction(txn)
        database.cache_amazon_order(
            order_id="order-dup",
            order_date=datetime(2025, 11, 21),
            total=50.00,
        )
        database.upsert_amazon_order_items("order-dup", [{"name": "Test Item"}])

        # First run
        result1 = category_mapping_service.learn_from_approved_transactions()
        assert result1.items_learned == 1
        assert result1.items_skipped_duplicate == 0

        # Second run (same data)
        result2 = category_mapping_service.learn_from_approved_transactions()
        assert result2.items_learned == 0
        assert result2.items_skipped_duplicate == 1

    def test_get_suggested_category(self, category_mapping_service, database):
        """Test getting suggested category."""
        # Record multiple categorizations for same item
        for i in range(8):
            database.record_item_category_learning(
                item_name="Cat Food Premium",
                category_id="cat-pet",
                category_name="Pet Supplies",
                source_transaction_id=f"txn-{i}",
            )
        for i in range(2):
            database.record_item_category_learning(
                item_name="Cat Food Premium",
                category_id="cat-grocery",
                category_name="Groceries",
                source_transaction_id=f"txn-g-{i}",
            )

        suggestion = category_mapping_service.get_suggested_category("cat food premium")

        assert suggestion is not None
        assert suggestion["category_id"] == "cat-pet"
        assert suggestion["category_name"] == "Pet Supplies"
        assert suggestion["confidence"] == 0.8
        assert suggestion["count"] == 8

    def test_get_suggested_category_low_confidence(self, category_mapping_service, database):
        """Test that low confidence returns None."""
        # 50/50 split - below default 0.5 threshold
        database.record_item_category_learning(
            item_name="Mixed Item",
            category_id="cat-a",
            category_name="Category A",
            source_transaction_id="txn-a",
        )
        database.record_item_category_learning(
            item_name="Mixed Item",
            category_id="cat-b",
            category_name="Category B",
            source_transaction_id="txn-b",
        )

        suggestion = category_mapping_service.get_suggested_category(
            "mixed item", min_confidence=0.6
        )
        assert suggestion is None

    def test_get_suggested_category_unknown_item(self, category_mapping_service):
        """Test getting suggestion for unknown item."""
        suggestion = category_mapping_service.get_suggested_category("totally unknown item xyz")
        assert suggestion is None

    def test_get_statistics(self, category_mapping_service, database):
        """Test getting statistics."""
        # Empty initially
        stats = category_mapping_service.get_statistics()
        assert stats["total_mappings"] == 0
        assert stats["unique_items"] == 0

        # Add some data
        database.record_item_category_learning(
            item_name="Cat Food",
            category_id="cat-pet",
            category_name="Pet Supplies",
            source_transaction_id="txn-1",
        )
        database.record_item_category_learning(
            item_name="Cat Food",
            category_id="cat-grocery",
            category_name="Groceries",
            source_transaction_id="txn-2",
        )
        database.record_item_category_learning(
            item_name="Dog Food",
            category_id="cat-pet",
            category_name="Pet Supplies",
            source_transaction_id="txn-3",
        )

        stats = category_mapping_service.get_statistics()
        assert stats["total_mappings"] == 3
        assert stats["unique_items"] == 2


class TestCategoryMappingServiceWithMockData:
    """Tests using patterns from mock data."""

    @pytest.fixture
    def setup_mock_data(self, database):
        """Setup data matching mock_data patterns."""
        # From mock_data/transactions.csv - Amazon transactions with "Reimburse" category
        transactions = [
            Transaction(
                id="5c58c34a-f483-4539-91ef-2cfd6b076381",
                date=datetime(2025, 11, 27),
                amount=-44.99,
                payee_name="Amazon",
                category_id="03b5e7b1-3485-41d2-98dd-34d9f4ffad33",
                category_name="Reimburse",
                approved=True,
            ),
            Transaction(
                id="8ed61813-9fb9-41c7-94f4-b22acd74f02a",
                date=datetime(2025, 11, 23),
                amount=-217.66,
                payee_name="Amazon",
                category_id="03b5e7b1-3485-41d2-98dd-34d9f4ffad33",
                category_name="Reimburse",
                approved=True,
            ),
            Transaction(
                id="c8755c02-8c36-4158-917b-6120dacf6b08",
                date=datetime(2025, 11, 23),
                amount=-59.48,
                payee_name="Amazon",
                category_id="03b5e7b1-3485-41d2-98dd-34d9f4ffad33",
                category_name="Reimburse",
                approved=True,
            ),
        ]
        for txn in transactions:
            database.upsert_ynab_transaction(txn)

        # From mock_data/orders.csv - matching orders
        database.cache_amazon_order(
            order_id="114-3053829-2667440",
            order_date=datetime(2025, 11, 24),
            total=44.99,
        )
        database.upsert_amazon_order_items(
            "114-3053829-2667440",
            [{"name": "Huggies Size 4 Diapers, Little Snugglers Baby Diapers"}],
        )
        database.cache_amazon_order(
            order_id="112-9352464-5661005",
            order_date=datetime(2025, 11, 21),
            total=217.66,
        )
        database.upsert_amazon_order_items(
            "112-9352464-5661005",
            [{"name": "Inglesina Quid 2 Stroller - Alpaca Beige"}],
        )
        database.cache_amazon_order(
            order_id="114-4106648-0573835",
            order_date=datetime(2025, 11, 21),
            total=59.48,
        )
        database.upsert_amazon_order_items(
            "114-4106648-0573835",
            [{"name": "KYOCERA Revolution 2-Piece Ceramic Knife Set"}],
        )

        return transactions

    def test_learn_from_mock_data(self, category_mapping_service, setup_mock_data, database):
        """Test learning from mock data patterns."""
        result = category_mapping_service.learn_from_approved_transactions()

        assert result.transactions_processed == 3
        assert result.transactions_matched == 3
        assert result.items_learned == 3  # One item per order
        assert result.success is True

        # All items should be mapped to "Reimburse"
        mappings = database.get_all_item_category_mappings()
        assert len(mappings) == 3

        for mapping in mappings:
            assert len(mapping["categories"]) == 1
            assert mapping["categories"][0]["name"] == "Reimburse"


class TestOrderCategoryPrediction:
    """Tests for OrderCategoryPrediction dataclass."""

    def test_has_any_predictions_true(self):
        """Test has_any_predictions when items have predictions."""
        prediction = OrderCategoryPrediction(
            order_id="order-123",
            item_predictions=[
                ItemCategoryPrediction(
                    item_name="Item 1",
                    category_id="cat-001",
                    category_name="Electronics",
                    confidence=0.8,
                    occurrence_count=5,
                ),
            ],
        )
        assert prediction.has_any_predictions is True

    def test_has_any_predictions_false(self):
        """Test has_any_predictions when no items have predictions."""
        prediction = OrderCategoryPrediction(
            order_id="order-123",
            item_predictions=[
                ItemCategoryPrediction(
                    item_name="Unknown Item",
                    category_id=None,
                    category_name=None,
                    confidence=0.0,
                    occurrence_count=0,
                ),
            ],
        )
        assert prediction.has_any_predictions is False

    def test_dominant_category_single_item(self):
        """Test dominant_category with single item."""
        prediction = OrderCategoryPrediction(
            order_id="order-123",
            item_predictions=[
                ItemCategoryPrediction(
                    item_name="Item 1",
                    category_id="cat-001",
                    category_name="Electronics",
                    confidence=0.9,
                    occurrence_count=10,
                ),
            ],
        )
        result = prediction.dominant_category
        assert result is not None
        assert result[0] == "cat-001"
        assert result[1] == "Electronics"
        assert result[2] == 0.9

    def test_dominant_category_multiple_items_same_category(self):
        """Test dominant_category when items share the same category."""
        prediction = OrderCategoryPrediction(
            order_id="order-123",
            item_predictions=[
                ItemCategoryPrediction(
                    item_name="Item 1",
                    category_id="cat-001",
                    category_name="Electronics",
                    confidence=0.8,
                    occurrence_count=5,
                ),
                ItemCategoryPrediction(
                    item_name="Item 2",
                    category_id="cat-001",
                    category_name="Electronics",
                    confidence=0.9,
                    occurrence_count=10,
                ),
            ],
        )
        result = prediction.dominant_category
        assert result is not None
        assert result[0] == "cat-001"
        assert result[1] == "Electronics"
        # Average confidence: (0.8 + 0.9) / 2 = 0.85
        assert abs(result[2] - 0.85) < 0.01

    def test_dominant_category_different_categories(self):
        """Test dominant_category returns most common category."""
        prediction = OrderCategoryPrediction(
            order_id="order-123",
            item_predictions=[
                ItemCategoryPrediction(
                    item_name="Item 1",
                    category_id="cat-001",
                    category_name="Electronics",
                    confidence=0.8,
                    occurrence_count=5,
                ),
                ItemCategoryPrediction(
                    item_name="Item 2",
                    category_id="cat-002",
                    category_name="Home",
                    confidence=0.7,
                    occurrence_count=3,
                ),
                ItemCategoryPrediction(
                    item_name="Item 3",
                    category_id="cat-001",
                    category_name="Electronics",
                    confidence=0.9,
                    occurrence_count=8,
                ),
            ],
        )
        result = prediction.dominant_category
        assert result is not None
        # cat-001 appears twice, cat-002 once
        assert result[0] == "cat-001"
        assert result[1] == "Electronics"

    def test_dominant_category_none_when_no_predictions(self):
        """Test dominant_category returns None when no items have categories."""
        prediction = OrderCategoryPrediction(
            order_id="order-123",
            item_predictions=[
                ItemCategoryPrediction(
                    item_name="Unknown Item",
                    category_id=None,
                    category_name=None,
                    confidence=0.0,
                    occurrence_count=0,
                ),
            ],
        )
        assert prediction.dominant_category is None


class TestPredictItemCategory:
    """Tests for predict_item_category method."""

    def test_predict_item_category_with_history(self, category_mapping_service, database):
        """Test predicting category for item with history."""
        # Add history for an item
        for i in range(5):
            database.record_item_category_learning(
                item_name="USB Cable",
                category_id="cat-electronics",
                category_name="Electronics",
                source_transaction_id=f"txn-{i}",
            )

        prediction = category_mapping_service.predict_item_category("USB Cable")

        assert prediction.item_name == "USB Cable"
        assert prediction.category_id == "cat-electronics"
        assert prediction.category_name == "Electronics"
        assert prediction.confidence == 1.0
        assert prediction.occurrence_count == 5

    def test_predict_item_category_no_history(self, category_mapping_service):
        """Test predicting category for item with no history."""
        prediction = category_mapping_service.predict_item_category("Unknown Item XYZ")

        assert prediction.item_name == "Unknown Item XYZ"
        assert prediction.category_id is None
        assert prediction.category_name is None
        assert prediction.confidence == 0.0
        assert prediction.occurrence_count == 0


class TestPredictOrderCategories:
    """Tests for predict_order_categories method."""

    def test_predict_order_categories(self, category_mapping_service, database):
        """Test predicting categories for all items in an order."""
        # Add history for some items
        database.record_item_category_learning(
            item_name="USB Cable",
            category_id="cat-electronics",
            category_name="Electronics",
            source_transaction_id="txn-1",
        )

        # Create an order
        order = AmazonOrderCache(
            order_id="order-test",
            order_date=datetime(2024, 1, 15),
            total=50.00,
            items=["USB Cable", "Unknown Item"],
            fetched_at=datetime(2024, 1, 15),
        )

        prediction = category_mapping_service.predict_order_categories(order)

        assert prediction.order_id == "order-test"
        assert len(prediction.item_predictions) == 2

        # First item should have prediction
        usb_pred = next(p for p in prediction.item_predictions if p.item_name == "USB Cable")
        assert usb_pred.category_id == "cat-electronics"

        # Second item should not have prediction
        unknown_pred = next(p for p in prediction.item_predictions if p.item_name == "Unknown Item")
        assert unknown_pred.category_id is None
