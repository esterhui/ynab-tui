"""Repository protocols for database operations.

These protocols define interfaces for database operations, enabling
dependency injection and easier testing with mock implementations.
"""

from datetime import datetime
from typing import Any, Optional, Protocol

from .database import AmazonOrderCache
from .models import TransactionFilter


class AmazonOrderRepositoryProtocol(Protocol):
    """Protocol for Amazon order data access."""

    def get_cached_orders_by_date_range(
        self, start: datetime, end: datetime
    ) -> list[AmazonOrderCache]:
        """Get orders within date range.

        Args:
            start: Start of date range (inclusive).
            end: End of date range (inclusive).

        Returns:
            List of orders within the range.
        """
        ...

    def get_order_items_with_prices(self, order_id: str) -> list[dict[str, Any]]:
        """Get items for an order with price information.

        Args:
            order_id: Amazon order ID.

        Returns:
            List of item dicts with item_name, item_price, quantity.
        """
        ...


class TransactionRepositoryProtocol(Protocol):
    """Protocol for YNAB transaction data access."""

    def get_transactions(
        self,
        filter: Optional[TransactionFilter] = None,
        payee_filter: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Query transactions with optional filters.

        Args:
            filter: Transaction filter criteria.
            payee_filter: Optional payee name filter.

        Returns:
            List of transaction dicts.
        """
        ...

    def get_transaction(self, txn_id: str) -> Optional[dict[str, Any]]:
        """Get single transaction by ID.

        Args:
            txn_id: Transaction ID.

        Returns:
            Transaction dict or None if not found.
        """
        ...


class PendingChangesRepositoryProtocol(Protocol):
    """Protocol for pending changes (delta table) operations."""

    def create_change(
        self,
        txn_id: str,
        new_values: dict[str, Any],
        original_values: dict[str, Any],
        change_type: str,
    ) -> bool:
        """Create or update a pending change.

        Args:
            txn_id: Transaction ID.
            new_values: New field values.
            original_values: Original field values (for undo).
            change_type: Type of change (e.g., 'category', 'memo', 'split').

        Returns:
            True if change was created/updated.
        """
        ...

    def get_change(self, txn_id: str) -> Optional[dict[str, Any]]:
        """Get pending change for a transaction.

        Args:
            txn_id: Transaction ID.

        Returns:
            Change dict or None if no pending change.
        """
        ...

    def delete_change(self, txn_id: str) -> bool:
        """Delete pending change for a transaction.

        Args:
            txn_id: Transaction ID.

        Returns:
            True if change was deleted.
        """
        ...

    def get_all_changes(self) -> list[dict[str, Any]]:
        """Get all pending changes.

        Returns:
            List of pending change dicts.
        """
        ...


class HistoryRepositoryProtocol(Protocol):
    """Protocol for categorization history operations."""

    def add_categorization(
        self,
        transaction_id: str,
        payee_name: str,
        category_id: str,
        category_name: str,
        amazon_items: Optional[list[str]] = None,
    ) -> None:
        """Record a categorization decision.

        Args:
            transaction_id: Transaction ID.
            payee_name: Payee name.
            category_id: Category ID.
            category_name: Category name.
            amazon_items: Optional list of Amazon item names.
        """
        ...

    def get_payee_category_distributions_batch(
        self, payee_names: list[str]
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """Get category distributions for multiple payees.

        Args:
            payee_names: List of payee names.

        Returns:
            Dict mapping payee -> category_id -> {name, count, pct}.
        """
        ...
