"""SQLite database management for YNAB Categorizer.

Handles connection management and provides query methods for:
- Categorization history (for learning from past decisions)
- Amazon order cache (to avoid re-scraping)
- YNAB transactions (synced from YNAB API)
- Sync state tracking
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator, Optional

from .models import AmazonOrderCache, CategorizationRecord, TransactionFilter

if TYPE_CHECKING:
    from ynab_tui.models.transaction import SubTransaction, Transaction

__all__ = [
    "Database",
    "AmazonOrderCache",
    "CategorizationRecord",
    "TransactionFilter",
]

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    """Return current datetime as ISO format string."""
    return datetime.now().isoformat()


def _date_str(dt: date | datetime) -> str:
    """Convert date/datetime to YYYY-MM-DD string."""
    return dt.strftime("%Y-%m-%d")


class Database:
    """SQLite database manager for categorization history and caching."""

    def __init__(self, db_path: Path, budget_id: Optional[str] = None):
        """Initialize database connection."""
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._budget_id: Optional[str] = budget_id
        self._init_schema()

    @property
    def budget_id(self) -> Optional[str]:
        """Get current budget ID for filtering."""
        return self._budget_id

    @budget_id.setter
    def budget_id(self, value: Optional[str]) -> None:
        """Set current budget ID for filtering."""
        self._budget_id = value

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create a persistent database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30.0)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=30000")
        return self._conn

    def close(self):
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Context manager for database connections."""
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _count(self, table: str, where: str = "", params: tuple[Any, ...] = ()) -> int:
        """Count rows in a table with optional WHERE clause."""
        query = f"SELECT COUNT(*) as count FROM {table}"
        if where:
            query += f" WHERE {where}"
        with self._connection() as conn:
            row = conn.execute(query, params).fetchone()
            return int(row["count"]) if row else 0

    def _init_schema(self):
        """Create database tables if they don't exist."""
        with self._connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS categorization_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payee_name TEXT NOT NULL,
                    payee_normalized TEXT NOT NULL,
                    amount REAL,
                    category_name TEXT NOT NULL,
                    category_id TEXT NOT NULL,
                    amazon_items TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    transaction_id TEXT UNIQUE,
                    transaction_date DATE
                );
                CREATE TABLE IF NOT EXISTS amazon_orders_cache (
                    order_id TEXT PRIMARY KEY,
                    order_date DATE NOT NULL,
                    total REAL NOT NULL,
                    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS ynab_transactions (
                    id TEXT PRIMARY KEY,
                    budget_id TEXT,
                    date DATE NOT NULL,
                    amount REAL NOT NULL,
                    payee_name TEXT,
                    payee_id TEXT,
                    category_id TEXT,
                    category_name TEXT,
                    account_name TEXT,
                    account_id TEXT,
                    memo TEXT,
                    cleared TEXT,
                    approved BOOLEAN DEFAULT 0,
                    is_split BOOLEAN DEFAULT 0,
                    parent_transaction_id TEXT,
                    sync_status TEXT DEFAULT 'synced',
                    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    modified_at TIMESTAMP,
                    transfer_account_id TEXT,
                    transfer_account_name TEXT,
                    debt_transaction_type TEXT,
                    FOREIGN KEY (parent_transaction_id) REFERENCES ynab_transactions(id)
                );
                CREATE TABLE IF NOT EXISTS amazon_order_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT NOT NULL,
                    item_name TEXT NOT NULL,
                    item_price REAL,
                    quantity INTEGER DEFAULT 1,
                    category_id TEXT,
                    category_name TEXT,
                    FOREIGN KEY (order_id) REFERENCES amazon_orders_cache(order_id)
                );
                CREATE TABLE IF NOT EXISTS amazon_item_category_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_name TEXT NOT NULL,
                    item_name_normalized TEXT NOT NULL,
                    category_id TEXT NOT NULL,
                    category_name TEXT NOT NULL,
                    source_transaction_id TEXT,
                    source_order_id TEXT,
                    learned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(item_name_normalized, category_id, source_transaction_id)
                );
                CREATE TABLE IF NOT EXISTS sync_state (
                    key TEXT PRIMARY KEY,
                    last_sync_date DATE,
                    last_sync_at TIMESTAMP,
                    record_count INTEGER
                );
                CREATE TABLE IF NOT EXISTS ynab_categories (
                    id TEXT PRIMARY KEY,
                    budget_id TEXT,
                    name TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    group_name TEXT NOT NULL,
                    hidden BOOLEAN DEFAULT 0,
                    deleted BOOLEAN DEFAULT 0,
                    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS pending_splits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    budget_id TEXT,
                    transaction_id TEXT NOT NULL,
                    category_id TEXT,
                    category_name TEXT,
                    amount REAL NOT NULL,
                    memo TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (transaction_id) REFERENCES ynab_transactions(id)
                );
                CREATE INDEX IF NOT EXISTS idx_pending_splits_txn ON pending_splits(transaction_id);
                CREATE TABLE IF NOT EXISTS pending_changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    budget_id TEXT,
                    transaction_id TEXT NOT NULL UNIQUE,
                    change_type TEXT NOT NULL DEFAULT 'category',
                    new_category_id TEXT,
                    new_category_name TEXT,
                    original_category_id TEXT,
                    original_category_name TEXT,
                    new_approved BOOLEAN,
                    original_approved BOOLEAN,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (transaction_id) REFERENCES ynab_transactions(id)
                );
                CREATE INDEX IF NOT EXISTS idx_pending_changes_txn ON pending_changes(transaction_id);
                CREATE INDEX IF NOT EXISTS idx_payee_normalized ON categorization_history(payee_normalized);
                CREATE INDEX IF NOT EXISTS idx_order_date ON amazon_orders_cache(order_date);
                CREATE INDEX IF NOT EXISTS idx_ynab_date ON ynab_transactions(date);
                CREATE INDEX IF NOT EXISTS idx_ynab_payee ON ynab_transactions(payee_name);
                CREATE INDEX IF NOT EXISTS idx_ynab_category ON ynab_transactions(category_id);
                CREATE INDEX IF NOT EXISTS idx_ynab_approved ON ynab_transactions(approved);
                CREATE INDEX IF NOT EXISTS idx_ynab_sync_status ON ynab_transactions(sync_status);
                CREATE INDEX IF NOT EXISTS idx_ynab_parent ON ynab_transactions(parent_transaction_id);
                CREATE INDEX IF NOT EXISTS idx_amazon_item_order ON amazon_order_items(order_id);
                CREATE INDEX IF NOT EXISTS idx_amazon_item_name ON amazon_order_items(item_name);
                CREATE INDEX IF NOT EXISTS idx_item_cat_history_name ON amazon_item_category_history(item_name_normalized);
                CREATE INDEX IF NOT EXISTS idx_category_group ON ynab_categories(group_id);
                CREATE INDEX IF NOT EXISTS idx_category_name ON ynab_categories(name);
                CREATE INDEX IF NOT EXISTS idx_ynab_transfer ON ynab_transactions(transfer_account_id);
            """)
            self._run_migrations(conn)

    def _run_migrations(self, conn) -> None:
        """Run all schema migrations."""
        # Add transfer columns
        cursor = conn.execute("PRAGMA table_info(ynab_transactions)")
        columns = {row[1] for row in cursor.fetchall()}
        if "transfer_account_id" not in columns:
            conn.execute("ALTER TABLE ynab_transactions ADD COLUMN transfer_account_id TEXT")
        if "transfer_account_name" not in columns:
            conn.execute("ALTER TABLE ynab_transactions ADD COLUMN transfer_account_name TEXT")
        if "debt_transaction_type" not in columns:
            conn.execute("ALTER TABLE ynab_transactions ADD COLUMN debt_transaction_type TEXT")

        # Clear legacy pending_push
        conn.execute(
            "UPDATE ynab_transactions SET sync_status = 'synced' WHERE sync_status = 'pending_push'"
        )

        # Add approval columns to pending_changes
        cursor = conn.execute("PRAGMA table_info(pending_changes)")
        columns = {row[1] for row in cursor.fetchall()}
        if "new_approved" not in columns:
            conn.execute("ALTER TABLE pending_changes ADD COLUMN new_approved BOOLEAN")
        if "original_approved" not in columns:
            conn.execute("ALTER TABLE pending_changes ADD COLUMN original_approved BOOLEAN")

        # Add budget_id columns
        for table in ["ynab_transactions", "ynab_categories", "pending_changes", "pending_splits"]:
            cursor = conn.execute(f"PRAGMA table_info({table})")
            cols = {row[1] for row in cursor.fetchall()}
            if "budget_id" not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN budget_id TEXT")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_ynab_budget ON ynab_transactions(budget_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_category_budget ON ynab_categories(budget_id)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pending_changes_budget ON pending_changes(budget_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pending_splits_budget ON pending_splits(budget_id)"
        )

        # Add JSON columns for pending_changes
        cursor = conn.execute("PRAGMA table_info(pending_changes)")
        columns = {row[1] for row in cursor.fetchall()}
        if "new_values" not in columns:
            conn.execute("ALTER TABLE pending_changes ADD COLUMN new_values TEXT")
        if "original_values" not in columns:
            conn.execute("ALTER TABLE pending_changes ADD COLUMN original_values TEXT")

        # Migrate existing pending_changes to JSON format
        rows = conn.execute("""
            SELECT id, new_category_id, new_category_name, original_category_id,
                   original_category_name, new_approved, original_approved, new_values, original_values
            FROM pending_changes WHERE new_values IS NULL AND (new_category_id IS NOT NULL OR new_approved IS NOT NULL)
        """).fetchall()
        for row in rows:
            new_values, original_values = {}, {}
            if row["new_category_id"]:
                new_values["category_id"] = row["new_category_id"]
            if row["new_category_name"]:
                new_values["category_name"] = row["new_category_name"]
            if row["new_approved"] is not None:
                new_values["approved"] = bool(row["new_approved"])
            if row["original_category_id"]:
                original_values["category_id"] = row["original_category_id"]
            if row["original_category_name"]:
                original_values["category_name"] = row["original_category_name"]
            if row["original_approved"] is not None:
                original_values["approved"] = bool(row["original_approved"])
            conn.execute(
                "UPDATE pending_changes SET new_values = ?, original_values = ? WHERE id = ?",
                (json.dumps(new_values), json.dumps(original_values), row["id"]),
            )

        # Add transaction_id and transaction_date to categorization_history
        cursor = conn.execute("PRAGMA table_info(categorization_history)")
        columns = {row[1] for row in cursor.fetchall()}
        if "transaction_id" not in columns:
            # Note: SQLite doesn't allow ALTER TABLE ADD COLUMN with UNIQUE constraint
            # So we add the column without UNIQUE and create a unique index instead
            conn.execute("ALTER TABLE categorization_history ADD COLUMN transaction_id TEXT")
        if "transaction_date" not in columns:
            conn.execute("ALTER TABLE categorization_history ADD COLUMN transaction_date DATE")
        # Create unique index for transaction_id (enforces uniqueness for migrations)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_cat_history_txn_unique ON categorization_history(transaction_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cat_history_date ON categorization_history(transaction_date)"
        )

    def clear_all(self) -> dict[str, int]:
        """Clear all data from all tables."""
        counts = {}
        tables = [
            "ynab_categories",
            "ynab_transactions",
            "amazon_orders_cache",
            "amazon_order_items",
            "amazon_item_category_history",
            "categorization_history",
            "sync_state",
        ]
        with self._connection() as conn:
            for table in tables:
                row = conn.execute(f"SELECT COUNT(*) as count FROM {table}").fetchone()
                counts[table] = row["count"] if row else 0
                conn.execute(f"DELETE FROM {table}")
        return counts

    # =========================================================================
    # Transaction Methods
    # =========================================================================

    def upsert_ynab_transaction(
        self, txn: Transaction, budget_id: Optional[str] = None
    ) -> tuple[bool, bool]:
        """Insert or update a YNAB transaction."""
        budget_id = budget_id or self._budget_id
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT id, date, amount, payee_name, category_id, category_name, memo, approved, transfer_account_id FROM ynab_transactions WHERE id = ?",
                (txn.id,),
            ).fetchone()
            new_date = _date_str(txn.date)
            if existing:
                # Check for pending changes - preserve local category if pending
                pending = conn.execute(
                    """SELECT json_extract(new_values, '$.category_id') as new_category_id,
                              json_extract(new_values, '$.category_name') as new_category_name
                       FROM pending_changes WHERE transaction_id=?""",
                    (txn.id,),
                ).fetchone()

                # Conflict detection: local has category, YNAB says uncategorized, no pending
                # This protects against YNAB resetting categories (e.g., bank re-import)
                is_conflict = False
                if not pending and existing["category_id"] and not txn.category_id:
                    # Keep local category, mark as conflict
                    is_conflict = True
                    logger.warning(
                        f"Conflict detected for {txn.id}: keeping local category "
                        f"'{existing['category_name']}' (YNAB returned uncategorized)"
                    )

                # Use pending category values if they exist, otherwise use YNAB values
                # BUT if conflict, preserve local category
                if pending and pending["new_category_id"]:
                    final_category_id = pending["new_category_id"]
                    final_category_name = pending["new_category_name"]
                elif is_conflict:
                    final_category_id = existing["category_id"]
                    final_category_name = existing["category_name"]
                else:
                    final_category_id = txn.category_id
                    final_category_name = txn.category_name

                data_changed = (
                    existing["date"] != new_date
                    or existing["amount"] != txn.amount
                    or existing["payee_name"] != txn.payee_name
                    or existing["category_id"] != final_category_id
                    or existing["category_name"] != final_category_name
                    or existing["memo"] != txn.memo
                    or existing["approved"] != txn.approved
                    or existing["transfer_account_id"] != txn.transfer_account_id
                )
                # Also update if conflict detected (to set sync_status)
                needs_update = data_changed or is_conflict
                if needs_update:
                    # Set sync_status to 'conflict' if conflict detected, otherwise keep 'synced'
                    new_sync_status = "conflict" if is_conflict else "synced"
                    conn.execute(
                        """UPDATE ynab_transactions SET date=?, amount=?, payee_name=?, payee_id=?,
                        category_id=?, category_name=?, account_name=?, account_id=?, memo=?, cleared=?, approved=?,
                        is_split=?, parent_transaction_id=?, synced_at=?, transfer_account_id=?, transfer_account_name=?,
                        debt_transaction_type=?, budget_id=COALESCE(?, budget_id), sync_status=?
                        WHERE id=? AND sync_status IN ('synced', 'conflict', 'pending_push')""",
                        (
                            new_date,
                            txn.amount,
                            txn.payee_name,
                            txn.payee_id,
                            final_category_id,
                            final_category_name,
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
                            new_sync_status,
                            txn.id,
                        ),
                    )
                inserted, changed = False, needs_update
            else:
                conn.execute(
                    """INSERT INTO ynab_transactions (id, budget_id, date, amount, payee_name, payee_id,
                    category_id, category_name, account_name, account_id, memo, cleared, approved, is_split,
                    parent_transaction_id, sync_status, synced_at, transfer_account_id, transfer_account_name, debt_transaction_type)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'synced',?,?,?,?)""",
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
                inserted, changed = True, True
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
                """UPDATE ynab_transactions SET amount=?, payee_name=?, payee_id=?, category_id=?,
                category_name=?, memo=?, parent_transaction_id=?, synced_at=?, budget_id=COALESCE(?, budget_id)
                WHERE id=? AND sync_status='synced'""",
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
                """INSERT INTO ynab_transactions (id, budget_id, date, amount, payee_name, payee_id,
                category_id, category_name, memo, is_split, parent_transaction_id, sync_status, synced_at)
                VALUES (?,?,(SELECT date FROM ynab_transactions WHERE id=?),?,?,?,?,?,?,0,?,'synced',?)""",
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
        """Batch upsert YNAB transactions."""
        inserted, updated = 0, 0
        for txn in transactions:
            was_inserted, was_changed = self.upsert_ynab_transaction(txn)
            if was_inserted:
                inserted += 1
            elif was_changed:
                updated += 1
        return inserted, updated

    def _non_categorizable_conditions(self, table_alias: str = "t") -> list[str]:
        """SQL conditions to exclude transfers and balance adjustments."""
        from ynab_tui.models.transaction import BALANCE_ADJUSTMENT_PAYEES

        prefix = f"{table_alias}." if table_alias else ""
        payees_sql = ", ".join(f"'{p}'" for p in BALANCE_ADJUSTMENT_PAYEES)
        return [f"{prefix}transfer_account_id IS NULL", f"{prefix}payee_name NOT IN ({payees_sql})"]

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
        """Query YNAB transactions with filters."""
        if filter is not None:
            approved_only, unapproved_only = filter.approved_only, filter.unapproved_only
            uncategorized_only, pending_push_only = (
                filter.uncategorized_only,
                filter.pending_push_only,
            )
            payee_filter, category_id_filter = filter.payee_filter, filter.category_id_filter
            limit, exclude_subtransactions, since_date = (
                filter.limit,
                filter.exclude_subtransactions,
                filter.since_date,
            )
        else:
            category_id_filter = None
        conditions, params = [], []
        if self._budget_id:
            conditions.append("t.budget_id = ?")
            params.append(self._budget_id)
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
            conditions.append(
                "(COALESCE(json_extract(pc.new_values, '$.category_id'), t.category_id) IS NULL OR COALESCE(json_extract(pc.new_values, '$.category_name'), t.category_name) IS NULL) AND t.is_split = 0"
            )
            conditions.extend(self._non_categorizable_conditions("t"))
        if pending_push_only:
            conditions.append("(pc.id IS NOT NULL OR t.sync_status = 'pending_push')")
        if payee_filter:
            conditions.append("t.payee_name LIKE ?")
            params.append(f"%{payee_filter}%")
        if category_id_filter:
            conditions.append(
                "COALESCE(json_extract(pc.new_values, '$.category_id'), t.category_id) = ?"
            )
            params.append(category_id_filter)
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        limit_clause = f"LIMIT {limit}" if limit else ""
        with self._connection() as conn:
            rows = conn.execute(
                f"""SELECT t.id, t.budget_id, t.date, t.amount, t.payee_name, t.payee_id,
                COALESCE(json_extract(pc.new_values, '$.category_id'), t.category_id) AS category_id,
                COALESCE(json_extract(pc.new_values, '$.category_name'), t.category_name) AS category_name,
                t.account_name, t.account_id, t.memo, t.cleared,
                COALESCE(json_extract(pc.new_values, '$.approved'), t.approved) AS approved, t.is_split, t.parent_transaction_id,
                CASE WHEN pc.id IS NOT NULL THEN 'pending_push' ELSE t.sync_status END AS sync_status,
                t.synced_at, t.modified_at, t.transfer_account_id, t.transfer_account_name, t.debt_transaction_type
                FROM ynab_transactions t LEFT JOIN pending_changes pc ON t.id = pc.transaction_id
                WHERE {where_clause} ORDER BY t.date DESC {limit_clause}""",
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    def get_ynab_transaction(self, transaction_id: str) -> Optional[dict[str, Any]]:
        """Get a single YNAB transaction by ID."""
        with self._connection() as conn:
            row = conn.execute(
                """SELECT id, budget_id, date, amount, payee_name, payee_id, category_id,
                category_name, account_name, account_id, memo, cleared, approved, is_split,
                parent_transaction_id, sync_status, synced_at, modified_at, transfer_account_id,
                transfer_account_name, debt_transaction_type FROM ynab_transactions WHERE id = ?""",
                (transaction_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_subtransactions(self, parent_id: str) -> list[dict[str, Any]]:
        """Get subtransactions for a parent transaction."""
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT id, date, amount, payee_name, payee_id, category_id, category_name, memo, parent_transaction_id
                FROM ynab_transactions WHERE parent_transaction_id = ? ORDER BY amount DESC""",
                (parent_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def mark_pending_split(
        self, transaction_id: str, splits: list[dict[str, Any]], category_name: str | None = None
    ) -> bool:
        """Mark a transaction as pending push with split information."""
        # Use "Split" to match YNAB's category name for split transactions
        split_category = category_name or "Split"
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE ynab_transactions SET category_name=?, is_split=1, sync_status='pending_push', modified_at=? WHERE id=?",
                (split_category, _now_iso(), transaction_id),
            )
            if cursor.rowcount == 0:
                return False
            conn.execute("DELETE FROM pending_splits WHERE transaction_id = ?", (transaction_id,))
            for split in splits:
                conn.execute(
                    "INSERT INTO pending_splits (transaction_id, category_id, category_name, amount, memo) VALUES (?,?,?,?,?)",
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
        """Get pending splits for a transaction."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT category_id, category_name, amount, memo FROM pending_splits WHERE transaction_id=? ORDER BY id",
                (transaction_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def clear_pending_splits(self, transaction_id: str) -> bool:
        """Clear pending splits after successful push."""
        with self._connection() as conn:
            cursor = conn.execute(
                "DELETE FROM pending_splits WHERE transaction_id = ?", (transaction_id,)
            )
            return cursor.rowcount > 0

    def mark_synced(self, transaction_id: str) -> bool:
        """Mark a transaction as synced after successful push."""
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE ynab_transactions SET sync_status='synced', synced_at=? WHERE id=?",
                (_now_iso(), transaction_id),
            )
            return cursor.rowcount > 0

    def get_transaction_count(self, exclude_subtransactions: bool = True) -> int:
        """Get total YNAB transaction count."""
        conditions = []
        if exclude_subtransactions:
            conditions.append("parent_transaction_id IS NULL")
        if self._budget_id:
            conditions.append(f"budget_id = '{self._budget_id}'")
        return self._count("ynab_transactions", " AND ".join(conditions) if conditions else "")

    def get_uncategorized_count(self, exclude_subtransactions: bool = True) -> int:
        """Get count of uncategorized YNAB transactions."""
        conditions = ["(category_id IS NULL OR category_name IS NULL)", "is_split = 0"]
        conditions.extend(self._non_categorizable_conditions(""))
        if exclude_subtransactions:
            conditions.append("parent_transaction_id IS NULL")
        if self._budget_id:
            conditions.append(f"budget_id = '{self._budget_id}'")
        return self._count("ynab_transactions", " AND ".join(conditions))

    def get_pending_push_count(self) -> int:
        """Get count of transactions pending push."""
        return self._count("ynab_transactions", "sync_status = 'pending_push'")

    def get_transaction_date_range(self) -> tuple[Optional[str], Optional[str]]:
        """Get earliest and latest transaction dates."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT MIN(date) as earliest, MAX(date) as latest FROM ynab_transactions"
            ).fetchone()
            if row and row["earliest"]:
                return (row["earliest"][:10], row["latest"][:10])
            return (None, None)

    def get_ynab_transaction_by_amount_date(
        self, amount: float, date: datetime, window_days: int = 3, tolerance: float = 0.10
    ) -> Optional[dict[str, Any]]:
        """Find a YNAB transaction matching amount and date."""
        start, end = date - timedelta(days=window_days), date + timedelta(days=window_days)
        with self._connection() as conn:
            row = conn.execute(
                """SELECT id, date, amount, payee_name, payee_id, category_id, category_name,
                account_name, account_id, memo, cleared, approved, is_split, sync_status
                FROM ynab_transactions WHERE date BETWEEN ? AND ? AND ABS(amount - ?) <= ? AND parent_transaction_id IS NULL
                ORDER BY ABS(amount - ?) ASC, ABS(julianday(date) - julianday(?)) ASC LIMIT 1""",
                (_date_str(start), _date_str(end), amount, tolerance, amount, _date_str(date)),
            ).fetchone()
            return dict(row) if row else None

    def get_conflict_transactions(self) -> list[dict[str, Any]]:
        """Get all transactions with sync_status='conflict'."""
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT id, date, amount, payee_name, payee_id, category_id, category_name,
                account_name, account_id, memo, cleared, approved, is_split, sync_status
                FROM ynab_transactions WHERE sync_status = 'conflict'
                ORDER BY date DESC"""
            ).fetchall()
            return [dict(row) for row in rows]

    def fix_conflict_transaction(self, transaction_id: str) -> bool:
        """Mark a conflict transaction as pending_push to re-sync local category to YNAB.

        Creates a pending_change entry with the local category and marks the
        transaction as pending_push so the next push will update YNAB.

        Returns:
            True if the conflict was fixed, False if transaction not found or not a conflict.
        """
        with self._connection() as conn:
            # Get the conflict transaction
            txn = conn.execute(
                """SELECT id, category_id, category_name, approved
                FROM ynab_transactions WHERE id = ? AND sync_status = 'conflict'""",
                (transaction_id,),
            ).fetchone()

            if not txn:
                return False

            # Create pending change to push local category back to YNAB
            new_values = {
                "category_id": txn["category_id"],
                "category_name": txn["category_name"],
            }
            # Original values: uncategorized (what YNAB sent)
            original_values = {
                "category_id": None,
                "category_name": None,
            }

            # Update sync status to pending_push
            conn.execute(
                "UPDATE ynab_transactions SET sync_status = 'pending_push', modified_at = ? WHERE id = ?",
                (_now_iso(), transaction_id),
            )

            # Create or update pending change
            self.create_pending_change(transaction_id, new_values, original_values, "update")

            logger.info(
                f"Fixed conflict for {transaction_id}: will push category "
                f"'{txn['category_name']}' to YNAB on next push"
            )
            return True

    # =========================================================================
    # Amazon Methods
    # =========================================================================

    def cache_amazon_order(
        self, order_id: str, order_date: datetime, total: float
    ) -> tuple[bool, bool]:
        """Cache an Amazon order to avoid re-scraping."""
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT order_id, order_date, total FROM amazon_orders_cache WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            new_date = _date_str(order_date)
            if existing:
                data_changed = existing["order_date"] != new_date or existing["total"] != total
                if data_changed:
                    conn.execute(
                        "UPDATE amazon_orders_cache SET order_date=?, total=?, fetched_at=? WHERE order_id=?",
                        (new_date, total, _now_iso(), order_id),
                    )
                return (False, data_changed)
            else:
                conn.execute(
                    "INSERT INTO amazon_orders_cache (order_id, order_date, total, fetched_at) VALUES (?,?,?,?)",
                    (order_id, new_date, total, _now_iso()),
                )
                return (True, True)

    def get_cached_orders_by_date_range(
        self, start_date: datetime, end_date: datetime
    ) -> list[AmazonOrderCache]:
        """Get cached Amazon orders within a date range."""
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT c.order_id, c.order_date, c.total, c.fetched_at, GROUP_CONCAT(i.item_name, '||') as items
                FROM amazon_orders_cache c LEFT JOIN amazon_order_items i ON c.order_id = i.order_id
                WHERE c.order_date BETWEEN ? AND ? GROUP BY c.order_id ORDER BY c.order_date DESC""",
                (_date_str(start_date), _date_str(end_date)),
            ).fetchall()
            return [
                AmazonOrderCache(
                    order_id=row["order_id"],
                    order_date=datetime.strptime(row["order_date"], "%Y-%m-%d")
                    if row["order_date"]
                    else datetime.min,
                    total=row["total"],
                    items=row["items"].split("||") if row["items"] else [],
                    fetched_at=datetime.fromisoformat(row["fetched_at"]),
                )
                for row in rows
            ]

    def get_cached_orders_for_year(self, year: int) -> list[AmazonOrderCache]:
        """Get cached Amazon orders for a specific year."""
        return self.get_cached_orders_by_date_range(datetime(year, 1, 1), datetime(year, 12, 31))

    def get_cached_order_by_amount(
        self, amount: float, date: datetime, window_days: int = 3, tolerance: float = 0.01
    ) -> Optional[AmazonOrderCache]:
        """Find a cached order matching amount and date."""
        start, end = date - timedelta(days=window_days), date + timedelta(days=window_days)
        with self._connection() as conn:
            order_row = conn.execute(
                """SELECT order_id, order_date, total, fetched_at FROM amazon_orders_cache
                WHERE order_date BETWEEN ? AND ? AND ABS(total - ?) <= ?
                ORDER BY ABS(total - ?) ASC, ABS(julianday(order_date) - julianday(?)) ASC LIMIT 1""",
                (_date_str(start), _date_str(end), amount, tolerance, amount, _date_str(date)),
            ).fetchone()
            if not order_row:
                return None
            item_rows = conn.execute(
                "SELECT item_name FROM amazon_order_items WHERE order_id = ?",
                (order_row["order_id"],),
            ).fetchall()
            return AmazonOrderCache(
                order_id=order_row["order_id"],
                order_date=datetime.strptime(order_row["order_date"], "%Y-%m-%d")
                if order_row["order_date"]
                else datetime.min,
                total=order_row["total"],
                items=[r["item_name"] for r in item_rows],
                fetched_at=datetime.fromisoformat(order_row["fetched_at"]),
            )

    def get_cached_order(self, order_id: str) -> Optional[dict[str, Any]]:
        """Get a cached Amazon order by ID."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT order_id, order_date, total FROM amazon_orders_cache WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            return dict(row) if row else None

    def upsert_amazon_order_items(self, order_id: str, items: list[dict[str, Any]]) -> int:
        """Store Amazon order items for category matching."""
        with self._connection() as conn:
            conn.execute("DELETE FROM amazon_order_items WHERE order_id = ?", (order_id,))
            for item in items:
                conn.execute(
                    "INSERT INTO amazon_order_items (order_id, item_name, item_price, quantity) VALUES (?,?,?,?)",
                    (
                        order_id,
                        item.get("name", "Unknown"),
                        item.get("price"),
                        item.get("quantity", 1),
                    ),
                )
            return len(items)

    def get_amazon_order_items_with_prices(self, order_id: str) -> list[dict[str, Any]]:
        """Get order items with prices for split transaction matching."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT item_name, item_price, quantity FROM amazon_order_items WHERE order_id=? ORDER BY item_price DESC",
                (order_id,),
            ).fetchall()
            return [
                {
                    "item_name": r["item_name"],
                    "item_price": r["item_price"],
                    "quantity": r["quantity"],
                }
                for r in rows
            ]

    def get_order_count(self) -> int:
        return self._count("amazon_orders_cache")

    def get_order_item_count(self) -> int:
        return self._count("amazon_order_items")

    def get_order_date_range(self) -> tuple[Optional[str], Optional[str]]:
        """Get earliest and latest Amazon order dates."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT MIN(order_date) as earliest, MAX(order_date) as latest FROM amazon_orders_cache"
            ).fetchone()
            if row and row["earliest"]:
                return (row["earliest"][:10], row["latest"][:10])
            return (None, None)

    # =========================================================================
    # Category Methods
    # =========================================================================

    def upsert_category(
        self,
        category_id: str,
        name: str,
        group_id: str,
        group_name: str,
        hidden: bool = False,
        deleted: bool = False,
        budget_id: Optional[str] = None,
    ) -> tuple[bool, bool]:
        """Insert or update a YNAB category."""
        budget_id = budget_id or self._budget_id
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT id, name, group_id, group_name, hidden, deleted FROM ynab_categories WHERE id = ?",
                (category_id,),
            ).fetchone()
            if existing:
                data_changed = (
                    existing["name"] != name
                    or existing["group_id"] != group_id
                    or existing["group_name"] != group_name
                    or existing["hidden"] != hidden
                    or existing["deleted"] != deleted
                )
                if data_changed:
                    conn.execute(
                        "UPDATE ynab_categories SET name=?, group_id=?, group_name=?, hidden=?, deleted=?, synced_at=?, budget_id=COALESCE(?, budget_id) WHERE id=?",
                        (
                            name,
                            group_id,
                            group_name,
                            hidden,
                            deleted,
                            _now_iso(),
                            budget_id,
                            category_id,
                        ),
                    )
                return (False, data_changed)
            else:
                conn.execute(
                    "INSERT INTO ynab_categories (id, budget_id, name, group_id, group_name, hidden, deleted, synced_at) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        category_id,
                        budget_id,
                        name,
                        group_id,
                        group_name,
                        hidden,
                        deleted,
                        _now_iso(),
                    ),
                )
                return (True, True)

    def upsert_categories(self, category_list: Any) -> tuple[int, int]:
        """Batch upsert YNAB categories from CategoryList."""
        inserted, updated = 0, 0
        for group in category_list.groups:
            for cat in group.categories:
                was_inserted, was_changed = self.upsert_category(
                    cat.id, cat.name, group.id, group.name, cat.hidden, cat.deleted
                )
                if was_inserted:
                    inserted += 1
                elif was_changed:
                    updated += 1
        return inserted, updated

    def get_categories(self, include_hidden: bool = False) -> list[dict[str, Any]]:
        """Get all categories grouped by category group."""
        conditions, params = [], []
        if not include_hidden:
            conditions.append("hidden = 0 AND deleted = 0")
        if self._budget_id:
            conditions.append("budget_id = ?")
            params.append(self._budget_id)
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT id, name, group_id, group_name, hidden, deleted, budget_id FROM ynab_categories WHERE {where_clause} ORDER BY group_name, name",
                params,
            ).fetchall()
            groups: dict[str, dict[str, Any]] = {}
            for row in rows:
                gid = row["group_id"]
                if gid not in groups:
                    groups[gid] = {"id": gid, "name": row["group_name"], "categories": []}
                groups[gid]["categories"].append(
                    {
                        "id": row["id"],
                        "name": row["name"],
                        "group_id": row["group_id"],
                        "group_name": row["group_name"],
                        "hidden": bool(row["hidden"]),
                        "deleted": bool(row["deleted"]),
                        "budget_id": row["budget_id"],
                    }
                )
            return list(groups.values())

    def get_category_by_id(self, category_id: str) -> Optional[dict[str, Any]]:
        """Get a category by ID."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT id, name, group_id, group_name, hidden, deleted FROM ynab_categories WHERE id = ?",
                (category_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_category_by_name(self, name: str) -> Optional[dict[str, Any]]:
        """Get a category by name (case-insensitive)."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT id, name, group_id, group_name, hidden, deleted FROM ynab_categories WHERE LOWER(name) = LOWER(?)",
                (name,),
            ).fetchone()
            return dict(row) if row else None

    def get_category_count(self, include_hidden: bool = False) -> int:
        """Get total category count."""
        conditions = []
        if not include_hidden:
            conditions.append("hidden = 0 AND deleted = 0")
        if self._budget_id:
            conditions.append(f"budget_id = '{self._budget_id}'")
        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self._connection() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) as count FROM ynab_categories{where_clause}"
            ).fetchone()
            return row["count"] if row else 0

    # =========================================================================
    # Pending Changes Methods
    # =========================================================================

    def create_pending_change(
        self,
        transaction_id: str,
        new_values: dict[str, Any],
        original_values: dict[str, Any],
        change_type: str = "update",
    ) -> str:
        """Create or update a pending change for a transaction.

        If after merging the new values equal the original values (i.e., the user
        reverted all changes), the pending change is deleted instead of updated.

        Returns:
            "created" if a new pending change was created,
            "updated" if an existing pending change was updated,
            "deleted" if all changes were reverted (pending change removed).
        """
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT new_values, original_values FROM pending_changes WHERE transaction_id = ?",
                (transaction_id,),
            ).fetchone()
            if existing:
                existing_new = json.loads(existing["new_values"]) if existing["new_values"] else {}
                existing_orig = (
                    json.loads(existing["original_values"]) if existing["original_values"] else {}
                )
                merged_new = {**existing_new, **new_values}
                merged_orig = {
                    k: v for k, v in {**original_values, **existing_orig}.items() if k in merged_new
                }

                # Check if all new values match original values (user reverted changes)
                # Filter out fields where new == original
                effective_changes = {k: v for k, v in merged_new.items() if merged_orig.get(k) != v}

                if not effective_changes:
                    # All changes reverted - delete the pending change
                    conn.execute(
                        "DELETE FROM pending_changes WHERE transaction_id = ?",
                        (transaction_id,),
                    )
                    return "deleted"

                # Keep only the fields that actually changed
                effective_orig = {k: merged_orig[k] for k in effective_changes if k in merged_orig}

                conn.execute(
                    "UPDATE pending_changes SET new_values=?, original_values=?, change_type=?, created_at=? WHERE transaction_id=?",
                    (
                        json.dumps(effective_changes),
                        json.dumps(effective_orig),
                        change_type,
                        _now_iso(),
                        transaction_id,
                    ),
                )
                return "updated"
            else:
                conn.execute(
                    """INSERT INTO pending_changes (transaction_id, budget_id, change_type, new_values, original_values,
                    new_category_id, new_category_name, original_category_id, original_category_name, new_approved, original_approved, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        transaction_id,
                        self._budget_id,
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
                return "created"

    def get_pending_change(self, transaction_id: str) -> Optional[dict[str, Any]]:
        """Get pending change for a transaction if exists."""
        with self._connection() as conn:
            row = conn.execute(
                """SELECT id, transaction_id, change_type, new_values, original_values,
                new_category_id, new_category_name, original_category_id, original_category_name,
                new_approved, original_approved, created_at FROM pending_changes WHERE transaction_id = ?""",
                (transaction_id,),
            ).fetchone()
            if not row:
                return None
            result = dict(row)
            result["new_values"] = json.loads(row["new_values"]) if row["new_values"] else {}
            result["original_values"] = (
                json.loads(row["original_values"]) if row["original_values"] else {}
            )
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
        """Get all pending changes with transaction details."""
        conditions, params = [], []
        if self._budget_id:
            conditions.append("pc.budget_id = ?")
            params.append(self._budget_id)
        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        with self._connection() as conn:
            rows = conn.execute(
                f"""SELECT pc.id, pc.transaction_id, pc.change_type, pc.new_values, pc.original_values,
                pc.new_category_id, pc.new_category_name, pc.original_category_id, pc.original_category_name,
                pc.new_approved, pc.original_approved, pc.created_at, t.date, t.amount, t.payee_name, t.account_name,
                t.approved, t.memo, t.category_name, t.category_id, t.transfer_account_id, t.transfer_account_name
                FROM pending_changes pc JOIN ynab_transactions t ON pc.transaction_id = t.id {where_clause} ORDER BY t.date DESC""",
                params,
            ).fetchall()
            results = []
            for row in rows:
                result = dict(row)
                result["new_values"] = json.loads(row["new_values"]) if row["new_values"] else {}
                result["original_values"] = (
                    json.loads(row["original_values"]) if row["original_values"] else {}
                )
                if not result.get("new_category_id") and result["new_values"].get("category_id"):
                    result["new_category_id"] = result["new_values"]["category_id"]
                    result["new_category_name"] = result["new_values"].get("category_name")
                results.append(result)
            return results

    def delete_pending_change(self, transaction_id: str) -> bool:
        """Delete pending change for a transaction (for undo)."""
        with self._connection() as conn:
            cursor = conn.execute(
                "DELETE FROM pending_changes WHERE transaction_id = ?", (transaction_id,)
            )
            return cursor.rowcount > 0

    def get_pending_change_count(self) -> int:
        """Get count of pending changes."""
        where = f"WHERE budget_id = '{self._budget_id}'" if self._budget_id else ""
        with self._connection() as conn:
            row = conn.execute(f"SELECT COUNT(*) as count FROM pending_changes {where}").fetchone()
            return row["count"] if row else 0

    def apply_pending_change(self, transaction_id: str) -> bool:
        """Apply pending change to ynab_transactions and cleanup."""
        with self._connection() as conn:
            change = conn.execute(
                "SELECT * FROM pending_changes WHERE transaction_id = ?", (transaction_id,)
            ).fetchone()
            if not change:
                return False
            new_values = json.loads(change["new_values"]) if change["new_values"] else {}
            if not new_values:
                if change["new_category_id"]:
                    new_values["category_id"] = change["new_category_id"]
                    new_values["category_name"] = change["new_category_name"]
                if change["new_approved"] is not None:
                    new_values["approved"] = change["new_approved"]
            updates, params = ["sync_status = 'synced'", "synced_at = ?"], [_now_iso()]
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
            conn.execute(f"UPDATE ynab_transactions SET {', '.join(updates)} WHERE id = ?", params)
            conn.execute("DELETE FROM pending_changes WHERE transaction_id = ?", (transaction_id,))
            return True

    def clear_all_pending_changes(self) -> int:
        """Clear all pending changes."""
        with self._connection() as conn:
            cursor = conn.execute("DELETE FROM pending_changes")
            return cursor.rowcount

    # =========================================================================
    # History Methods
    # =========================================================================

    @staticmethod
    def normalize_payee(payee: str) -> str:
        """Normalize payee name for consistent matching."""
        return payee.lower().strip()

    @staticmethod
    def normalize_item(item_name: str) -> str:
        """Normalize item name for consistent matching."""
        return item_name.lower().strip()

    def add_categorization(
        self,
        payee_name: str,
        category_name: str,
        category_id: str,
        amount: Optional[float] = None,
        amazon_items: Optional[list[str]] = None,
        transaction_id: Optional[str] = None,
        transaction_date: Optional[date] = None,
    ) -> int:
        """Record a categorization decision for learning.

        Args:
            payee_name: The payee name.
            category_name: The category name.
            category_id: The category ID.
            amount: Optional transaction amount.
            amazon_items: Optional list of Amazon item names.
            transaction_id: Optional transaction ID (prevents duplicate entries).
            transaction_date: Optional transaction date (for recency sorting).

        Returns:
            Row ID if inserted, 0 if skipped (duplicate transaction_id).
        """
        with self._connection() as conn:
            try:
                cursor = conn.execute(
                    """INSERT INTO categorization_history
                    (payee_name, payee_normalized, amount, category_name, category_id, amazon_items, transaction_id, transaction_date)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        payee_name,
                        self.normalize_payee(payee_name),
                        amount,
                        category_name,
                        category_id,
                        json.dumps(amazon_items) if amazon_items else None,
                        transaction_id,
                        transaction_date.isoformat() if transaction_date else None,
                    ),
                )
                return cursor.lastrowid or 0
            except sqlite3.IntegrityError:
                # Duplicate transaction_id - already recorded
                return 0

    def needs_history_backfill(self) -> bool:
        """Check if categorization history needs to be backfilled from transactions.

        Returns True if:
        - History table has no entries with transaction_id (pre-migration data)
        - Or history count is much smaller than categorized transaction count
        """
        with self._connection() as conn:
            # Count history entries with transaction_id
            history_with_txn = conn.execute(
                "SELECT COUNT(*) as count FROM categorization_history WHERE transaction_id IS NOT NULL"
            ).fetchone()["count"]

            # Count categorized transactions
            categorized_txns = conn.execute(
                "SELECT COUNT(*) as count FROM ynab_transactions WHERE category_id IS NOT NULL AND category_id != ''"
            ).fetchone()["count"]

            # Backfill needed if history with transaction_id is much smaller
            # Allow some slack (90%) since some transactions may be uncategorized
            return history_with_txn < categorized_txns * 0.5

    def backfill_categorization_history(self, progress_callback=None) -> int:
        """Backfill categorization history from existing transactions.

        Args:
            progress_callback: Optional callback(current, total) for progress updates.

        Returns:
            Number of entries added.
        """
        with self._connection() as conn:
            # Get all categorized transactions not already in history
            rows = conn.execute(
                """SELECT t.id, t.payee_name, t.category_name, t.category_id, t.amount, t.date
                FROM ynab_transactions t
                WHERE t.category_id IS NOT NULL AND t.category_id != ''
                AND t.payee_name IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1 FROM categorization_history h WHERE h.transaction_id = t.id
                )"""
            ).fetchall()

            total = len(rows)
            added = 0

            for i, row in enumerate(rows):
                try:
                    conn.execute(
                        """INSERT INTO categorization_history
                        (payee_name, payee_normalized, amount, category_name, category_id, transaction_id, transaction_date)
                        VALUES (?,?,?,?,?,?,?)""",
                        (
                            row["payee_name"],
                            self.normalize_payee(row["payee_name"]),
                            row["amount"],
                            row["category_name"],
                            row["category_id"],
                            row["id"],
                            row["date"],
                        ),
                    )
                    added += 1
                except sqlite3.IntegrityError:
                    # Skip duplicates
                    pass

                if progress_callback and (i + 1) % 100 == 0:
                    progress_callback(i + 1, total)

            # Final progress callback
            if progress_callback:
                progress_callback(total, total)

            return added

    def get_payee_history(self, payee_name: str, limit: int = 100) -> list[CategorizationRecord]:
        """Get categorization history for a payee."""
        normalized = self.normalize_payee(payee_name)
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT id, payee_name, payee_normalized, amount, category_name, category_id, amazon_items, created_at
                FROM categorization_history WHERE payee_normalized = ? ORDER BY created_at DESC LIMIT ?""",
                (normalized, limit),
            ).fetchall()
            return [
                CategorizationRecord(
                    id=row["id"],
                    payee_name=row["payee_name"],
                    payee_normalized=row["payee_normalized"],
                    amount=row["amount"],
                    category_name=row["category_name"],
                    category_id=row["category_id"],
                    amazon_items=json.loads(row["amazon_items"]) if row["amazon_items"] else None,
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
                for row in rows
            ]

    def get_payee_category_distribution(
        self, payee_name: str, sort_by: str = "count"
    ) -> dict[str, dict[str, float | int | str]]:
        """Get category distribution for a payee.

        Args:
            payee_name: The payee name to look up.
            sort_by: Sort order - "count" (most used) or "recent" (most recent).

        Returns:
            Dict mapping category_name -> {count, percentage, avg_amount, category_id, last_used}.
        """
        normalized = self.normalize_payee(payee_name)
        order_clause = "ORDER BY last_used DESC" if sort_by == "recent" else "ORDER BY count DESC"
        with self._connection() as conn:
            rows = conn.execute(
                f"""SELECT category_name, category_id, COUNT(*) as count, AVG(amount) as avg_amount,
                    MAX(transaction_date) as last_used
                FROM categorization_history WHERE payee_normalized = ?
                GROUP BY category_name, category_id {order_clause}""",
                (normalized,),
            ).fetchall()
            if not rows:
                return {}
            total = sum(row["count"] for row in rows)
            return {
                row["category_name"]: {
                    "count": row["count"],
                    "percentage": row["count"] / total,
                    "avg_amount": row["avg_amount"],
                    "category_id": row["category_id"],
                    "last_used": row["last_used"],
                }
                for row in rows
            }

    def get_payee_category_distributions_batch(
        self, payee_names: list[str]
    ) -> dict[str, dict[str, dict[str, float | int | str]]]:
        """Get category distributions for multiple payees in one query."""
        if not payee_names:
            return {}
        normalized_map = {self.normalize_payee(p): p for p in payee_names}
        normalized_names = list(normalized_map.keys())
        with self._connection() as conn:
            placeholders = ",".join("?" * len(normalized_names))
            rows = conn.execute(
                f"""SELECT payee_normalized, category_name, category_id, COUNT(*) as count, AVG(amount) as avg_amount
                FROM categorization_history WHERE payee_normalized IN ({placeholders})
                GROUP BY payee_normalized, category_name, category_id ORDER BY payee_normalized, count DESC""",
                normalized_names,
            ).fetchall()
            if not rows:
                return {}
            result: dict[str, dict[str, dict[str, float | int | str]]] = {}
            payee_totals: dict[str, int] = {}
            for row in rows:
                payee_totals[row["payee_normalized"]] = (
                    payee_totals.get(row["payee_normalized"], 0) + row["count"]
                )
            for row in rows:
                payee_norm = row["payee_normalized"]
                original_payee = normalized_map.get(payee_norm, payee_norm)
                if original_payee not in result:
                    result[original_payee] = {}
                total = payee_totals[payee_norm]
                result[original_payee][row["category_name"]] = {
                    "count": row["count"],
                    "percentage": row["count"] / total,
                    "avg_amount": row["avg_amount"],
                    "category_id": row["category_id"],
                }
            return result

    def record_item_category_learning(
        self,
        item_name: str,
        category_id: str,
        category_name: str,
        source_transaction_id: str | None = None,
        source_order_id: str | None = None,
    ) -> bool:
        """Record a learned item→category mapping."""
        item_name_normalized = self.normalize_item(item_name)
        with self._connection() as conn:
            try:
                conn.execute(
                    """INSERT INTO amazon_item_category_history (item_name, item_name_normalized, category_id, category_name, source_transaction_id, source_order_id)
                    VALUES (?,?,?,?,?,?)""",
                    (
                        item_name,
                        item_name_normalized,
                        category_id,
                        category_name,
                        source_transaction_id,
                        source_order_id,
                    ),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def get_item_category_distribution(self, item_name: str) -> dict[str, dict[str, Any]]:
        """Get category distribution for an item."""
        item_name_normalized = self.normalize_item(item_name)
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT category_id, category_name, COUNT(*) as count FROM amazon_item_category_history
                WHERE item_name_normalized = ? GROUP BY category_id, category_name ORDER BY count DESC""",
                (item_name_normalized,),
            ).fetchall()
            if not rows:
                return {}
            total = sum(row["count"] for row in rows)
            return {
                row["category_id"]: {
                    "name": row["category_name"],
                    "count": row["count"],
                    "percentage": row["count"] / total if total > 0 else 0,
                }
                for row in rows
            }

    def get_item_category_distributions_batch(
        self, item_names: list[str]
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """Get category distributions for multiple items in one query.

        Args:
            item_names: List of item names to look up.

        Returns:
            Dict mapping item_name -> {category_id: {name, count, percentage}, ...}
        """
        if not item_names:
            return {}
        normalized_map = {self.normalize_item(name): name for name in item_names}
        normalized_names = list(normalized_map.keys())
        with self._connection() as conn:
            placeholders = ",".join("?" * len(normalized_names))
            rows = conn.execute(
                f"""SELECT item_name_normalized, category_id, category_name, COUNT(*) as count
                FROM amazon_item_category_history
                WHERE item_name_normalized IN ({placeholders})
                GROUP BY item_name_normalized, category_id, category_name
                ORDER BY item_name_normalized, count DESC""",
                normalized_names,
            ).fetchall()
            if not rows:
                return {}
            # Calculate totals per item
            item_totals: dict[str, int] = {}
            for row in rows:
                item_totals[row["item_name_normalized"]] = (
                    item_totals.get(row["item_name_normalized"], 0) + row["count"]
                )
            # Build result dict
            result: dict[str, dict[str, dict[str, Any]]] = {}
            for row in rows:
                item_norm = row["item_name_normalized"]
                original_item = normalized_map.get(item_norm, item_norm)
                if original_item not in result:
                    result[original_item] = {}
                total = item_totals[item_norm]
                result[original_item][row["category_id"]] = {
                    "name": row["category_name"],
                    "count": row["count"],
                    "percentage": row["count"] / total if total > 0 else 0,
                }
            return result

    def get_all_item_category_mappings(
        self, search_term: str | None = None, category_filter: str | None = None
    ) -> list[dict[str, Any]]:
        """Get all learned item→category mappings with statistics."""
        with self._connection() as conn:
            params, where_clauses = [], []
            if search_term:
                where_clauses.append("item_name_normalized LIKE ?")
                params.append(f"%{self.normalize_item(search_term)}%")
            if category_filter:
                where_clauses.append("category_name LIKE ?")
                params.append(f"%{category_filter}%")
            where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            rows = conn.execute(
                f"SELECT DISTINCT item_name_normalized, item_name FROM amazon_item_category_history {where_sql} ORDER BY item_name_normalized",
                params,
            ).fetchall()
            results = []
            for row in rows:
                normalized_name = row["item_name_normalized"]
                category_rows = conn.execute(
                    """SELECT category_id, category_name, COUNT(*) as count FROM amazon_item_category_history
                    WHERE item_name_normalized = ? GROUP BY category_id, category_name ORDER BY count DESC""",
                    (normalized_name,),
                ).fetchall()
                total = sum(cr["count"] for cr in category_rows)
                categories = [
                    {
                        "id": cr["category_id"],
                        "name": cr["category_name"],
                        "count": cr["count"],
                        "percentage": cr["count"] / total if total > 0 else 0,
                    }
                    for cr in category_rows
                ]
                results.append(
                    {
                        "item_name": row["item_name"],
                        "item_name_normalized": normalized_name,
                        "total_count": total,
                        "categories": categories,
                    }
                )
            return results

    def get_item_category_history_count(self) -> int:
        return self._count("amazon_item_category_history")

    def get_unique_item_count(self) -> int:
        """Get count of unique items with learned categories."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT item_name_normalized) as count FROM amazon_item_category_history"
            ).fetchone()
            return row["count"] if row else 0

    # =========================================================================
    # Sync Methods
    # =========================================================================

    def _get_sync_key(self, base_key: str) -> str:
        """Get budget-specific sync key."""
        if base_key == "amazon":
            return base_key
        if self._budget_id:
            return f"{base_key}:{self._budget_id}"
        return base_key

    def get_sync_state(self, key: str) -> Optional[dict[str, Any]]:
        """Get sync state for a given key."""
        actual_key = self._get_sync_key(key)
        with self._connection() as conn:
            row = conn.execute(
                "SELECT key, last_sync_date, last_sync_at, record_count FROM sync_state WHERE key = ?",
                (actual_key,),
            ).fetchone()
            if not row:
                return None
            return {
                "key": row["key"],
                "last_sync_date": datetime.strptime(row["last_sync_date"], "%Y-%m-%d")
                if row["last_sync_date"]
                else None,
                "last_sync_at": datetime.fromisoformat(row["last_sync_at"])
                if row["last_sync_at"]
                else None,
                "record_count": row["record_count"],
            }

    def update_sync_state(self, key: str, last_sync_date: datetime, record_count: int) -> None:
        """Update sync state for a given key."""
        actual_key = self._get_sync_key(key)
        with self._connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sync_state (key, last_sync_date, last_sync_at, record_count) VALUES (?,?,?,?)",
                (actual_key, _date_str(last_sync_date), _now_iso(), record_count),
            )
