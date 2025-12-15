"""Transaction models for YNAB Categorizer."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..utils import truncate_list_display

# Payees that represent balance adjustments (don't need categories)
BALANCE_ADJUSTMENT_PAYEES = frozenset(
    {
        "Reconciliation Balance Adjustment",
        "Manual Balance Adjustment",
        "Starting Balance",
    }
)


@dataclass
class SubTransaction:
    """Represents a YNAB split transaction component.

    When a YNAB transaction is split into multiple categories, each split
    is represented as a SubTransaction. The parent transaction will have
    category_name="Split" and category_id=None.
    """

    id: str  # YNAB subtransaction ID
    transaction_id: str  # Parent transaction ID
    amount: float  # In dollars (negative for outflows)
    payee_id: Optional[str] = None
    payee_name: Optional[str] = None
    memo: Optional[str] = None
    category_id: Optional[str] = None
    category_name: Optional[str] = None

    @property
    def is_uncategorized(self) -> bool:
        """Check if subtransaction needs categorization."""
        return self.category_id is None or self.category_name is None

    @property
    def display_amount(self) -> str:
        """Format amount for display."""
        sign = "" if self.amount >= 0 else "-"
        return f"{sign}${abs(self.amount):,.2f}"


@dataclass
class Transaction:
    """Represents a YNAB transaction for categorization.

    This is our internal representation that combines YNAB transaction data
    with enrichment from Amazon orders.
    """

    # YNAB fields
    id: str  # YNAB transaction ID
    date: datetime
    amount: float  # In dollars (negative for outflows)
    payee_name: str
    payee_id: Optional[str] = None
    memo: Optional[str] = None
    account_name: Optional[str] = None
    account_id: Optional[str] = None

    # Current category (may be None if uncategorized)
    category_id: Optional[str] = None
    category_name: Optional[str] = None

    # Approval status
    approved: bool = False
    cleared: str = "uncleared"  # cleared, uncleared, reconciled

    # Split transaction support
    is_split: bool = False  # True if this transaction has subtransactions
    subtransactions: list[SubTransaction] = field(default_factory=list)

    # Sync status for local changes
    sync_status: str = "synced"  # 'synced', 'pending_push', 'conflict'

    # Transfer fields (transfers don't need categories)
    transfer_account_id: Optional[str] = None  # If set, this is a transfer
    transfer_account_name: Optional[str] = None  # Target account name for display
    debt_transaction_type: Optional[str] = None  # 'payment', 'refund', 'fee', 'interest'

    # Enrichment fields (populated by our services)
    is_amazon: bool = False
    amazon_items: list[str] = field(default_factory=list)
    amazon_order_id: Optional[str] = None

    # Historical context
    payee_history_summary: Optional[str] = None  # e.g., "85% Groceries"

    @property
    def is_transfer(self) -> bool:
        """Check if transaction is a transfer (doesn't need category)."""
        return self.transfer_account_id is not None

    @property
    def is_balance_adjustment(self) -> bool:
        """Check if transaction is a balance adjustment (doesn't need category)."""
        return self.payee_name in BALANCE_ADJUSTMENT_PAYEES

    @property
    def is_uncategorized(self) -> bool:
        """Check if transaction needs categorization.

        Transfers and balance adjustments don't need categories.
        """
        if self.is_transfer:
            return False
        if self.is_balance_adjustment:
            return False
        return self.category_id is None or self.category_name is None

    @property
    def is_unapproved(self) -> bool:
        """Check if transaction needs approval."""
        return not self.approved

    @property
    def needs_push(self) -> bool:
        """Check if transaction has local changes to push to YNAB."""
        return self.sync_status == "pending_push"

    @property
    def has_conflict(self) -> bool:
        """Check if transaction has a sync conflict."""
        return self.sync_status == "conflict"

    @property
    def display_amount(self) -> str:
        """Format amount for display."""
        sign = "" if self.amount >= 0 else "-"
        return f"{sign}${abs(self.amount):,.2f}"

    @property
    def display_date(self) -> str:
        """Format date for display."""
        return self.date.strftime("%Y-%m-%d")

    @property
    def enrichment_summary(self) -> str:
        """Summary of enrichment data for display."""
        if self.is_amazon and self.amazon_items:
            return truncate_list_display(self.amazon_items)
        elif self.payee_history_summary:
            return f"Historical: {self.payee_history_summary}"
        return ""


@dataclass
class TransactionBatch:
    """A batch of transactions for processing."""

    transactions: list[Transaction] = field(default_factory=list)

    @property
    def total_count(self) -> int:
        """Total number of transactions."""
        return len(self.transactions)

    @property
    def amazon_count(self) -> int:
        """Number of Amazon transactions."""
        return sum(1 for t in self.transactions if t.is_amazon)

    @property
    def other_count(self) -> int:
        """Number of non-Amazon transactions."""
        return self.total_count - self.amazon_count

    def filter_amazon(self) -> list[Transaction]:
        """Get only Amazon transactions."""
        return [t for t in self.transactions if t.is_amazon]

    def filter_other(self) -> list[Transaction]:
        """Get only non-Amazon transactions."""
        return [t for t in self.transactions if not t.is_amazon]
