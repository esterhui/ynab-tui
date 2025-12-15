"""Pending changes (delta table) database operations for undo support."""

from __future__ import annotations

from typing import Any, Optional

from .base import DatabaseMixin, _now_iso


class PendingChangesMixin(DatabaseMixin):
    """Mixin for pending changes (undo) database operations."""

    def create_pending_change(
        self,
        transaction_id: str,
        new_category_id: Optional[str],
        new_category_name: Optional[str],
        original_category_id: Optional[str],
        original_category_name: Optional[str],
        change_type: str = "category",
        new_approved: Optional[bool] = None,
        original_approved: Optional[bool] = None,
    ) -> bool:
        """Create or replace a pending category change.

        If a pending change already exists for this transaction, replace it
        (latest wins behavior).

        Args:
            transaction_id: YNAB transaction ID.
            new_category_id: New category ID to apply.
            new_category_name: New category name.
            original_category_id: Original category ID (for undo).
            original_category_name: Original category name (for undo).
            change_type: Type of change ('category' or 'split').
            new_approved: New approval status (True = approved).
            original_approved: Original approval status (for undo).

        Returns:
            True if created/replaced successfully.
        """
        budget_id = getattr(self, "budget_id", None)

        with self._connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO pending_changes
                (transaction_id, budget_id, change_type, new_category_id, new_category_name,
                 original_category_id, original_category_name,
                 new_approved, original_approved, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transaction_id,
                    budget_id,
                    change_type,
                    new_category_id,
                    new_category_name,
                    original_category_id,
                    original_category_name,
                    new_approved,
                    original_approved,
                    _now_iso(),
                ),
            )
            return True

    def get_pending_change(self, transaction_id: str) -> Optional[dict[str, Any]]:
        """Get pending change for a transaction if exists.

        Args:
            transaction_id: YNAB transaction ID.

        Returns:
            Dict with change details or None if no pending change.
        """
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT id, transaction_id, change_type,
                       new_category_id, new_category_name,
                       original_category_id, original_category_name,
                       new_approved, original_approved,
                       created_at
                FROM pending_changes
                WHERE transaction_id = ?
                """,
                (transaction_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_all_pending_changes(self) -> list[dict[str, Any]]:
        """Get all pending changes with transaction details.

        Returns:
            List of dicts with pending change and transaction info.
        """
        budget_id = getattr(self, "budget_id", None)
        conditions: list[str] = []
        params: list[str] = []

        if budget_id:
            conditions.append("pc.budget_id = ?")
            params.append(budget_id)

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    pc.id, pc.transaction_id, pc.change_type,
                    pc.new_category_id, pc.new_category_name,
                    pc.original_category_id, pc.original_category_name,
                    pc.new_approved, pc.original_approved,
                    pc.created_at,
                    t.date, t.amount, t.payee_name, t.account_name, t.approved
                FROM pending_changes pc
                JOIN ynab_transactions t ON pc.transaction_id = t.id
                {where_clause}
                ORDER BY t.date DESC
                """,
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    def delete_pending_change(self, transaction_id: str) -> bool:
        """Delete pending change for a transaction (for undo).

        Args:
            transaction_id: YNAB transaction ID.

        Returns:
            True if deleted, False if not found.
        """
        with self._connection() as conn:
            cursor = conn.execute(
                "DELETE FROM pending_changes WHERE transaction_id = ?",
                (transaction_id,),
            )
            return cursor.rowcount > 0

    def get_pending_change_count(self) -> int:
        """Get count of pending changes.

        Returns:
            Number of pending changes.
        """
        budget_id = getattr(self, "budget_id", None)
        if budget_id:
            where_clause = f"WHERE budget_id = '{budget_id}'"
        else:
            where_clause = ""

        with self._connection() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) as count FROM pending_changes {where_clause}"
            ).fetchone()
            return row["count"] if row else 0

    def apply_pending_change(self, transaction_id: str) -> bool:
        """Apply pending change to ynab_transactions and cleanup.

        Called after successful push to YNAB. Updates ynab_transactions
        with the new category and removes the pending change record.

        Args:
            transaction_id: Transaction ID to finalize.

        Returns:
            True if applied and cleaned up.
        """
        with self._connection() as conn:
            change = conn.execute(
                "SELECT * FROM pending_changes WHERE transaction_id = ?",
                (transaction_id,),
            ).fetchone()

            if not change:
                return False

            conn.execute(
                """
                UPDATE ynab_transactions
                SET category_id = ?, category_name = ?,
                    approved = COALESCE(?, approved),
                    sync_status = 'synced', synced_at = ?
                WHERE id = ?
                """,
                (
                    change["new_category_id"],
                    change["new_category_name"],
                    change["new_approved"],
                    _now_iso(),
                    transaction_id,
                ),
            )

            conn.execute(
                "DELETE FROM pending_changes WHERE transaction_id = ?",
                (transaction_id,),
            )

            return True

    def clear_all_pending_changes(self) -> int:
        """Clear all pending changes.

        Returns:
            Number of pending changes cleared.
        """
        with self._connection() as conn:
            cursor = conn.execute("DELETE FROM pending_changes")
            return cursor.rowcount
