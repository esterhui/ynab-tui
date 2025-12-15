"""Protocol definitions for client interfaces.

These protocols define the expected interface for real and mock clients,
ensuring type safety and interface consistency.
"""

from datetime import datetime
from typing import Any, Optional, Protocol

from ..models import (
    AmazonOrder,
    CategoryList,
    Transaction,
)


class YNABClientProtocol(Protocol):
    """Protocol defining the YNAB client interface."""

    def get_categories(self) -> CategoryList:
        """Fetch all categories from YNAB."""
        pass

    def get_uncategorized_transactions(
        self,
        since_date: Optional[datetime] = None,
    ) -> list[Transaction]:
        """Fetch transactions that need categorization."""
        pass

    def get_unapproved_transactions(
        self,
        since_date: Optional[datetime] = None,
    ) -> list[Transaction]:
        """Fetch transactions that need approval."""
        pass

    def get_all_pending_transactions(
        self,
        since_date: Optional[datetime] = None,
    ) -> list[Transaction]:
        """Fetch all transactions needing attention."""
        pass

    def get_recent_transactions(
        self,
        days: int = 30,
        since_date: Optional[datetime] = None,
    ) -> list[Transaction]:
        """Fetch recent transactions."""
        pass

    def get_all_transactions(
        self,
        since_date: Optional[datetime] = None,
    ) -> list[Transaction]:
        """Fetch all transactions."""
        pass

    def update_transaction_category(
        self,
        transaction_id: str,
        category_id: str,
        approve: bool = True,
    ) -> Transaction:
        """Update a transaction's category."""
        pass

    def create_split_transaction(
        self,
        transaction_id: str,
        splits: list[dict[str, Any]],
        approve: bool = True,
    ) -> Transaction:
        """Create a split transaction."""
        pass

    def approve_transaction(self, transaction_id: str) -> Transaction:
        """Approve a transaction."""
        pass

    def get_budgets(self) -> list[dict[str, Any]]:
        """Get available budgets."""
        pass

    def set_budget_id(self, budget_id: str) -> None:
        """Set the budget ID to use for all operations."""
        pass

    def get_current_budget_id(self) -> str:
        """Get the current resolved budget ID."""
        pass

    def get_budget_name(self, budget_id: Optional[str] = None) -> str:
        """Get the name of a budget by ID."""
        pass

    def test_connection(self) -> dict[str, Any]:
        """Test API connection."""
        pass


class AmazonClientProtocol(Protocol):
    """Protocol defining the Amazon client interface."""

    def get_orders_for_year(self, year: int) -> list[AmazonOrder]:
        """Fetch all orders for a specific year."""
        pass

    def get_orders_in_range(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[AmazonOrder]:
        """Fetch orders within a date range."""
        pass

    def get_recent_orders(self, days: int = 30) -> list[AmazonOrder]:
        """Fetch orders from the last N days."""
        pass

    def find_matching_order(
        self,
        amount: float,
        date: datetime,
        window_days: int = 3,
    ) -> Optional[AmazonOrder]:
        """Find an order matching the given amount and date."""
        pass
