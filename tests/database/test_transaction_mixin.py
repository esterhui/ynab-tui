"""Tests for TransactionMixin database operations.

These tests use a real temporary SQLite database.
"""

from datetime import datetime
from pathlib import Path

import pytest

from ynab_tui.db.database import Database
from ynab_tui.db.models import TransactionFilter
from ynab_tui.models import Transaction


@pytest.fixture
def temp_db(tmp_path: Path) -> Database:
    """Create a temporary database for testing."""
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))
    yield db
    db.close()


def make_transaction(
    id: str = "txn-001",
    date: datetime | None = None,
    amount: int = -4499,
    payee_name: str = "Amazon",
    account_name: str = "Checking",
    category_id: str | None = None,
    category_name: str | None = None,
    approved: bool = False,
    memo: str | None = None,
    is_split: bool = False,
    transfer_account_id: str | None = None,
) -> Transaction:
    """Create a test transaction."""
    return Transaction(
        id=id,
        date=date or datetime(2025, 11, 24),
        amount=amount,
        payee_name=payee_name,
        account_name=account_name,
        category_id=category_id,
        category_name=category_name,
        approved=approved,
        memo=memo,
        is_split=is_split,
        transfer_account_id=transfer_account_id,
    )


class TestTransactionMixin:
    """Tests for YNAB transaction database operations."""

    def test_upsert_new_transaction(self, temp_db: Database) -> None:
        """Can insert a new transaction."""
        txn = make_transaction()
        was_inserted, was_changed = temp_db.upsert_ynab_transaction(txn)

        assert was_inserted is True
        assert was_changed is True

        # Verify it was stored
        stored = temp_db.get_ynab_transaction("txn-001")
        assert stored is not None
        assert stored["payee_name"] == "Amazon"
        assert stored["amount"] == -4499

    def test_upsert_update_existing(self, temp_db: Database) -> None:
        """Can update an existing transaction."""
        txn1 = make_transaction(category_id=None)
        temp_db.upsert_ynab_transaction(txn1)

        # Update with category
        txn2 = make_transaction(category_id="cat-1", category_name="Groceries")
        was_inserted, was_changed = temp_db.upsert_ynab_transaction(txn2)

        assert was_inserted is False
        assert was_changed is True

        stored = temp_db.get_ynab_transaction("txn-001")
        assert stored["category_id"] == "cat-1"
        assert stored["category_name"] == "Groceries"

    def test_upsert_no_change(self, temp_db: Database) -> None:
        """Upserting unchanged transaction returns was_changed=False."""
        txn = make_transaction()
        temp_db.upsert_ynab_transaction(txn)

        # Upsert same transaction again
        was_inserted, was_changed = temp_db.upsert_ynab_transaction(txn)

        assert was_inserted is False
        assert was_changed is False

    def test_get_transaction_not_found(self, temp_db: Database) -> None:
        """get_ynab_transaction returns None for non-existent."""
        result = temp_db.get_ynab_transaction("nonexistent")
        assert result is None

    def test_get_transactions_all(self, temp_db: Database) -> None:
        """Can get all transactions."""
        temp_db.upsert_ynab_transaction(make_transaction("txn-1"))
        temp_db.upsert_ynab_transaction(make_transaction("txn-2"))
        temp_db.upsert_ynab_transaction(make_transaction("txn-3"))

        txns = temp_db.get_ynab_transactions()
        assert len(txns) == 3

    def test_get_transactions_uncategorized_only(self, temp_db: Database) -> None:
        """Can filter to uncategorized transactions."""
        temp_db.upsert_ynab_transaction(
            make_transaction("txn-1", category_id=None, category_name=None)
        )
        temp_db.upsert_ynab_transaction(
            make_transaction("txn-2", category_id="cat-1", category_name="Groceries")
        )

        txns = temp_db.get_ynab_transactions(uncategorized_only=True)
        assert len(txns) == 1
        assert txns[0]["id"] == "txn-1"

    def test_get_transactions_approved_only(self, temp_db: Database) -> None:
        """Can filter to approved transactions."""
        temp_db.upsert_ynab_transaction(make_transaction("txn-1", approved=True))
        temp_db.upsert_ynab_transaction(make_transaction("txn-2", approved=False))

        txns = temp_db.get_ynab_transactions(approved_only=True)
        assert len(txns) == 1
        assert txns[0]["id"] == "txn-1"

    def test_get_transactions_unapproved_only(self, temp_db: Database) -> None:
        """Can filter to unapproved transactions."""
        temp_db.upsert_ynab_transaction(make_transaction("txn-1", approved=True))
        temp_db.upsert_ynab_transaction(make_transaction("txn-2", approved=False))

        txns = temp_db.get_ynab_transactions(unapproved_only=True)
        assert len(txns) == 1
        assert txns[0]["id"] == "txn-2"

    def test_get_transactions_payee_filter(self, temp_db: Database) -> None:
        """Can filter by payee name."""
        temp_db.upsert_ynab_transaction(make_transaction("txn-1", payee_name="Amazon"))
        temp_db.upsert_ynab_transaction(make_transaction("txn-2", payee_name="Walmart"))
        temp_db.upsert_ynab_transaction(make_transaction("txn-3", payee_name="Amazon Prime"))

        txns = temp_db.get_ynab_transactions(payee_filter="Amazon")
        assert len(txns) == 2
        payees = {t["payee_name"] for t in txns}
        assert payees == {"Amazon", "Amazon Prime"}

    def test_get_transactions_limit(self, temp_db: Database) -> None:
        """Can limit results."""
        for i in range(10):
            temp_db.upsert_ynab_transaction(
                make_transaction(f"txn-{i}", date=datetime(2025, 11, i + 1))
            )

        txns = temp_db.get_ynab_transactions(limit=3)
        assert len(txns) == 3

    def test_get_transactions_since_date(self, temp_db: Database) -> None:
        """Can filter by since_date."""
        temp_db.upsert_ynab_transaction(make_transaction("txn-1", date=datetime(2025, 11, 1)))
        temp_db.upsert_ynab_transaction(make_transaction("txn-2", date=datetime(2025, 11, 15)))
        temp_db.upsert_ynab_transaction(make_transaction("txn-3", date=datetime(2025, 11, 20)))

        txns = temp_db.get_ynab_transactions(since_date=datetime(2025, 11, 10))
        assert len(txns) == 2

    def test_get_transactions_with_filter_object(self, temp_db: Database) -> None:
        """Can use TransactionFilter object."""
        temp_db.upsert_ynab_transaction(make_transaction("txn-1", approved=True))
        temp_db.upsert_ynab_transaction(make_transaction("txn-2", approved=False))

        filter_obj = TransactionFilter(approved_only=True)
        txns = temp_db.get_ynab_transactions(filter=filter_obj)
        assert len(txns) == 1
        assert txns[0]["id"] == "txn-1"

    def test_get_transactions_excludes_transfers(self, temp_db: Database) -> None:
        """Uncategorized filter excludes transfers."""
        temp_db.upsert_ynab_transaction(
            make_transaction("txn-1", category_id=None, transfer_account_id=None)
        )
        temp_db.upsert_ynab_transaction(
            make_transaction("txn-2", category_id=None, transfer_account_id="acct-123")
        )

        txns = temp_db.get_ynab_transactions(uncategorized_only=True)
        assert len(txns) == 1
        assert txns[0]["id"] == "txn-1"

    def test_mark_synced(self, temp_db: Database) -> None:
        """Can mark transaction as synced."""
        temp_db.upsert_ynab_transaction(make_transaction())

        result = temp_db.mark_synced("txn-001")
        assert result is True

        stored = temp_db.get_ynab_transaction("txn-001")
        assert stored["sync_status"] == "synced"

    def test_get_transaction_count(self, temp_db: Database) -> None:
        """Can count transactions."""
        assert temp_db.get_transaction_count() == 0

        temp_db.upsert_ynab_transaction(make_transaction("txn-1"))
        temp_db.upsert_ynab_transaction(make_transaction("txn-2"))

        assert temp_db.get_transaction_count() == 2

    def test_get_uncategorized_count(self, temp_db: Database) -> None:
        """Can count uncategorized transactions."""
        temp_db.upsert_ynab_transaction(make_transaction("txn-1", category_id=None))
        temp_db.upsert_ynab_transaction(
            make_transaction("txn-2", category_id="cat-1", category_name="Groceries")
        )

        assert temp_db.get_uncategorized_count() == 1

    def test_get_pending_push_count(self, temp_db: Database) -> None:
        """Can count pending push transactions via pending_changes table."""
        temp_db.upsert_ynab_transaction(make_transaction("txn-1"))
        temp_db.upsert_ynab_transaction(make_transaction("txn-2"))
        temp_db.create_pending_change(
            "txn-1",
            new_values={"category_id": "cat-1", "category_name": "Groceries"},
            original_values={"category_id": None, "category_name": None},
        )

        # pending_push_only=True uses pending_changes table
        txns = temp_db.get_ynab_transactions(pending_push_only=True)
        assert len(txns) == 1

    def test_get_transaction_date_range(self, temp_db: Database) -> None:
        """Can get transaction date range."""
        temp_db.upsert_ynab_transaction(make_transaction("txn-1", date=datetime(2025, 11, 1)))
        temp_db.upsert_ynab_transaction(make_transaction("txn-2", date=datetime(2025, 11, 15)))
        temp_db.upsert_ynab_transaction(make_transaction("txn-3", date=datetime(2025, 11, 30)))

        earliest, latest = temp_db.get_transaction_date_range()
        assert earliest == "2025-11-01"
        assert latest == "2025-11-30"

    def test_get_transaction_date_range_empty(self, temp_db: Database) -> None:
        """Empty database returns None date range."""
        earliest, latest = temp_db.get_transaction_date_range()
        assert earliest is None
        assert latest is None

    def test_upsert_batch_transactions(self, temp_db: Database) -> None:
        """Can batch upsert transactions."""
        txns = [
            make_transaction("txn-1"),
            make_transaction("txn-2"),
            make_transaction("txn-3"),
        ]

        inserted, updated = temp_db.upsert_ynab_transactions(txns)
        assert inserted == 3
        assert updated == 0

        # Update one
        txns[0] = make_transaction("txn-1", memo="Updated")
        inserted, updated = temp_db.upsert_ynab_transactions([txns[0]])
        assert inserted == 0
        assert updated == 1

    def test_get_transaction_by_amount_date(self, temp_db: Database) -> None:
        """Can find transaction by amount and date."""
        temp_db.upsert_ynab_transaction(
            make_transaction("txn-1", amount=-4499, date=datetime(2025, 11, 24))
        )
        temp_db.upsert_ynab_transaction(
            make_transaction("txn-2", amount=-9999, date=datetime(2025, 11, 24))
        )

        result = temp_db.get_ynab_transaction_by_amount_date(
            amount=-4499,
            date=datetime(2025, 11, 24),
        )

        assert result is not None
        assert result["id"] == "txn-1"

    def test_get_transaction_by_amount_date_with_tolerance(self, temp_db: Database) -> None:
        """Amount matching uses tolerance."""
        temp_db.upsert_ynab_transaction(
            make_transaction("txn-1", amount=-4499, date=datetime(2025, 11, 24))
        )

        # Slightly different amount within tolerance
        result = temp_db.get_ynab_transaction_by_amount_date(
            amount=-4498,
            date=datetime(2025, 11, 24),
            tolerance=1.0,
        )

        assert result is not None
        assert result["id"] == "txn-1"

    def test_get_transaction_by_amount_date_not_found(self, temp_db: Database) -> None:
        """Returns None when no match found."""
        temp_db.upsert_ynab_transaction(
            make_transaction("txn-1", amount=-4499, date=datetime(2025, 11, 24))
        )

        result = temp_db.get_ynab_transaction_by_amount_date(
            amount=-9999,
            date=datetime(2025, 11, 24),
        )

        assert result is None


