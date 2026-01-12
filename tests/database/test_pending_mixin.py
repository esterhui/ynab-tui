"""Tests for PendingChangesMixin database operations.

These tests use a real temporary SQLite database.
"""

from pathlib import Path

import pytest

from ynab_tui.db.database import Database


@pytest.fixture
def temp_db(tmp_path: Path) -> Database:
    """Create a temporary database for testing."""
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))
    yield db
    db.close()


@pytest.fixture
def db_with_transaction(temp_db: Database) -> Database:
    """Create db with a sample transaction for pending change tests."""
    with temp_db._connection() as conn:
        conn.execute(
            """
            INSERT INTO ynab_transactions
            (id, date, amount, payee_name, account_name, category_id,
             category_name, approved, memo, sync_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "txn-001",
                "2025-11-24",
                -4499,
                "Amazon",
                "Checking",
                None,
                None,
                False,
                None,
                "synced",
            ),
        )
    return temp_db


class TestPendingChangesMixin:
    """Tests for pending changes database operations."""

    def test_create_pending_change(self, db_with_transaction: Database) -> None:
        """Can create a pending change."""
        result = db_with_transaction.create_pending_change(
            transaction_id="txn-001",
            new_values={"category_id": "cat-1", "category_name": "Groceries"},
            original_values={"category_id": None, "category_name": None},
        )

        assert result == "created"

        # Verify it was created
        change = db_with_transaction.get_pending_change("txn-001")
        assert change is not None
        assert change["new_values"]["category_id"] == "cat-1"
        assert change["original_values"]["category_id"] is None

    def test_create_pending_change_with_approved(self, db_with_transaction: Database) -> None:
        """Can create pending change for approval."""
        db_with_transaction.create_pending_change(
            transaction_id="txn-001",
            new_values={"approved": True},
            original_values={"approved": False},
        )

        change = db_with_transaction.get_pending_change("txn-001")
        assert change is not None
        assert change["new_values"]["approved"] is True
        assert change["original_values"]["approved"] is False

    def test_create_pending_change_with_memo(self, db_with_transaction: Database) -> None:
        """Can create pending change for memo."""
        db_with_transaction.create_pending_change(
            transaction_id="txn-001",
            new_values={"memo": "New memo text"},
            original_values={"memo": None},
        )

        change = db_with_transaction.get_pending_change("txn-001")
        assert change is not None
        assert change["new_values"]["memo"] == "New memo text"

    def test_merge_pending_changes(self, db_with_transaction: Database) -> None:
        """Multiple pending changes merge correctly."""
        # First change: set category
        db_with_transaction.create_pending_change(
            transaction_id="txn-001",
            new_values={"category_id": "cat-1", "category_name": "Groceries"},
            original_values={"category_id": None, "category_name": None},
        )

        # Second change: also approve
        db_with_transaction.create_pending_change(
            transaction_id="txn-001",
            new_values={"approved": True},
            original_values={"approved": False},
        )

        change = db_with_transaction.get_pending_change("txn-001")
        assert change is not None
        # Both changes should be merged
        assert change["new_values"]["category_id"] == "cat-1"
        assert change["new_values"]["approved"] is True
        # Original values preserved from first change
        assert change["original_values"]["category_id"] is None
        assert change["original_values"]["approved"] is False

    def test_get_pending_change_not_found(self, temp_db: Database) -> None:
        """get_pending_change returns None for non-existent."""
        change = temp_db.get_pending_change("nonexistent")
        assert change is None

    def test_delete_pending_change(self, db_with_transaction: Database) -> None:
        """Can delete a pending change."""
        db_with_transaction.create_pending_change(
            transaction_id="txn-001",
            new_values={"category_id": "cat-1"},
            original_values={"category_id": None},
        )

        # Verify it exists
        assert db_with_transaction.get_pending_change("txn-001") is not None

        # Delete it
        result = db_with_transaction.delete_pending_change("txn-001")
        assert result is True

        # Verify it's gone
        assert db_with_transaction.get_pending_change("txn-001") is None

    def test_delete_pending_change_not_found(self, temp_db: Database) -> None:
        """delete_pending_change returns False for non-existent."""
        result = temp_db.delete_pending_change("nonexistent")
        assert result is False

    def test_get_pending_change_count(self, db_with_transaction: Database) -> None:
        """Can count pending changes."""
        # Initially 0
        assert db_with_transaction.get_pending_change_count() == 0

        # Add some
        db_with_transaction.create_pending_change(
            "txn-001", {"category_id": "c1"}, {"category_id": None}
        )

        assert db_with_transaction.get_pending_change_count() == 1

    def test_get_all_pending_changes(self, temp_db: Database) -> None:
        """Can get all pending changes with transaction details."""
        # Create two transactions
        with temp_db._connection() as conn:
            conn.execute(
                """
                INSERT INTO ynab_transactions
                (id, date, amount, payee_name, account_name, approved, sync_status)
                VALUES
                ('txn-1', '2025-11-24', -1000, 'Payee1', 'Checking', 0, 'synced'),
                ('txn-2', '2025-11-25', -2000, 'Payee2', 'Checking', 0, 'synced')
                """
            )

        # Create pending changes
        temp_db.create_pending_change(
            "txn-1", {"category_id": "c1", "category_name": "Cat1"}, {"category_id": None}
        )
        temp_db.create_pending_change("txn-2", {"approved": True}, {"approved": False})

        changes = temp_db.get_all_pending_changes()

        assert len(changes) == 2
        # Should be ordered by date DESC
        assert changes[0]["transaction_id"] == "txn-2"
        assert changes[1]["transaction_id"] == "txn-1"
        # Should include transaction details
        assert changes[0]["payee_name"] == "Payee2"
        assert changes[1]["payee_name"] == "Payee1"

    def test_get_all_pending_changes_empty(self, temp_db: Database) -> None:
        """get_all_pending_changes returns empty list when none."""
        changes = temp_db.get_all_pending_changes()
        assert changes == []

    def test_apply_pending_change(self, db_with_transaction: Database) -> None:
        """apply_pending_change updates transaction and removes pending."""
        # Create pending change
        db_with_transaction.create_pending_change(
            transaction_id="txn-001",
            new_values={"category_id": "cat-1", "category_name": "Groceries"},
            original_values={"category_id": None, "category_name": None},
        )

        # Apply it
        result = db_with_transaction.apply_pending_change("txn-001")
        assert result is True

        # Pending change should be gone
        assert db_with_transaction.get_pending_change("txn-001") is None

        # Transaction should be updated
        with db_with_transaction._connection() as conn:
            row = conn.execute(
                "SELECT category_id, category_name, sync_status FROM ynab_transactions WHERE id = ?",
                ("txn-001",),
            ).fetchone()
            assert row["category_id"] == "cat-1"
            assert row["category_name"] == "Groceries"
            assert row["sync_status"] == "synced"

    def test_apply_pending_change_not_found(self, temp_db: Database) -> None:
        """apply_pending_change returns False for non-existent."""
        result = temp_db.apply_pending_change("nonexistent")
        assert result is False

    def test_clear_all_pending_changes(self, db_with_transaction: Database) -> None:
        """Can clear all pending changes."""
        # Create some pending changes
        with db_with_transaction._connection() as conn:
            conn.execute(
                """
                INSERT INTO ynab_transactions
                (id, date, amount, payee_name, account_name, approved, sync_status)
                VALUES ('txn-2', '2025-11-25', -2000, 'Payee2', 'Checking', 0, 'synced')
                """
            )

        db_with_transaction.create_pending_change(
            "txn-001", {"category_id": "c1"}, {"category_id": None}
        )
        db_with_transaction.create_pending_change(
            "txn-2", {"category_id": "c2"}, {"category_id": None}
        )

        assert db_with_transaction.get_pending_change_count() == 2

        # Clear all
        count = db_with_transaction.clear_all_pending_changes()
        assert count == 2
        assert db_with_transaction.get_pending_change_count() == 0

    def test_apply_pending_change_with_approval(self, db_with_transaction: Database) -> None:
        """apply_pending_change handles approved field."""
        db_with_transaction.create_pending_change(
            transaction_id="txn-001",
            new_values={"approved": True},
            original_values={"approved": False},
        )

        db_with_transaction.apply_pending_change("txn-001")

        with db_with_transaction._connection() as conn:
            row = conn.execute(
                "SELECT approved FROM ynab_transactions WHERE id = ?",
                ("txn-001",),
            ).fetchone()
            assert row["approved"] == 1  # SQLite stores booleans as integers

    def test_apply_pending_change_with_memo(self, db_with_transaction: Database) -> None:
        """apply_pending_change handles memo field."""
        db_with_transaction.create_pending_change(
            transaction_id="txn-001",
            new_values={"memo": "Updated memo"},
            original_values={"memo": None},
        )

        db_with_transaction.apply_pending_change("txn-001")

        with db_with_transaction._connection() as conn:
            row = conn.execute(
                "SELECT memo FROM ynab_transactions WHERE id = ?",
                ("txn-001",),
            ).fetchone()
            assert row["memo"] == "Updated memo"
