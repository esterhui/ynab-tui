"""Tests for HistoryMixin database operations.

These tests use a real temporary SQLite database.
"""

from pathlib import Path

import pytest

from src.db.database import Database


@pytest.fixture
def temp_db(tmp_path: Path) -> Database:
    """Create a temporary database for testing."""
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))
    yield db
    db.close()


class TestHistoryMixin:
    """Tests for categorization history operations."""

    def test_normalize_payee(self, temp_db: Database) -> None:
        """Payee names are normalized consistently."""
        result = temp_db.normalize_payee("  Amazon.Com Store  ")
        # Just lowercases and strips whitespace
        assert result == "amazon.com store"

    def test_normalize_item(self, temp_db: Database) -> None:
        """Item names are normalized consistently."""
        result = temp_db.normalize_item("Widget Pro 2000")
        assert result == "widget pro 2000"

    def test_add_categorization(self, temp_db: Database) -> None:
        """Can add a categorization record."""
        record_id = temp_db.add_categorization(
            payee_name="Amazon.com",
            category_name="Shopping",
            category_id="cat-1",
            amount=44.99,
        )

        assert record_id > 0

    def test_add_categorization_with_amazon_items(self, temp_db: Database) -> None:
        """Can add categorization with Amazon item names."""
        record_id = temp_db.add_categorization(
            payee_name="Amazon.com",
            category_name="Electronics",
            category_id="cat-1",
            amount=199.99,
            amazon_items=["USB Cable", "Keyboard"],
        )

        assert record_id > 0

    def test_get_payee_history_empty(self, temp_db: Database) -> None:
        """Empty history returns empty list."""
        result = temp_db.get_payee_history("Unknown Payee")
        assert result == []

    def test_get_payee_history(self, temp_db: Database) -> None:
        """Can get payee history."""
        # Add some history
        temp_db.add_categorization("Amazon.com", "Shopping", "cat-1", 44.99)
        temp_db.add_categorization("Amazon.com", "Electronics", "cat-2", 99.99)
        temp_db.add_categorization("Walmart", "Groceries", "cat-3", 55.00)

        history = temp_db.get_payee_history("Amazon.com")

        assert len(history) == 2
        categories = {h.category_name for h in history}
        assert categories == {"Shopping", "Electronics"}

    def test_get_payee_history_limit(self, temp_db: Database) -> None:
        """History respects limit."""
        for i in range(10):
            temp_db.add_categorization("Amazon.com", f"Cat{i}", f"cat-{i}")

        history = temp_db.get_payee_history("Amazon.com", limit=3)
        assert len(history) == 3

    def test_get_payee_history_normalized_matching(self, temp_db: Database) -> None:
        """History matches on normalized payee name."""
        temp_db.add_categorization("AMAZON.COM", "Shopping", "cat-1")

        # Should match even with different case
        history = temp_db.get_payee_history("amazon.com")
        assert len(history) == 1

    def test_get_payee_category_distribution_empty(self, temp_db: Database) -> None:
        """Empty distribution returns empty dict."""
        result = temp_db.get_payee_category_distribution("Unknown")
        assert result == {}

    def test_get_payee_category_distribution(self, temp_db: Database) -> None:
        """Can get category distribution for payee."""
        temp_db.add_categorization("Amazon.com", "Shopping", "cat-1", 50.00)
        temp_db.add_categorization("Amazon.com", "Shopping", "cat-1", 60.00)
        temp_db.add_categorization("Amazon.com", "Electronics", "cat-2", 100.00)

        dist = temp_db.get_payee_category_distribution("Amazon.com")

        assert "Shopping" in dist
        assert "Electronics" in dist
        assert dist["Shopping"]["count"] == 2
        assert dist["Shopping"]["percentage"] == pytest.approx(2 / 3)
        assert dist["Electronics"]["count"] == 1

    def test_get_payee_category_distributions_batch_empty(self, temp_db: Database) -> None:
        """Batch with empty list returns empty."""
        result = temp_db.get_payee_category_distributions_batch([])
        assert result == {}

    def test_get_payee_category_distributions_batch(self, temp_db: Database) -> None:
        """Can get distributions for multiple payees."""
        amazon = "Amazon.com"
        walmart = "Walmart"
        temp_db.add_categorization(amazon, "Shopping", "cat-1")
        temp_db.add_categorization(amazon, "Electronics", "cat-2")
        temp_db.add_categorization(walmart, "Groceries", "cat-3")
        temp_db.add_categorization(walmart, "Groceries", "cat-3")

        result = temp_db.get_payee_category_distributions_batch([amazon, walmart])

        assert amazon in result
        assert walmart in result
        assert result[walmart]["Groceries"]["count"] == 2


