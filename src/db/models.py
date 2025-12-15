"""Database models and data classes."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class CategorizationRecord:
    """A historical categorization decision."""

    id: Optional[int]
    payee_name: str
    payee_normalized: str
    amount: Optional[float]
    category_name: str
    category_id: str
    amazon_items: Optional[list[str]]
    created_at: datetime


@dataclass
class AmazonOrderCache:
    """Cached Amazon order data."""

    order_id: str
    order_date: datetime
    total: float
    items: list[str]
    fetched_at: datetime


@dataclass
class TransactionFilter:
    """Filter criteria for querying YNAB transactions.

    Replaces the 8 boolean/optional parameters with a single typed object.
    All fields default to None/False for no filtering.
    """

    approved_only: bool = False
    unapproved_only: bool = False
    uncategorized_only: bool = False
    pending_push_only: bool = False
    payee_filter: Optional[str] = None
    category_id_filter: Optional[str] = None
    limit: Optional[int] = None
    exclude_subtransactions: bool = True
    since_date: Optional[datetime] = None

    @classmethod
    def uncategorized(cls) -> "TransactionFilter":
        """Create a filter for uncategorized transactions."""
        return cls(uncategorized_only=True)

    @classmethod
    def pending(cls) -> "TransactionFilter":
        """Create a filter for pending push transactions."""
        return cls(pending_push_only=True)

    @classmethod
    def approved(cls) -> "TransactionFilter":
        """Create a filter for approved transactions."""
        return cls(approved_only=True)

    @classmethod
    def unapproved(cls) -> "TransactionFilter":
        """Create a filter for unapproved (new) transactions."""
        return cls(unapproved_only=True)
