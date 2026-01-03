"""Pending changes (delta table) database operations for undo support."""

from __future__ import annotations

import json
from typing import Any, Optional

from .base import DatabaseMixin, _now_iso


class PendingChangesMixin(DatabaseMixin):
    """Mixin for pending changes (undo) database operations.

    Uses JSON columns (new_values, original_values) for flexible field storage.
    Supports any updatable transaction field: category_id, category_name,
    approved, memo, and future fields without schema changes.
    """

    def create_pending_change(
        self,
        transaction_id: str,
        new_values: dict[str, Any],
        original_values: dict[str, Any],
        change_type: str = "update",
    ) -> bool:
        """Create or update a pending change for a transaction.

        If a pending change already exists for this transaction, merges
        the new values while preserving original values from the first change.

        Args:
            transaction_id: YNAB transaction ID.
            new_values: Dict of field names to new values.
                Supported fields: category_id, category_name, approved, memo.
            original_values: Dict of field names to original values (for undo).
            change_type: Type of change ('update' or 'split').

        Returns:
            True if created/updated successfully.
        """
        budget_id = getattr(self, "budget_id", None)

        with self._connection() as conn:
            # Check if there's an existing pending change
            existing = conn.execute(
                "SELECT new_values, original_values FROM pending_changes WHERE transaction_id = ?",
                (transaction_id,),
            ).fetchone()

            if existing:
                # Merge: update new_values, but preserve original_values from first change
                existing_new = json.loads(existing["new_values"]) if existing["new_values"] else {}
                existing_orig = (
                    json.loads(existing["original_values"]) if existing["original_values"] else {}
                )

                # Merge new values (latest wins)
                merged_new = {**existing_new, **new_values}
                # Preserve original values (first wins - only add keys not already present)
                merged_orig = {**original_values, **existing_orig}
                # But ensure we only keep originals for keys we're actually changing
                merged_orig = {k: v for k, v in merged_orig.items() if k in merged_new}

                conn.execute(
                    """
                    UPDATE pending_changes
                    SET new_values = ?, original_values = ?, change_type = ?, created_at = ?
                    WHERE transaction_id = ?
                    """,
                    (
                        json.dumps(merged_new),
                        json.dumps(merged_orig),
                        change_type,
                        _now_iso(),
                        transaction_id,
                    ),
                )
            else:
                # Also write to legacy columns for backward compatibility during migration
                conn.execute(
                    """
                    INSERT INTO pending_changes
                    (transaction_id, budget_id, change_type, new_values, original_values,
                     new_category_id, new_category_name, original_category_id, original_category_name,
                     new_approved, original_approved, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        transaction_id,
                        budget_id,
                        change_type,
                        json.dumps(new_values),
                        json.dumps(original_values),
                        new_values.get("category_id"),
                        new_values.get("category_name"),
                        original_values.get("category_id"),
                        original_values.get("category_name"),
                        new_values.get("approved"),
                        original_values.get("approved"),
                        _now_iso(),
                    ),
                )
            return True

    def get_pending_change(self, transaction_id: str) -> Optional[dict[str, Any]]:
        """Get pending change for a transaction if exists.

        Args:
            transaction_id: YNAB transaction ID.

        Returns:
            Dict with change details including parsed new_values and original_values,
            or None if no pending change.
        """
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT id, transaction_id, change_type,
                       new_values, original_values,
                       new_category_id, new_category_name,
                       original_category_id, original_category_name,
                       new_approved, original_approved,
                       created_at
                FROM pending_changes
                WHERE transaction_id = ?
                """,
                (transaction_id,),
            ).fetchone()

            if not row:
                return None

            result = dict(row)
            # Parse JSON columns
            result["new_values"] = json.loads(row["new_values"]) if row["new_values"] else {}
            result["original_values"] = (
                json.loads(row["original_values"]) if row["original_values"] else {}
            )

            # For backward compatibility, populate from JSON if legacy columns are empty
            if not result.get("new_category_id") and result["new_values"].get("category_id"):
                result["new_category_id"] = result["new_values"]["category_id"]
                result["new_category_name"] = result["new_values"].get("category_name")
            if not result.get("original_category_id") and result["original_values"].get(
                "category_id"
            ):
                result["original_category_id"] = result["original_values"]["category_id"]
                result["original_category_name"] = result["original_values"].get("category_name")

            return result

    def get_all_pending_changes(self) -> list[dict[str, Any]]:
        """Get all pending changes with transaction details.

        Returns:
            List of dicts with pending change and transaction info,
            including parsed new_values and original_values.
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
                    pc.new_values, pc.original_values,
                    pc.new_category_id, pc.new_category_name,
                    pc.original_category_id, pc.original_category_name,
                    pc.new_approved, pc.original_approved,
                    pc.created_at,
                    t.date, t.amount, t.payee_name, t.account_name, t.approved, t.memo,
                    t.category_name, t.category_id
                FROM pending_changes pc
                JOIN ynab_transactions t ON pc.transaction_id = t.id
                {where_clause}
                ORDER BY t.date DESC
                """,
                params,
            ).fetchall()

            results = []
            for row in rows:
                result = dict(row)
                # Parse JSON columns
                result["new_values"] = json.loads(row["new_values"]) if row["new_values"] else {}
                result["original_values"] = (
                    json.loads(row["original_values"]) if row["original_values"] else {}
                )

                # For backward compatibility
                if not result.get("new_category_id") and result["new_values"].get("category_id"):
                    result["new_category_id"] = result["new_values"]["category_id"]
                    result["new_category_name"] = result["new_values"].get("category_name")

                results.append(result)

            return results

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
        with all changed fields and removes the pending change record.

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

            # Parse JSON values
            new_values = json.loads(change["new_values"]) if change["new_values"] else {}

            # Fallback to legacy columns if JSON is empty
            if not new_values:
                new_values = {}
                if change["new_category_id"]:
                    new_values["category_id"] = change["new_category_id"]
                    new_values["category_name"] = change["new_category_name"]
                if change["new_approved"] is not None:
                    new_values["approved"] = change["new_approved"]

            # Build dynamic UPDATE statement based on which fields changed
            updates = ["sync_status = 'synced'", "synced_at = ?"]
            params: list[Any] = [_now_iso()]

            if "category_id" in new_values:
                updates.append("category_id = ?")
                params.append(new_values["category_id"])
            if "category_name" in new_values:
                updates.append("category_name = ?")
                params.append(new_values["category_name"])
            if "approved" in new_values:
                updates.append("approved = ?")
                params.append(new_values["approved"])
            if "memo" in new_values:
                updates.append("memo = ?")
                params.append(new_values["memo"])

            params.append(transaction_id)

            conn.execute(
                f"UPDATE ynab_transactions SET {', '.join(updates)} WHERE id = ?",
                params,
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
