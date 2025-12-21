"""Tests for AmazonMixin database operations.

These tests use a real temporary SQLite database.
"""

from datetime import datetime
from pathlib import Path

import pytest

from ynab_tui.db.database import AmazonOrderCache, Database


@pytest.fixture
def temp_db(tmp_path: Path) -> Database:
    """Create a temporary database for testing."""
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))
    yield db
    db.close()


class TestAmazonMixin:
    """Tests for Amazon order database operations."""

    def test_cache_amazon_order(self, temp_db: Database) -> None:
        """Can cache an Amazon order."""
        order_date = datetime(2025, 11, 24)

        temp_db.cache_amazon_order(
            order_id="order-001",
            order_date=order_date,
            total=44.99,
        )

        # Verify it was cached
        orders = temp_db.get_cached_orders_by_date_range(
            datetime(2025, 11, 1),
            datetime(2025, 11, 30),
        )

        assert len(orders) == 1
        assert orders[0].order_id == "order-001"
        assert orders[0].total == 44.99

    def test_cache_amazon_order_with_items(self, temp_db: Database) -> None:
        """Can cache order and items separately."""
        temp_db.cache_amazon_order("order-001", datetime(2025, 11, 24), 44.99)
        temp_db.upsert_amazon_order_items(
            "order-001",
            [
                {"name": "Item A", "price": 20.00, "quantity": 1},
                {"name": "Item B", "price": 24.99, "quantity": 1},
            ],
        )

        # Items should be joined in get_cached_orders_by_date_range
        orders = temp_db.get_cached_orders_by_date_range(
            datetime(2025, 11, 1),
            datetime(2025, 11, 30),
        )

        assert len(orders) == 1
        assert "Item A" in orders[0].items
        assert "Item B" in orders[0].items

    def test_get_cached_orders_by_date_range(self, temp_db: Database) -> None:
        """Can query orders by date range."""
        # Cache orders in different months
        temp_db.cache_amazon_order("o1", datetime(2025, 10, 15), 10.00)
        temp_db.cache_amazon_order("o2", datetime(2025, 11, 15), 20.00)
        temp_db.cache_amazon_order("o3", datetime(2025, 12, 15), 30.00)

        # Query November only
        orders = temp_db.get_cached_orders_by_date_range(
            datetime(2025, 11, 1),
            datetime(2025, 11, 30),
        )

        assert len(orders) == 1
        assert orders[0].order_id == "o2"

    def test_get_cached_orders_empty_range(self, temp_db: Database) -> None:
        """Empty date range returns empty list."""
        temp_db.cache_amazon_order("o1", datetime(2025, 11, 15), 20.00)

        orders = temp_db.get_cached_orders_by_date_range(
            datetime(2025, 1, 1),
            datetime(2025, 1, 31),
        )

        assert orders == []

    def test_get_amazon_order_items_with_prices(self, temp_db: Database) -> None:
        """Can get items with prices for an order."""
        temp_db.cache_amazon_order("order-001", datetime(2025, 11, 24), 44.99)
        temp_db.upsert_amazon_order_items(
            "order-001",
            [
                {"name": "Item A", "price": 20.00, "quantity": 1},
                {"name": "Item B", "price": 24.99, "quantity": 2},
            ],
        )

        items = temp_db.get_amazon_order_items_with_prices("order-001")

        assert len(items) == 2
        item_a = next(i for i in items if i["item_name"] == "Item A")
        assert item_a["item_price"] == 20.00
        assert item_a["quantity"] == 1

    def test_amazon_order_cache_model(self) -> None:
        """AmazonOrderCache dataclass works correctly."""
        order = AmazonOrderCache(
            order_id="o1",
            order_date=datetime(2025, 11, 24),
            total=44.99,
            items=["A", "B"],
            fetched_at=datetime.now(),
        )

        assert order.order_id == "o1"
        assert order.total == 44.99
        assert len(order.items) == 2

    def test_cache_updates_existing_order(self, temp_db: Database) -> None:
        """Caching same order ID should update it."""
        temp_db.cache_amazon_order("o1", datetime(2025, 11, 24), 10.00)
        temp_db.cache_amazon_order("o1", datetime(2025, 11, 24), 20.00)

        orders = temp_db.get_cached_orders_by_date_range(
            datetime(2025, 11, 1),
            datetime(2025, 11, 30),
        )

        assert len(orders) == 1
        assert orders[0].total == 20.00

    def test_multiple_orders_sorted_by_date(self, temp_db: Database) -> None:
        """Multiple orders should be returned (sorted by date desc)."""
        temp_db.cache_amazon_order("o1", datetime(2025, 11, 10), 10.00)
        temp_db.cache_amazon_order("o2", datetime(2025, 11, 20), 20.00)
        temp_db.cache_amazon_order("o3", datetime(2025, 11, 15), 15.00)

        orders = temp_db.get_cached_orders_by_date_range(
            datetime(2025, 11, 1),
            datetime(2025, 11, 30),
        )

        assert len(orders) == 3
        # Sorted by date DESC
        assert orders[0].order_id == "o2"  # Nov 20
        assert orders[1].order_id == "o3"  # Nov 15
        assert orders[2].order_id == "o1"  # Nov 10
