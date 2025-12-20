"""Pure action handlers for TUI - testable without Textual.

This module contains ActionResult and ActionHandler classes that wrap
the CategorizerService with a pure function interface. Each handler
method returns an ActionResult that the TUI can use for notifications.
"""

from dataclasses import dataclass
from typing import Optional

from src.models import Transaction
from src.services.categorizer import CategorizerService


@dataclass
class ActionResult:
    """Result of an action - pure data, no UI.

    Attributes:
        success: Whether the action succeeded.
        message: Human-readable message for display.
        transaction_id: ID of affected transaction (if applicable).
        error: Error message if action failed.
    """

    success: bool
    message: str
    transaction_id: Optional[str] = None
    error: Optional[str] = None

    @classmethod
    def ok(cls, message: str, transaction_id: Optional[str] = None) -> "ActionResult":
        """Create a successful result."""
        return cls(success=True, message=message, transaction_id=transaction_id)

    @classmethod
    def fail(cls, error: str, transaction_id: Optional[str] = None) -> "ActionResult":
        """Create a failed result."""
        return cls(success=False, message="", error=error, transaction_id=transaction_id)


class ActionHandler:
    """Pure business logic handlers - testable without UI.

    All methods return ActionResult instead of updating UI directly.
    The TUI layer can then display messages/errors appropriately.
    """

    def __init__(self, categorizer: CategorizerService):
        """Initialize handler with categorizer service.

        Args:
            categorizer: The CategorizerService to wrap.
        """
        self._categorizer = categorizer

    def categorize(
        self,
        transaction: Transaction,
        category_id: str,
        category_name: str,
    ) -> ActionResult:
        """Apply category to transaction.

        Args:
            transaction: Transaction to categorize.
            category_id: YNAB category ID.
            category_name: Human-readable category name.

        Returns:
            ActionResult with success status and message.
        """
        try:
            self._categorizer.apply_category(transaction, category_id, category_name)
            return ActionResult.ok(
                message=f"Categorized as: {category_name}",
                transaction_id=transaction.id,
            )
        except Exception as e:
            return ActionResult.fail(str(e), transaction.id)

    def categorize_batch(
        self,
        transactions: list[Transaction],
        category_id: str,
        category_name: str,
    ) -> ActionResult:
        """Apply category to multiple transactions.

        Args:
            transactions: List of transactions to categorize.
            category_id: YNAB category ID.
            category_name: Human-readable category name.

        Returns:
            ActionResult with count of successful/failed operations.
        """
        if not transactions:
            return ActionResult.fail("No transactions to categorize")

        succeeded = 0
        errors: list[str] = []

        for txn in transactions:
            try:
                self._categorizer.apply_category(txn, category_id, category_name)
                succeeded += 1
            except Exception as e:
                errors.append(f"{txn.payee_name}: {e}")

        total = len(transactions)
        if succeeded == total:
            return ActionResult.ok(f"Categorized {succeeded} transactions as: {category_name}")
        elif succeeded > 0:
            return ActionResult.ok(
                f"Categorized {succeeded}/{total} transactions ({total - succeeded} failed)"
            )
        else:
            return ActionResult.fail(
                f"Failed to categorize any transactions: {errors[0] if errors else 'Unknown error'}"
            )

    def approve(self, transaction: Transaction) -> ActionResult:
        """Approve a transaction.

        Args:
            transaction: Transaction to approve.

        Returns:
            ActionResult with success status and message.
        """
        try:
            result = self._categorizer.approve_transaction(transaction)
            if result.approved:
                return ActionResult.ok("Transaction approved", transaction.id)
            else:
                return ActionResult.ok("Transaction already approved", transaction.id)
        except Exception as e:
            return ActionResult.fail(str(e), transaction.id)

    def approve_batch(self, transactions: list[Transaction]) -> ActionResult:
        """Approve multiple transactions.

        Args:
            transactions: List of transactions to approve.

        Returns:
            ActionResult with count of successful/failed operations.
        """
        if not transactions:
            return ActionResult.fail("No transactions to approve")

        succeeded = 0
        already_approved = 0
        errors: list[str] = []

        for txn in transactions:
            try:
                result = self._categorizer.approve_transaction(txn)
                if result.approved:
                    succeeded += 1
                else:
                    already_approved += 1
            except Exception as e:
                errors.append(f"{txn.payee_name}: {e}")

        total = len(transactions)
        if succeeded + already_approved == total:
            if already_approved > 0 and succeeded == 0:
                return ActionResult.ok("All transactions were already approved")
            elif already_approved > 0:
                return ActionResult.ok(
                    f"Approved {succeeded} transactions ({already_approved} already approved)"
                )
            return ActionResult.ok(f"Approved {succeeded} transactions")
        else:
            return ActionResult.fail(
                f"Failed to approve some transactions: {errors[0] if errors else 'Unknown error'}"
            )

    def undo(self, transaction: Transaction) -> ActionResult:
        """Undo pending change on a transaction.

        Args:
            transaction: Transaction with pending change to undo.

        Returns:
            ActionResult with success status and restored state info.
        """
        try:
            # Get original category before undo for the message
            old_category = transaction.category_name

            result = self._categorizer.undo_category(transaction)

            # Get new (restored) category
            new_category = result.category_name or "Uncategorized"

            if old_category and old_category != new_category:
                return ActionResult.ok(
                    f"Undone: restored to '{new_category}'",
                    transaction.id,
                )
            else:
                return ActionResult.ok("Change undone", transaction.id)
        except Exception as e:
            return ActionResult.fail(str(e), transaction.id)

    def undo_batch(self, transactions: list[Transaction]) -> ActionResult:
        """Undo pending changes on multiple transactions.

        Args:
            transactions: List of transactions with pending changes to undo.

        Returns:
            ActionResult with count of successful/failed operations.
        """
        if not transactions:
            return ActionResult.fail("No transactions to undo")

        succeeded = 0
        errors: list[str] = []

        for txn in transactions:
            try:
                self._categorizer.undo_category(txn)
                succeeded += 1
            except Exception as e:
                errors.append(f"{txn.payee_name}: {e}")

        total = len(transactions)
        if succeeded == total:
            return ActionResult.ok(f"Undone {succeeded} transactions")
        elif succeeded > 0:
            return ActionResult.ok(
                f"Undone {succeeded}/{total} transactions ({total - succeeded} failed)"
            )
        else:
            return ActionResult.fail(
                f"Failed to undo any transactions: {errors[0] if errors else 'Unknown error'}"
            )

    def update_memo(
        self,
        transaction: Transaction,
        new_memo: str,
    ) -> ActionResult:
        """Update transaction memo.

        Args:
            transaction: Transaction to update.
            new_memo: New memo text (can be empty to clear).

        Returns:
            ActionResult with success status and message.
        """
        try:
            self._categorizer.apply_memo(transaction, new_memo)
            if new_memo:
                return ActionResult.ok("Memo updated", transaction.id)
            else:
                return ActionResult.ok("Memo cleared", transaction.id)
        except Exception as e:
            return ActionResult.fail(str(e), transaction.id)

    def split(
        self,
        transaction: Transaction,
        splits: list[dict],
    ) -> ActionResult:
        """Apply split categories to a transaction.

        Args:
            transaction: Transaction to split.
            splits: List of split dictionaries with category_id, category_name, amount.

        Returns:
            ActionResult with success status and message.
        """
        try:
            if not splits:
                return ActionResult.fail("No splits provided", transaction.id)

            self._categorizer.apply_split_categories(transaction, splits)
            return ActionResult.ok(
                f"Split into {len(splits)} categories",
                transaction.id,
            )
        except Exception as e:
            return ActionResult.fail(str(e), transaction.id)