class TestPendingSplits:
    """Tests for pending split operations."""

    def test_mark_pending_split(self, temp_db: Database) -> None:
        """Can mark transaction as pending split."""
        temp_db.upsert_ynab_transaction(make_transaction())

        splits = [
            {"category_id": "cat-1", "category_name": "Groceries", "amount": -2000},
            {"category_id": "cat-2", "category_name": "Household", "amount": -2499},
        ]

        result = temp_db.mark_pending_split("txn-001", splits)
        assert result is True

        stored = temp_db.get_ynab_transaction("txn-001")
        assert stored["sync_status"] == "pending_push"
        assert stored["is_split"] == 1
        assert stored["category_name"] == "Split (pending)"

    def test_get_pending_splits(self, temp_db: Database) -> None:
        """Can get pending splits."""
        temp_db.upsert_ynab_transaction(make_transaction())
        temp_db.mark_pending_split(
            "txn-001",
            [
                {"category_id": "cat-1", "category_name": "Groceries", "amount": -2000},
                {"category_id": "cat-2", "category_name": "Household", "amount": -2499},
            ],
        )

        splits = temp_db.get_pending_splits("txn-001")
        assert len(splits) == 2
        assert splits[0]["category_id"] == "cat-1"
        assert splits[1]["category_id"] == "cat-2"

    def test_clear_pending_splits(self, temp_db: Database) -> None:
        """Can clear pending splits."""
        temp_db.upsert_ynab_transaction(make_transaction())
        temp_db.mark_pending_split(
            "txn-001",
            [{"category_id": "cat-1", "category_name": "Groceries", "amount": -2000}],
        )

        result = temp_db.clear_pending_splits("txn-001")
        assert result is True

        splits = temp_db.get_pending_splits("txn-001")
        assert len(splits) == 0

    def test_clear_pending_splits_not_found(self, temp_db: Database) -> None:
        """clear_pending_splits returns False when none exist."""
        result = temp_db.clear_pending_splits("nonexistent")
        assert result is False
