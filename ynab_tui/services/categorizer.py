"""Categorization service.

Orchestrates the full categorization workflow:
1. Fetch uncategorized transactions from DB (synced via 'pull')
2. Enrich Amazon transactions with order details
3. Apply categories based on user selections

DB-first architecture: Run 'pull' to sync data, then all operations use local SQLite.
"""

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Optional, Union

from ..config import Config
from ..db.database import Database, TransactionFilter
from ..models import (
    Category,
    CategoryGroup,
    CategoryList,
    Transaction,
    TransactionBatch,
)
from ..utils import parse_to_datetime
from .matcher import TransactionMatcher

if TYPE_CHECKING:
    from ..clients import MockYNABClient, YNABClient

logger = logging.getLogger(__name__)


class CategorizerService:
    """Main service for transaction categorization."""

    def __init__(
        self,
        config: Config,
        ynab_client: Union["YNABClient", "MockYNABClient"],
        db: Database,
    ):
        """Initialize categorizer service.

        Args:
            config: Application configuration.
            ynab_client: YNAB API client.
            db: Database for history and cached Amazon orders.
        """
        self._config = config
        self._ynab = ynab_client
        self._db = db

        self._matcher = TransactionMatcher(
            db=db,
            categorization_config=config.categorization,
            payees_config=config.payees,
        )

        self._categories: Optional[CategoryList] = None

    @staticmethod
    def _format_payee_history_summary(history: dict) -> str:
        """Format payee history as a summary string.

        Args:
            history: Dict of category_name -> {count, percentage, ...}

        Returns:
            Summary like "85% Groceries, 10% Electronics" (top 2 categories)
        """
        parts = []
        for cat, stats in sorted(history.items(), key=lambda x: x[1]["count"], reverse=True)[:2]:
            pct = stats["percentage"] * 100
            parts.append(f"{pct:.0f}% {cat}")
        return ", ".join(parts)

    def _get_original_values(
        self, transaction: "Transaction", fields: list[str] | None = None
    ) -> dict[str, str | bool | None]:
        """Get original values for a transaction, preserving first originals if pending.

        When a transaction already has a pending change, we keep the very first
        original values (from DB before any local changes). This ensures undo
        restores to the true original state.

        Args:
            transaction: The transaction to get original values for.
            fields: Specific fields to get originals for. If None, gets all standard fields.

        Returns:
            Dict with original field values (category_id, category_name, approved, memo).
        """
        if fields is None:
            fields = ["category_id", "category_name", "approved", "memo"]

        existing_pending = self._db.get_pending_change(transaction.id)
        if existing_pending:
            # Keep the very first original values from the pending change's original_values
            orig_values = existing_pending.get("original_values", {})
            result = {}
            for field in fields:
                if field in orig_values:
                    result[field] = orig_values[field]
                # Fallback to legacy columns for backward compatibility
                elif field == "category_id" and existing_pending.get("original_category_id"):
                    result[field] = existing_pending["original_category_id"]
                elif field == "category_name" and existing_pending.get("original_category_name"):
                    result[field] = existing_pending["original_category_name"]
                elif field == "approved" and existing_pending.get("original_approved") is not None:
                    result[field] = existing_pending["original_approved"]
                else:
                    # Field not in pending change - get from transaction
                    result[field] = getattr(transaction, field, None)
            return result

        # First change - capture current values as original
        return {field: getattr(transaction, field, None) for field in fields}

    def _db_row_to_transaction(self, row: dict) -> Transaction:
        """Convert a database row to a Transaction object.

        Args:
            row: Dictionary from db.get_ynab_transactions().

        Returns:
            Transaction object.
        """
        return Transaction(
            id=row["id"],
            date=parse_to_datetime(row["date"]),
            amount=row["amount"],
            payee_name=row["payee_name"] or "",
            payee_id=row.get("payee_id"),
            memo=row.get("memo"),
            account_name=row.get("account_name"),
            account_id=row.get("account_id"),
            category_id=row.get("category_id"),
            category_name=row.get("category_name"),
            approved=bool(row.get("approved", False)),
            cleared=row.get("cleared", "uncleared"),
            is_split=bool(row.get("is_split", False)),
            sync_status=row.get("sync_status", "synced"),
            transfer_account_id=row.get("transfer_account_id"),
            transfer_account_name=row.get("transfer_account_name"),
            debt_transaction_type=row.get("debt_transaction_type"),
        )

    def _db_categories_to_list(self, groups: list[dict]) -> CategoryList:
        """Convert database category groups to CategoryList model.

        Args:
            groups: List of group dicts from db.get_categories().

        Returns:
            CategoryList object.
        """
        category_groups = []
        for group in groups:
            categories = [
                Category(
                    id=cat["id"],
                    name=cat["name"],
                    group_id=cat["group_id"],
                    group_name=cat["group_name"],
                    hidden=cat.get("hidden", False),
                    deleted=cat.get("deleted", False),
                )
                for cat in group.get("categories", [])
            ]
            category_groups.append(
                CategoryGroup(
                    id=group["id"],
                    name=group["name"],
                    categories=categories,
                )
            )
        return CategoryList(groups=category_groups)

    @property
    def categories(self) -> CategoryList:
        """Get cached categories from database.

        Categories must be synced via 'pull' first.
        """
        if self._categories is None:
            db_groups = self._db.get_categories()
            self._categories = self._db_categories_to_list(db_groups)
        return self._categories

    def refresh_categories(self) -> CategoryList:
        """Force refresh categories from database."""
        db_groups = self._db.get_categories()
        self._categories = self._db_categories_to_list(db_groups)
        return self._categories

    def get_config(self) -> Config:
        """Get the application configuration.

        Returns:
            Application config object.
        """
        return self._config

    def get_search_match_style(self) -> str:
        """Get the search match style setting.

        Returns:
            Match style: 'prefix', 'contains', or 'fuzzy'.
        """
        return self._config.display.search_match_style

    def get_category_groups(self) -> list[CategoryGroup]:
        """Get list of category groups.

        Returns:
            List of CategoryGroup objects.
        """
        return self.categories.groups

    def get_pending_transactions(self) -> TransactionBatch:
        """Fetch and enrich all pending (uncategorized) transactions from database.

        Transactions must be synced via 'pull' first.

        Returns:
            TransactionBatch with enriched transactions.
        """
        # Fetch uncategorized transactions from database
        rows = self._db.get_ynab_transactions(filter=TransactionFilter.uncategorized())
        transactions = [self._db_row_to_transaction(row) for row in rows]

        # Enrich with Amazon order data
        transactions = self._matcher.enrich_transactions(transactions)

        # Batch fetch all payee histories (1 query instead of N)
        payee_names = [txn.payee_name for txn in transactions]
        all_histories = self._db.get_payee_category_distributions_batch(payee_names)

        # Add historical context for each transaction (O(1) lookup)
        for txn in transactions:
            history = all_histories.get(txn.payee_name)
            if history:
                txn.payee_history_summary = self._format_payee_history_summary(history)

        return TransactionBatch(transactions=transactions)

    def get_transactions(
        self,
        filter_mode: str = "all",
        since_date: Optional[datetime] = None,
        category_id: Optional[str] = None,
        payee_name: Optional[str] = None,
    ) -> TransactionBatch:
        """Fetch transactions from database with optional filtering.

        Args:
            filter_mode: One of 'all', 'approved', 'new', 'uncategorized', 'pending'.
                - 'all': All transactions
                - 'approved': Only approved transactions
                - 'new': Only unapproved (new) transactions
                - 'uncategorized': Only uncategorized transactions
                - 'pending': Only transactions pending push to YNAB
            since_date: Only return transactions on or after this date.
            category_id: Filter by specific category ID.
            payee_name: Filter by payee name (partial match).

        Returns:
            TransactionBatch with transactions.
        """
        # Build filter based on mode
        filter_map = {
            "uncategorized": TransactionFilter.uncategorized(),
            "pending": TransactionFilter.pending(),
            "unapproved": TransactionFilter.unapproved(),
        }
        txn_filter = filter_map.get(filter_mode, TransactionFilter())

        # Apply since_date if provided
        if since_date:
            txn_filter.since_date = since_date

        # Apply category filter if provided
        if category_id:
            txn_filter.category_id_filter = category_id

        # Apply payee filter if provided
        if payee_name:
            txn_filter.payee_filter = payee_name

        rows = self._db.get_ynab_transactions(filter=txn_filter)

        transactions = [self._db_row_to_transaction(row) for row in rows]

        # Enrich with Amazon order data
        transactions = self._matcher.enrich_transactions(transactions)

        return TransactionBatch(transactions=transactions)

    def apply_category(
        self,
        transaction: Transaction,
        category_id: str,
        category_name: str,
    ) -> Transaction:
        """Apply a category to a transaction locally (marks as pending_push).

        DB-first: Changes are stored in pending_changes table (delta) and
        synced to YNAB via 'push'. Original values are preserved for undo.

        Args:
            transaction: Transaction to update.
            category_id: YNAB category ID.
            category_name: Category name for history.

        Returns:
            Updated transaction.
        """
        # Get original values (preserves first originals if already pending)
        originals = self._get_original_values(
            transaction, ["category_id", "category_name", "approved"]
        )

        # Create pending change in delta table (preserves original for undo)
        self._db.create_pending_change(
            transaction_id=transaction.id,
            new_values={
                "category_id": category_id,
                "category_name": category_name,
                "approved": True,  # Auto-approve when categorizing
            },
            original_values=originals,
            change_type="update",
        )

        # Record in history for learning
        self._db.add_categorization(
            payee_name=transaction.payee_name,
            category_name=category_name,
            category_id=category_id,
            amount=transaction.amount,
            amazon_items=transaction.amazon_items if transaction.is_amazon else None,
        )

        # Update the transaction object to reflect the change (for UI display)
        transaction.category_id = category_id
        transaction.category_name = category_name
        transaction.sync_status = "pending_push"
        transaction.approved = True  # Auto-approve when categorizing

        return transaction

    def apply_split_categories(
        self,
        transaction: Transaction,
        splits: list[dict],
    ) -> Transaction:
        """Apply split categories to a transaction locally (marks as pending_push).

        DB-first: Split is stored locally and synced to YNAB via 'push'.
        Original values are preserved in pending_changes for undo.

        Args:
            transaction: Transaction to split.
            splits: List of dicts with category_id, category_name, amount, memo.

        Returns:
            Updated transaction marked as split and pending_push.
        """
        # Get original values (preserves first originals if already pending)
        originals = self._get_original_values(
            transaction, ["category_id", "category_name", "approved"]
        )

        # Use "Split" to match YNAB's category name for split transactions
        split_category_name = "Split"

        # Create pending change record with split type
        self._db.create_pending_change(
            transaction_id=transaction.id,
            new_values={
                "category_id": None,  # Splits don't have a single category
                "category_name": split_category_name,
                "approved": True,  # Auto-approve when splitting
            },
            original_values=originals,
            change_type="split",
        )

        # Store split information in database for later push
        self._db.mark_pending_split(
            transaction_id=transaction.id,
            splits=splits,
            category_name=split_category_name,
        )

        # Record each categorization in history for learning
        for split in splits:
            if split.get("category_id") and split.get("category_name"):
                self._db.add_categorization(
                    payee_name=transaction.payee_name,
                    category_name=split["category_name"],
                    category_id=split["category_id"],
                    amount=split.get("amount", 0),
                    amazon_items=[split.get("memo", "")] if split.get("memo") else None,
                )

        # Update the transaction object to reflect the change
        transaction.is_split = True
        transaction.category_name = split_category_name
        transaction.sync_status = "pending_push"
        transaction.approved = True  # Auto-approve when splitting

        return transaction

    def undo_category(self, transaction: Transaction) -> Transaction:
        """Undo a pending category change.

        Restores the transaction to its original state by
        removing the pending change from the delta table.

        Args:
            transaction: Transaction with pending change to undo.

        Returns:
            Transaction restored to original state.

        Raises:
            ValueError: If no pending change exists for this transaction.
        """
        pending = self._db.get_pending_change(transaction.id)
        if not pending:
            raise ValueError("No pending change to undo for this transaction")

        # Delete the pending change
        self._db.delete_pending_change(transaction.id)

        # Also clear any pending splits if this was a split change
        if pending.get("change_type") == "split":
            self._db.clear_pending_splits(transaction.id)

        # Restore ALL original values from ynab_transactions table
        # (delta design doesn't modify it, so original values are preserved)
        original_txn = self._db.get_ynab_transaction(transaction.id)
        if original_txn:
            transaction.category_id = original_txn.get("category_id")
            transaction.category_name = original_txn.get("category_name")
            transaction.approved = original_txn.get("approved", False)
            transaction.memo = original_txn.get("memo")
        transaction.sync_status = "synced"
        transaction.is_split = False  # Restore non-split state

        return transaction

    def approve_transaction(self, transaction: Transaction) -> Transaction:
        """Approve a transaction locally (marks as pending_push).

        If transaction is already approved, this is a no-op and returns
        the transaction unchanged.

        Args:
            transaction: Transaction to approve.

        Returns:
            Updated transaction (or unchanged if already approved).
        """
        if transaction.approved:
            # Already approved - no-op
            return transaction

        # Get original values (preserves first originals if already pending)
        originals = self._get_original_values(transaction, ["approved"])

        # Create pending change for approval only
        self._db.create_pending_change(
            transaction_id=transaction.id,
            new_values={"approved": True},
            original_values=originals,
            change_type="update",
        )

        # Update the transaction object for UI display
        transaction.approved = True
        transaction.sync_status = "pending_push"

        return transaction

    def apply_memo(self, transaction: Transaction, memo: str) -> Transaction:
        """Apply a memo to a transaction locally (marks as pending_push).

        DB-first: Changes are stored in pending_changes table (delta) and
        synced to YNAB via 'push'. Original values are preserved for undo.

        Args:
            transaction: Transaction to update.
            memo: New memo text (can be empty string to clear memo).

        Returns:
            Updated transaction.
        """
        # Get original values (preserves first originals if already pending)
        originals = self._get_original_values(transaction, ["memo"])

        # Create pending change in delta table (preserves original for undo)
        self._db.create_pending_change(
            transaction_id=transaction.id,
            new_values={"memo": memo},
            original_values=originals,
            change_type="update",
        )

        # Update the transaction object to reflect the change (for UI display)
        transaction.memo = memo
        transaction.sync_status = "pending_push"

        return transaction

    def get_sync_status(self) -> dict[str, Optional[dict]]:
        """Get sync status for YNAB and Amazon.

        Returns:
            Dict with 'ynab' and 'amazon' sync states.
        """
        return {
            "ynab": self._db.get_sync_state("ynab"),
            "amazon": self._db.get_sync_state("amazon"),
        }

    def get_pending_changes(self) -> list[dict]:
        """Get all pending changes waiting to be pushed.

        Returns:
            List of pending change records.
        """
        return self._db.get_all_pending_changes()

    def get_amazon_order_items_with_prices(self, order_id: str) -> list[dict]:
        """Get Amazon order items with prices for a specific order.

        Args:
            order_id: The Amazon order ID.

        Returns:
            List of item dicts with name, quantity, and price.
        """
        return self._db.get_amazon_order_items_with_prices(order_id)

    def get_pending_splits(self, transaction_id: str) -> list[dict]:
        """Get pending splits for a transaction.

        Args:
            transaction_id: Transaction ID to look up.

        Returns:
            List of split dicts with category_id, category_name, amount, memo.
        """
        return self._db.get_pending_splits(transaction_id)

    def get_synced_splits(self, transaction_id: str) -> list[dict]:
        """Get synced subtransaction categories for a split transaction.

        For transactions already pushed to YNAB, the splits are stored as
        subtransactions in the database. This converts them to the same format
        as get_pending_splits() for use in the split screen.

        Args:
            transaction_id: Transaction ID to look up.

        Returns:
            List of split dicts with category_id, category_name, amount, memo.
        """
        subtransactions = self._db.get_subtransactions(transaction_id)
        return [
            {
                "category_id": sub["category_id"],
                "category_name": sub["category_name"],
                "amount": sub["amount"],
                "memo": sub.get("memo", ""),
            }
            for sub in subtransactions
        ]

    # Budget management methods

    def get_budgets(self) -> list[dict]:
        """Get available YNAB budgets.

        Returns:
            List of budget dicts with id, name, last_modified_on.
        """
        return self._ynab.get_budgets()

    def get_current_budget_id(self) -> str:
        """Get the current YNAB budget ID.

        Returns:
            The budget ID being used for operations.
        """
        return self._ynab.get_current_budget_id()

    def set_budget_id(self, budget_id: str) -> None:
        """Set the budget ID for all operations.

        Accepts either a UUID or budget name. Names are resolved to UUIDs.
        Updates both the YNAB client and the database filter.

        Args:
            budget_id: YNAB budget ID or budget name.
        """
        # Update YNAB client (handles name resolution)
        self._ynab.set_budget_id(budget_id)

        # Get the resolved UUID for the database
        resolved_id = self._ynab.get_current_budget_id()

        # Update database filter with the resolved UUID
        self._db.budget_id = resolved_id

        # Clear cached categories since they're budget-specific
        self._categories = None

    def get_budget_name(self, budget_id: str | None = None) -> str:
        """Get the name of a budget by ID.

        Args:
            budget_id: Budget UUID. If None, uses current budget.

        Returns:
            Budget name.
        """
        return self._ynab.get_budget_name(budget_id)
