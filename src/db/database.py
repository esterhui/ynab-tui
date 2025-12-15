"""SQLite database management for YNAB Categorizer.

Handles connection management and provides query methods for:
- Categorization history (for learning from past decisions)
- Amazon order cache (to avoid re-scraping)
- YNAB transactions (synced from YNAB API)
- Sync state tracking

The Database class uses mixins to organize domain-specific operations:
- TransactionMixin: YNAB transaction CRUD
- AmazonMixin: Amazon orders and items
- CategoryMixin: YNAB categories
- PendingChangesMixin: Pending changes for undo support
- HistoryMixin: Categorization and item learning history
- SyncMixin: Sync state tracking
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from .mixins import (
    AmazonMixin,
    CategoryMixin,
    HistoryMixin,
    PendingChangesMixin,
    SyncMixin,
    TransactionMixin,
)
from .mixins.base import CountMixin

# Re-export models for backwards compatibility
from .models import AmazonOrderCache, CategorizationRecord, TransactionFilter

__all__ = [
    "Database",
    "AmazonOrderCache",
    "CategorizationRecord",
    "TransactionFilter",
]


class Database(
    TransactionMixin,
    AmazonMixin,
    CategoryMixin,
    PendingChangesMixin,
    HistoryMixin,
    SyncMixin,
    CountMixin,
):
    """SQLite database manager for categorization history and caching.

    Inherits domain-specific operations from mixins while providing
    core connection management and schema initialization.
    """

    def __init__(self, db_path: Path, budget_id: Optional[str] = None):
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database file.
            budget_id: Optional budget ID to filter data by. If None, no filtering.
        """
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
        """Get or create a persistent database connection.

        Uses a single connection for all operations to avoid connection overhead.
        Thread-safe with check_same_thread=False.
        """
        if self._conn is None:
            self._conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=30.0,
            )
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
    def _connection(self):
        """Context manager for database connections.

        Uses a persistent connection for better performance.
        Handles commit/rollback automatically.
        """
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _init_schema(self):
        """Create database tables if they don't exist."""
        with self._connection() as conn:
            conn.executescript(
                """
                -- Historical categorizations for learning
                CREATE TABLE IF NOT EXISTS categorization_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payee_name TEXT NOT NULL,
                    payee_normalized TEXT NOT NULL,
                    amount REAL,
                    category_name TEXT NOT NULL,
                    category_id TEXT NOT NULL,
                    amazon_items TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- Cached Amazon orders (avoid re-scraping)
                CREATE TABLE IF NOT EXISTS amazon_orders_cache (
                    order_id TEXT PRIMARY KEY,
                    order_date DATE NOT NULL,
                    total REAL NOT NULL,
                    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- YNAB transactions (synced from YNAB API)
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

                -- Amazon order items (normalized for category matching)
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

                -- Amazon item category learning history
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

                -- Sync state tracking
                CREATE TABLE IF NOT EXISTS sync_state (
                    key TEXT PRIMARY KEY,
                    last_sync_date DATE,
                    last_sync_at TIMESTAMP,
                    record_count INTEGER
                );

                -- YNAB categories (synced from YNAB API)
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

                -- Pending splits (local-only, pushed to YNAB later)
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

                CREATE INDEX IF NOT EXISTS idx_pending_splits_txn
                ON pending_splits(transaction_id);

                -- Pending changes (delta table for undo capability)
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

                CREATE INDEX IF NOT EXISTS idx_pending_changes_txn
                ON pending_changes(transaction_id);

                -- Index for payee lookups
                CREATE INDEX IF NOT EXISTS idx_payee_normalized
                ON categorization_history(payee_normalized);

                -- Index for date-based order lookups
                CREATE INDEX IF NOT EXISTS idx_order_date
                ON amazon_orders_cache(order_date);

                -- Indexes for YNAB transactions
                CREATE INDEX IF NOT EXISTS idx_ynab_date
                ON ynab_transactions(date);

                CREATE INDEX IF NOT EXISTS idx_ynab_payee
                ON ynab_transactions(payee_name);

                CREATE INDEX IF NOT EXISTS idx_ynab_category
                ON ynab_transactions(category_id);

                CREATE INDEX IF NOT EXISTS idx_ynab_approved
                ON ynab_transactions(approved);

                CREATE INDEX IF NOT EXISTS idx_ynab_sync_status
                ON ynab_transactions(sync_status);

                CREATE INDEX IF NOT EXISTS idx_ynab_parent
                ON ynab_transactions(parent_transaction_id);

                -- Indexes for Amazon order items
                CREATE INDEX IF NOT EXISTS idx_amazon_item_order
                ON amazon_order_items(order_id);

                CREATE INDEX IF NOT EXISTS idx_amazon_item_name
                ON amazon_order_items(item_name);

                -- Index for Amazon item category history
                CREATE INDEX IF NOT EXISTS idx_item_cat_history_name
                ON amazon_item_category_history(item_name_normalized);

                -- Indexes for YNAB categories
                CREATE INDEX IF NOT EXISTS idx_category_group
                ON ynab_categories(group_id);

                CREATE INDEX IF NOT EXISTS idx_category_name
                ON ynab_categories(name);

                -- Index for transfer lookups
                CREATE INDEX IF NOT EXISTS idx_ynab_transfer
                ON ynab_transactions(transfer_account_id);
                """
            )

            self._migrate_add_transfer_columns(conn)
            self._migrate_pending_to_delta_table(conn)
            self._migrate_add_approval_columns(conn)
            self._migrate_add_budget_id_columns(conn)

    def _migrate_add_transfer_columns(self, conn) -> None:
        """Add transfer columns to ynab_transactions if they don't exist."""
        cursor = conn.execute("PRAGMA table_info(ynab_transactions)")
        columns = {row[1] for row in cursor.fetchall()}

        if "transfer_account_id" not in columns:
            conn.execute("ALTER TABLE ynab_transactions ADD COLUMN transfer_account_id TEXT")
        if "transfer_account_name" not in columns:
            conn.execute("ALTER TABLE ynab_transactions ADD COLUMN transfer_account_name TEXT")
        if "debt_transaction_type" not in columns:
            conn.execute("ALTER TABLE ynab_transactions ADD COLUMN debt_transaction_type TEXT")

    def _migrate_pending_to_delta_table(self, conn) -> None:
        """Clear any legacy pending_push transactions."""
        cursor = conn.execute(
            """
            UPDATE ynab_transactions
            SET sync_status = 'synced'
            WHERE sync_status = 'pending_push'
            """
        )
        if cursor.rowcount > 0:
            print(f"Migration: Cleared {cursor.rowcount} legacy pending_push transactions")

    def _migrate_add_approval_columns(self, conn) -> None:
        """Add approval columns to pending_changes if they don't exist."""
        cursor = conn.execute("PRAGMA table_info(pending_changes)")
        columns = {row[1] for row in cursor.fetchall()}

        if "new_approved" not in columns:
            conn.execute("ALTER TABLE pending_changes ADD COLUMN new_approved BOOLEAN")
        if "original_approved" not in columns:
            conn.execute("ALTER TABLE pending_changes ADD COLUMN original_approved BOOLEAN")

    def _migrate_add_budget_id_columns(self, conn) -> None:
        """Add budget_id columns to tables that need it."""
        # Check and add to ynab_transactions
        cursor = conn.execute("PRAGMA table_info(ynab_transactions)")
        columns = {row[1] for row in cursor.fetchall()}
        if "budget_id" not in columns:
            conn.execute("ALTER TABLE ynab_transactions ADD COLUMN budget_id TEXT")

        # Check and add to ynab_categories
        cursor = conn.execute("PRAGMA table_info(ynab_categories)")
        columns = {row[1] for row in cursor.fetchall()}
        if "budget_id" not in columns:
            conn.execute("ALTER TABLE ynab_categories ADD COLUMN budget_id TEXT")

        # Check and add to pending_changes
        cursor = conn.execute("PRAGMA table_info(pending_changes)")
        columns = {row[1] for row in cursor.fetchall()}
        if "budget_id" not in columns:
            conn.execute("ALTER TABLE pending_changes ADD COLUMN budget_id TEXT")

        # Check and add to pending_splits
        cursor = conn.execute("PRAGMA table_info(pending_splits)")
        columns = {row[1] for row in cursor.fetchall()}
        if "budget_id" not in columns:
            conn.execute("ALTER TABLE pending_splits ADD COLUMN budget_id TEXT")

        # Create budget-specific indexes (after columns exist)
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_ynab_budget
               ON ynab_transactions(budget_id)"""
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_category_budget
               ON ynab_categories(budget_id)"""
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_pending_changes_budget
               ON pending_changes(budget_id)"""
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_pending_splits_budget
               ON pending_splits(budget_id)"""
        )

    def clear_all(self) -> dict[str, int]:
        """Clear all data from all tables.

        Returns:
            Dict with counts of deleted records per table.
        """
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