class TestItemCategoryHistory:
    """Tests for item→category learning."""

    def test_record_item_category_learning(self, temp_db: Database) -> None:
        """Can record item→category mapping."""
        result = temp_db.record_item_category_learning(
            item_name="USB-C Cable",
            category_id="cat-1",
            category_name="Electronics",
        )

        assert result is True

    def test_record_item_category_learning_with_source(self, temp_db: Database) -> None:
        """Can record with source transaction and order."""
        result = temp_db.record_item_category_learning(
            item_name="Widget",
            category_id="cat-1",
            category_name="Gadgets",
            source_transaction_id="txn-123",
            source_order_id="order-456",
        )

        assert result is True

    def test_record_item_category_learning_multiple(self, temp_db: Database) -> None:
        """Can record multiple mappings for same item."""
        result1 = temp_db.record_item_category_learning("Widget", "cat-1", "Gadgets")
        result2 = temp_db.record_item_category_learning("Widget", "cat-2", "Electronics")

        assert result1 is True
        assert result2 is True

        dist = temp_db.get_item_category_distribution("Widget")
        assert len(dist) == 2

    def test_get_item_category_distribution_empty(self, temp_db: Database) -> None:
        """Empty item returns empty dict."""
        result = temp_db.get_item_category_distribution("Unknown Item")
        assert result == {}

    def test_get_item_category_distribution(self, temp_db: Database) -> None:
        """Can get category distribution for item."""
        temp_db.record_item_category_learning("USB Cable", "cat-1", "Electronics")
        temp_db.record_item_category_learning("USB Cable", "cat-2", "Office", source_order_id="o2")

        dist = temp_db.get_item_category_distribution("USB Cable")

        assert "cat-1" in dist
        assert dist["cat-1"]["name"] == "Electronics"
        assert dist["cat-1"]["count"] == 1

    def test_get_item_category_distribution_normalized(self, temp_db: Database) -> None:
        """Distribution matches on normalized item name."""
        temp_db.record_item_category_learning("USB-C CABLE", "cat-1", "Electronics")

        # Should match with different case
        dist = temp_db.get_item_category_distribution("usb-c cable")
        assert len(dist) == 1

    def test_get_all_item_category_mappings_empty(self, temp_db: Database) -> None:
        """Empty database returns empty list."""
        result = temp_db.get_all_item_category_mappings()
        assert result == []

    def test_get_all_item_category_mappings(self, temp_db: Database) -> None:
        """Can get all item mappings."""
        temp_db.record_item_category_learning("Widget A", "cat-1", "Gadgets")
        temp_db.record_item_category_learning("Widget B", "cat-2", "Electronics")

        result = temp_db.get_all_item_category_mappings()

        assert len(result) == 2
        names = {r["item_name"] for r in result}
        assert "Widget A" in names
        assert "Widget B" in names

    def test_get_all_item_category_mappings_search(self, temp_db: Database) -> None:
        """Can search item mappings."""
        temp_db.record_item_category_learning("USB Cable", "cat-1", "Electronics")
        temp_db.record_item_category_learning("Keyboard", "cat-1", "Electronics")

        result = temp_db.get_all_item_category_mappings(search_term="USB")

        assert len(result) == 1
        assert result[0]["item_name"] == "USB Cable"

    def test_get_all_item_category_mappings_category_filter(self, temp_db: Database) -> None:
        """Can filter by category."""
        temp_db.record_item_category_learning("Item A", "cat-1", "Electronics")
        temp_db.record_item_category_learning("Item B", "cat-2", "Groceries")

        result = temp_db.get_all_item_category_mappings(category_filter="Groceries")

        assert len(result) == 1
        assert result[0]["item_name"] == "Item B"

    def test_get_item_category_history_count(self, temp_db: Database) -> None:
        """Can count item history records."""
        assert temp_db.get_item_category_history_count() == 0

        temp_db.record_item_category_learning("Item A", "cat-1", "Cat1")
        temp_db.record_item_category_learning("Item B", "cat-2", "Cat2")

        assert temp_db.get_item_category_history_count() == 2

    def test_get_unique_item_count(self, temp_db: Database) -> None:
        """Can count unique items."""
        assert temp_db.get_unique_item_count() == 0

        # Same item, different categories
        temp_db.record_item_category_learning("Widget", "cat-1", "Cat1")
        temp_db.record_item_category_learning("Widget", "cat-2", "Cat2")
        temp_db.record_item_category_learning("Other", "cat-1", "Cat1")

        # Should be 2 unique items
        assert temp_db.get_unique_item_count() == 2
