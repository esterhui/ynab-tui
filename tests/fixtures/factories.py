"""Factory functions for creating test objects.

These functions create test data without pytest fixtures,
making them importable from any test file.
"""

from datetime import datetime
from typing import Any

from ynab_tui.db.database import AmazonOrderCache
from ynab_tui.services.matching import TransactionInfo


def make_transaction_info(
    transaction_id: str = "txn-001",
    amount: float = 44.99,
    date: datetime | None = None,
    date_str: str | None = None,
    display_amount: str | None = None,
    is_split: bool = False,
    category_id: str | None = None,
    category_name: str | None = None,
    approved: bool = False,
) -> TransactionInfo:
    """Factory function for creating TransactionInfo test objects."""
    if date is None:
        date = datetime(2025, 11, 27)
    if date_str is None:
        date_str = date.strftime("%Y-%m-%d")
    if display_amount is None:
        display_amount = f"-${amount:,.2f}"

    return TransactionInfo(
        transaction_id=transaction_id,
        amount=amount,
        date=date,
        date_str=date_str,
        display_amount=display_amount,
        is_split=is_split,
        category_id=category_id,
        category_name=category_name,
        approved=approved,
    )


def make_amazon_order(
    order_id: str = "order-001",
    order_date: datetime | None = None,
    total: float = 44.99,
    items: list[str] | None = None,
    fetched_at: datetime | None = None,
) -> AmazonOrderCache:
    """Factory function for creating AmazonOrderCache test objects."""
    if order_date is None:
        order_date = datetime(2025, 11, 24)
    if items is None:
        items = ["Test Item"]
    if fetched_at is None:
        fetched_at = datetime.now()

    return AmazonOrderCache(
        order_id=order_id,
        order_date=order_date,
        total=total,
        items=items,
        fetched_at=fetched_at,
    )


class MockAmazonOrderRepo:
    """Mock implementation of AmazonOrderRepositoryProtocol."""

    def __init__(self, orders: list[AmazonOrderCache] | None = None):
        self._orders = orders or []
        self._items: dict[str, list[dict[str, Any]]] = {}

    def add_order(self, order: AmazonOrderCache) -> None:
        """Add an order for testing."""
        self._orders.append(order)

    def add_items(self, order_id: str, items: list[dict[str, Any]]) -> None:
        """Add items with prices for an order."""
        self._items[order_id] = items

    def get_cached_orders_by_date_range(
        self, start: datetime, end: datetime
    ) -> list[AmazonOrderCache]:
        """Get orders within date range."""
        return [o for o in self._orders if start <= o.order_date <= end]

    def get_order_items_with_prices(self, order_id: str) -> list[dict[str, Any]]:
        """Get items for an order."""
        return self._items.get(order_id, [])
