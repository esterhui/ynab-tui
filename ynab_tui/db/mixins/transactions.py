"""YNAB transaction database operations."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional

from ..models import TransactionFilter
from .base import CountMixin, _date_str, _now_iso

if TYPE_CHECKING:
    from ynab_tui.models.transaction import SubTransaction, Transaction


class TransactionMixin(CountMixin):
    """Mixin for YNAB transaction database operations."""

    def upsert_ynab_transaction(
        self, txn: Transaction, budget_id: Optional[str] = None
    ) -> tuple[bool, bool]:
        """Insert or update a YNAB transaction.

        Args:
            txn: Transaction to upsert.
            budget_id: Budget ID to associate with transaction. If None, uses self.budget_id.

        Returns:
            Tuple of (was_inserted, was_changed). was_changed is True only if
            data actually changed (not just synced_at timestamp).
        """
        budget_id = budget_id or getattr(self, "budget_id", None)

        with self._connection() as conn:
            existing = conn.execute(
                """SELECT id, date, amount, payee_name, payee_id, category_id,
                          category_name, account_name, account_id, memo, cleared,
                          approved, is_split, transfer_account_id
                   FROM ynab_transactions WHERE id = ?""",
                (txn.id,),
            ).fetchone()

            new_date = _date_str(txn.date)

            if existing:
                data_changed = (
                    existing["date"] != new_date
                    or existing["amount"] != txn.amount
                    or existing["payee_name"] != txn.payee_name
                    or existing["category_id"] != txn.category_id
                    or existing["category_name"] != txn.category_name
                    or existing["memo"] != txn.memo
                    or existing["approved"] != txn.approved
                    or existing["transfer_account_id"] != txn.transfer_account_id
                )

                if data_changed:
                    conn.execute(
                        """
                        UPDATE ynab_transactions SET
                            date = ?, amount = ?, payee_name = ?, payee_id = ?,
                            category_id = ?, category_name = ?, account_name = ?,
                            account_id = ?, memo = ?, cleared = ?, approved = ?,
                            is_split = ?, parent_transaction_id = ?, synced_at = ?,
                            transfer_account_id = ?, transfer_account_name = ?,
                            debt_transaction_type = ?, budget_id = COALESCE(?, budget_id)
                        WHERE id = ? AND sync_status = 'synced'
                        """,
                        (
                            new_date,
                            txn.amount,
                            txn.payee_name,
                            txn.payee_id,
                            txn.category_id,
                            txn.category_name,
                            txn.account_name,
                            txn.account_id,
                            txn.memo,
                            txn.cleared,
                            txn.approved,
                            txn.is_split,
                            None,
                            _now_iso(),
                            txn.transfer_account_id,
                            txn.transfer_account_name,
                            txn.debt_transaction_type,
                            budget_id,
                            txn.id,
                        ),
                    )
                inserted = False
                changed = data_changed
            else:
                conn.execute(
                    """
                    INSERT INTO ynab_transactions
                    (id, budget_id, date, amount, payee_name, payee_id, category_id, category_name,
                     account_name, account_id, memo, cleared, approved, is_split,
                     parent_transaction_id, sync_status, synced_at,
                     transfer_account_id, transfer_account_name, debt_transaction_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'synced', ?, ?, ?, ?)
                    """,
                    (
                        txn.id,
                        budget_id,
                        new_date,
                        txn.amount,
                        txn.payee_name,
                        txn.payee_id,
                        txn.category_id,
                        txn.category_name,
                        txn.account_name,
                        txn.account_id,
                        txn.memo,
                        txn.cleared,
                        txn.approved,
                        txn.is_split,
                        None,
                        _now_iso(),
                        txn.transfer_account_id,
                        txn.transfer_account_name,
                        txn.debt_transaction_type,
                    ),
                )
                inserted = True
                changed = True

            if txn.subtransactions:
                for sub in txn.subtransactions:
                    self._upsert_subtransaction(conn, sub, txn.id, budget_id)

            return (inserted, changed)

    def _upsert_subtransaction(
        self,
        conn: sqlite3.Connection,
        sub: SubTransaction,
        parent_id: str,
        budget_id: Optional[str] = None,
    ) -> None:
        """Insert or update a subtransaction."""
        existing = conn.execute(
            "SELECT id FROM ynab_transactions WHERE id = ?", (sub.id,)
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE ynab_transactions SET
                    amount = ?, payee_name = ?, payee_id = ?, category_id = ?,
                    category_name = ?, memo = ?, parent_transaction_id = ?,
                    synced_at = ?, budget_id = COALESCE(?, budget_id)
                WHERE id = ? AND sync_status = 'synced'
                """,
                (
                    sub.amount,
                    sub.payee_name,
                    sub.payee_id,
                    sub.category_id,
                    sub.category_name,
                    sub.memo,
                    parent_id,
                    _now_iso(),
                    budget_id,
                    sub.id,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO ynab_transactions
                (id, budget_id, date, amount, payee_name, payee_id, category_id, category_name,
                 memo, is_split, parent_transaction_id, sync_status, synced_at)
                VALUES (?, ?, (SELECT date FROM ynab_transactions WHERE id = ?),
                        ?, ?, ?, ?, ?, ?, 0, ?, 'synced', ?)
                """,
                (
                    sub.id,
                    budget_id,
                    parent_id,
                    sub.amount,
                    sub.payee_name,
                    sub.payee_id,
                    sub.category_id,
                    sub.category_name,
                    sub.memo,
                    parent_id,
                    _now_iso(),
                ),
            )

    def upsert_ynab_transactions(self, transactions: list[Transaction]) -> tuple[int, int]:
        """Batch upsert YNAB transactions.

        Args:
            transactions: List of transactions to upsert.

        Returns:
            Tuple of (inserted_count, updated_count).
        """
        inserted = 0
        updated = 0
        for txn in transactions:
            was_inserted, was_changed = self.upsert_ynab_transaction(txn)
            if was_inserted:
                inserted += 1
            elif was_changed:
                updated += 1
        return inserted, updated

    def _non_categorizable_conditions(self, table_alias: str = "t") -> list[str]:
        """SQL conditions to exclude transfers and balance adjustments.

        Args:
            table_alias: Table alias to use in SQL conditions (empty for no alias).

        Returns:
            List of SQL WHERE conditions.
        """
        from ynab_tui.models.transaction import BALANCE_ADJUSTMENT_PAYEES

        prefix = f"{table_alias}." if table_alias else ""
        payees_sql = ", ".join(f"'{p}'" for p in BALANCE_ADJUSTMENT_PAYEES)
        return [
            f"{prefix}transfer_account_id IS NULL",
            f"{prefix}payee_name NOT IN ({payees_sql})",
        ]

    def get_ynab_transactions(
        self,
        approved_only: bool = False,
        unapproved_only: bool = False,
        uncategorized_only: bool = False,
        pending_push_only: bool = False,
        payee_filter: Optional[str] = None,
        limit: Optional[int] = None,
        exclude_subtransactions: bool = True,
        since_date: Optional[datetime] = None,
        *,
        filter: Optional[TransactionFilter] = None,
    ) -> list[dict[str, Any]]:
        """Query YNAB transactions with filters.

        Can be called with individual parameters (backwards compatible) or
        with a TransactionFilter object for cleaner API.

        Args:
            approved_only: Only return approved transactions.
            unapproved_only: Only return unapproved transactions.
            uncategorized_only: Only return uncategorized transactions.
            pending_push_only: Only return transactions pending push.
            payee_filter: Filter by payee name (partial match).
            limit: Maximum number of results.
            exclude_subtransactions: Exclude subtransactions from results.
            since_date: Only return transactions on or after this date.
            filter: TransactionFilter object (overrides individual parameters).

        Returns:
            List of transaction dictionaries.
        """
        if filter is not None:
            approved_only = filter.approved_only
            unapproved_only = filter.unapproved_only
            uncategorized_only = filter.uncategorized_only
            pending_push_only = filter.pending_push_only
            payee_filter = filter.payee_filter
            category_id_filter = filter.category_id_filter
            limit = filter.limit
            exclude_subtransactions = filter.exclude_subtransactions
            since_date = filter.since_date
        else:
            category_id_filter = None

        conditions: list[str] = []
        params: list[Any] = []

        # Filter by budget_id if set
        budget_id = getattr(self, "budget_id", None)
        if budget_id:
            conditions.append("t.budget_id = ?")
            params.append(budget_id)

        if exclude_subtransactions:
            conditions.append("t.parent_transaction_id IS NULL")

        if since_date:
            conditions.append("t.date >= ?")
            params.append(_date_str(since_date))

        if approved_only:
            conditions.append("t.approved = 1")

        if unapproved_only:
            conditions.append("t.approved = 0")

        if uncategorized_only:
            # Category must be NULL, plus exclude transfers/adjustments
            conditions.append(
                "(COALESCE(pc.new_category_id, t.category_id) IS NULL "
                "OR COALESCE(pc.new_category_name, t.category_name) IS NULL) "
                "AND t.is_split = 0"  # Split transactions have categories in subtransactions
            )
            conditions.extend(self._non_categorizable_conditions("t"))

        if pending_push_only:
            conditions.append("(pc.id IS NOT NULL OR t.sync_status = 'pending_push')")

        if payee_filter:
            conditions.append("t.payee_name LIKE ?")
            params.append(f"%{payee_filter}%")

        if category_id_filter:
            conditions.append("COALESCE(pc.new_category_id, t.category_id) = ?")
            params.append(category_id_filter)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        limit_clause = f"LIMIT {limit}" if limit else ""

        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT t.id, t.budget_id, t.date, t.amount, t.payee_name, t.payee_id,
                       COALESCE(pc.new_category_id, t.category_id) AS category_id,
                       COALESCE(pc.new_category_name, t.category_name) AS category_name,
                       t.account_name, t.account_id, t.memo, t.cleared,
                       COALESCE(pc.new_approved, t.approved) AS approved,
                       t.is_split, t.parent_transaction_id,
                       CASE WHEN pc.id IS NOT NULL THEN 'pending_push'
                            ELSE t.sync_status END AS sync_status,
                       t.synced_at, t.modified_at, t.transfer_account_id,
                       t.transfer_account_name, t.debt_transaction_type
                FROM ynab_transactions t
                LEFT JOIN pending_changes pc ON t.id = pc.transaction_id
                WHERE {where_clause}
                ORDER BY t.date DESC
                {limit_clause}
                """,
                params,
            ).fetchall()

            return [dict(row) for row in rows]

    def get_ynab_transaction(self, transaction_id: str) -> Optional[dict[str, Any]]:
        """Get a single YNAB transaction by ID.

        Args:
            transaction_id: YNAB transaction ID.

        Returns:
            Transaction dictionary or None.
        """
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT id, budget_id, date, amount, payee_name, payee_id, category_id,
                       category_name, account_name, account_id, memo, cleared,
                       approved, is_split, parent_transaction_id, sync_status,
                       synced_at, modified_at, transfer_account_id,
                       transfer_account_name, debt_transaction_type
                FROM ynab_transactions
                WHERE id = ?
                """,
                (transaction_id,),
            ).fetchone()

            return dict(row) if row else None

    def get_subtransactions(self, parent_id: str) -> list[dict[str, Any]]:
        """Get subtransactions for a parent transaction.

        Args:
            parent_id: Parent transaction ID.

        Returns:
            List of subtransaction dictionaries.
        """
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT id, date, amount, payee_name, payee_id, category_id,
                       category_name, memo, parent_transaction_id
                FROM ynab_transactions
                WHERE parent_transaction_id = ?
                ORDER BY amount DESC
                """,
                (parent_id,),
            ).fetchall()

            return [dict(row) for row in rows]

    def mark_pending_push(self, transaction_id: str, category_id: str, category_name: str) -> bool:
        """Mark a transaction as pending push after local categorization.

        Args:
            transaction_id: Transaction ID to update.
            category_id: New category ID.
            category_name: New category name.

        Returns:
            True if updated, False if not found.
        """
        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE ynab_transactions
                SET category_id = ?, category_name = ?,
                    sync_status = 'pending_push',
                    modified_at = ?
                WHERE id = ?
                """,
                (
                    category_id,
                    category_name,
                    _now_iso(),
                    transaction_id,
                ),
            )
            return cursor.rowcount > 0

    def mark_pending_split(self, transaction_id: str, splits: list[dict[str, Any]]) -> bool:
        """Mark a transaction as pending push with split information.

        Args:
            transaction_id: Transaction ID to update.
            splits: List of dicts with category_id, category_name, amount, memo.

        Returns:
            True if updated successfully.
        """
        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE ynab_transactions
                SET category_name = 'Split (pending)',
                    is_split = 1,
                    sync_status = 'pending_push',
                    modified_at = ?
                WHERE id = ?
                """,
                (_now_iso(), transaction_id),
            )

            if cursor.rowcount == 0:
                return False

            conn.execute(
                "DELETE FROM pending_splits WHERE transaction_id = ?",
                (transaction_id,),
            )

            for split in splits:
                conn.execute(
                    """
                    INSERT INTO pending_splits
                    (transaction_id, category_id, category_name, amount, memo)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        transaction_id,
                        split.get("category_id"),
                        split.get("category_name"),
                        split.get("amount", 0),
                        split.get("memo"),
                    ),
                )

            return True

    def get_pending_splits(self, transaction_id: str) -> list[dict[str, Any]]:
        """Get pending splits for a transaction.

        Args:
            transaction_id: Transaction ID to look up.

        Returns:
            List of split dictionaries.
        """
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT category_id, category_name, amount, memo
                FROM pending_splits
                WHERE transaction_id = ?
                ORDER BY id
                """,
                (transaction_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def clear_pending_splits(self, transaction_id: str) -> bool:
        """Clear pending splits after successful push.

        Args:
            transaction_id: Transaction ID to clear.

        Returns:
            True if any were deleted.
        """
        with self._connection() as conn:
            cursor = conn.execute(
                "DELETE FROM pending_splits WHERE transaction_id = ?",
                (transaction_id,),
            )
            return cursor.rowcount > 0

    def get_pending_push_transactions(self) -> list[dict[str, Any]]:
        """Get all transactions pending push to YNAB.

        Returns:
            List of transaction dictionaries.
        """
        return self.get_ynab_transactions(pending_push_only=True)

    def mark_synced(self, transaction_id: str) -> bool:
        """Mark a transaction as synced after successful push.

        Args:
            transaction_id: Transaction ID to update.

        Returns:
            True if updated, False if not found.
        """
        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE ynab_transactions
                SET sync_status = 'synced', synced_at = ?
                WHERE id = ?
                """,
                (_now_iso(), transaction_id),
            )
            return cursor.rowcount > 0

    def get_transaction_count(self, exclude_subtransactions: bool = True) -> int:
        """Get total YNAB transaction count.

        Args:
            exclude_subtransactions: Exclude subtransactions from count.

        Returns:
            Transaction count.
        """
        conditions = []
        if exclude_subtransactions:
            conditions.append("parent_transaction_id IS NULL")

        # Filter by budget_id if set
        budget_id = getattr(self, "budget_id", None)
        if budget_id:
            conditions.append(f"budget_id = '{budget_id}'")

        where = " AND ".join(conditions) if conditions else ""
        return self._count("ynab_transactions", where)

    def get_uncategorized_count(self, exclude_subtransactions: bool = True) -> int:
        """Get count of uncategorized YNAB transactions.

        Args:
            exclude_subtransactions: Exclude subtransactions from count.

        Returns:
            Uncategorized transaction count.
        """
        conditions = [
            "(category_id IS NULL OR category_name IS NULL)",
            "is_split = 0",  # Split transactions have categories in subtransactions
        ]
        conditions.extend(self._non_categorizable_conditions(""))
        if exclude_subtransactions:
            conditions.append("parent_transaction_id IS NULL")

        # Filter by budget_id if set
        budget_id = getattr(self, "budget_id", None)
        if budget_id:
            conditions.append(f"budget_id = '{budget_id}'")

        where_clause = " AND ".join(conditions)
        return self._count("ynab_transactions", where_clause)

    def get_pending_push_count(self) -> int:
        """Get count of transactions pending push.

        Returns:
            Pending push count.
        """
        return self._count("ynab_transactions", "sync_status = 'pending_push'")

    def get_transaction_date_range(self) -> tuple[Optional[str], Optional[str]]:
        """Get earliest and latest transaction dates.

        Returns:
            Tuple of (earliest_date, latest_date) as strings, or (None, None) if empty.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT MIN(date) as earliest, MAX(date) as latest FROM ynab_transactions"
            ).fetchone()
            if row and row["earliest"]:
                return (row["earliest"][:10], row["latest"][:10])
            return (None, None)

    def get_ynab_transaction_by_amount_date(
        self,
        amount: float,
        date: datetime,
        window_days: int = 3,
        tolerance: float = 0.10,
    ) -> Optional[dict[str, Any]]:
        """Find a YNAB transaction matching amount and date.

        Used for matching Amazon orders to YNAB transactions.

        Args:
            amount: Transaction amount to match.
            date: Transaction date.
            window_days: Days before/after to search.
            tolerance: Amount tolerance for matching.

        Returns:
            Matching transaction dictionary or None.
        """
        start = date - timedelta(days=window_days)
        end = date + timedelta(days=window_days)

        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT id, date, amount, payee_name, payee_id, category_id,
                       category_name, account_name, account_id, memo, cleared,
                       approved, is_split, sync_status
                FROM ynab_transactions
                WHERE date BETWEEN ? AND ?
                  AND ABS(amount - ?) <= ?
                  AND parent_transaction_id IS NULL
                ORDER BY ABS(amount - ?) ASC,
                         ABS(julianday(date) - julianday(?)) ASC
                LIMIT 1
                """,
                (_date_str(start), _date_str(end), amount, tolerance, amount, _date_str(date)),
            ).fetchone()

            return dict(row) if row else None
