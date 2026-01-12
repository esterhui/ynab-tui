"""Tests for pending change update bugs.

These tests verify that when a pending change is updated (e.g., category changed
from A to B when already pending), the new value persists correctly.

TDD approach: These tests are written first and should FAIL until the bug is fixed.
"""

from datetime import datetime

from ynab_tui.db.database import Database
from ynab_tui.models import Transaction


def _insert_test_transaction(db: Database, txn_id: str = "txn-001", **kwargs) -> None:
    """Helper to insert a test transaction directly into the database."""
    defaults = {
        "budget_id": "test-budget",
        "date": "2025-01-15",
        "amount": -5000,  # $50.00 in milliunits
        "payee_name": "Test Store",
        "payee_id": "payee-001",
        "category_id": None,
        "category_name": None,
        "account_name": "Checking",
        "account_id": "acc-001",
        "memo": None,
        "cleared": "cleared",
        "approved": False,
        "is_split": False,
        "parent_transaction_id": None,
        "sync_status": "synced",
    }
    defaults.update(kwargs)

    with db._connection() as conn:
        conn.execute(
            """INSERT INTO ynab_transactions
               (id, budget_id, date, amount, payee_name, payee_id, category_id, category_name,
                account_name, account_id, memo, cleared, approved, is_split,
                parent_transaction_id, sync_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                txn_id,
                defaults["budget_id"],
                defaults["date"],
                defaults["amount"],
                defaults["payee_name"],
                defaults["payee_id"],
                defaults["category_id"],
                defaults["category_name"],
                defaults["account_name"],
                defaults["account_id"],
                defaults["memo"],
                defaults["cleared"],
                defaults["approved"],
                defaults["is_split"],
                defaults["parent_transaction_id"],
                defaults["sync_status"],
            ),
        )


class TestCategoryUpdateBug:
    """Tests for the category update persistence bug."""

    def test_update_category_twice_persists_second_value(self, temp_db: Database):
        """When category is changed twice, second value should persist via get_ynab_transactions."""
        _insert_test_transaction(temp_db, "txn-001")

        # First change: None -> cat-1 (Groceries)
        temp_db.create_pending_change(
            transaction_id="txn-001",
            new_values={"category_id": "cat-1", "category_name": "Groceries"},
            original_values={"category_id": None, "category_name": None},
        )

        # Second change: cat-1 -> cat-2 (Electronics)
        # This simulates what happens when the user changes the category again
        temp_db.create_pending_change(
            transaction_id="txn-001",
            new_values={"category_id": "cat-2", "category_name": "Electronics"},
            original_values={"category_id": "cat-1", "category_name": "Groceries"},
        )

        # Fetch transaction using the same method TUI uses
        transactions = temp_db.get_ynab_transactions()
        txn = next((t for t in transactions if t["id"] == "txn-001"), None)

        assert txn is not None
        # BUG: This currently returns "cat-1" because legacy columns aren't updated
        assert txn["category_id"] == "cat-2", f"Expected cat-2, got {txn['category_id']}"
        assert txn["category_name"] == "Electronics", (
            f"Expected Electronics, got {txn['category_name']}"
        )

    def test_update_category_preserves_true_original(self, temp_db: Database):
        """When category is changed twice, original_values should contain TRUE original."""
        _insert_test_transaction(temp_db, "txn-001")

        # First change: None -> cat-1
        temp_db.create_pending_change(
            transaction_id="txn-001",
            new_values={"category_id": "cat-1", "category_name": "Groceries"},
            original_values={"category_id": None, "category_name": None},
        )

        # Second change: cat-1 -> cat-2
        temp_db.create_pending_change(
            transaction_id="txn-001",
            new_values={"category_id": "cat-2", "category_name": "Electronics"},
            original_values={"category_id": "cat-1", "category_name": "Groceries"},
        )

        # Check the pending change record
        pending = temp_db.get_pending_change("txn-001")
        assert pending is not None

        # new_values should have the latest category
        new_vals = pending.get("new_values", {})
        assert new_vals.get("category_id") == "cat-2"
        assert new_vals.get("category_name") == "Electronics"

        # original_values should have the TRUE original (None), not the intermediate (cat-1)
        orig_vals = pending.get("original_values", {})
        assert orig_vals.get("category_id") is None, (
            f"Expected None, got {orig_vals.get('category_id')}"
        )
        assert orig_vals.get("category_name") is None


class TestMemoUpdateBug:
    """Tests for the memo update persistence bug."""

    def test_update_memo_twice_persists_second_value(self, temp_db: Database):
        """When memo is changed twice, second value should persist."""
        _insert_test_transaction(temp_db, "txn-001", memo="Original memo")

        # First change: Original -> First update
        temp_db.create_pending_change(
            transaction_id="txn-001",
            new_values={"memo": "First update"},
            original_values={"memo": "Original memo"},
        )

        # Second change: First update -> Second update
        temp_db.create_pending_change(
            transaction_id="txn-001",
            new_values={"memo": "Second update"},
            original_values={"memo": "First update"},
        )

        pending = temp_db.get_pending_change("txn-001")
        assert pending is not None

        new_vals = pending.get("new_values", {})
        assert new_vals.get("memo") == "Second update"

        # Original should be the TRUE original
        orig_vals = pending.get("original_values", {})
        assert orig_vals.get("memo") == "Original memo"


class TestApprovedStatusBug:
    """Tests for the approved status update persistence bug."""

    def test_approve_twice_persists_final_state(self, temp_db: Database):
        """When approved status changes multiple times, final state should persist."""
        _insert_test_transaction(temp_db, "txn-001", approved=False)

        # First change: False -> True (approve)
        temp_db.create_pending_change(
            transaction_id="txn-001",
            new_values={"approved": True},
            original_values={"approved": False},
        )

        # Second change: True -> False (unapprove)
        temp_db.create_pending_change(
            transaction_id="txn-001",
            new_values={"approved": False},
            original_values={"approved": True},
        )

        # Fetch via get_ynab_transactions
        transactions = temp_db.get_ynab_transactions()
        txn = next((t for t in transactions if t["id"] == "txn-001"), None)

        assert txn is not None
        # BUG: This may return True if legacy columns aren't updated
        assert txn["approved"] is False or txn["approved"] == 0


class TestMixedFieldUpdates:
    """Tests for updating multiple different fields sequentially."""

    def test_category_then_memo_preserves_both_updates(self, temp_db: Database):
        """Category change then memo change should both persist."""
        _insert_test_transaction(temp_db, "txn-001", memo="Original memo")

        # First change: category
        temp_db.create_pending_change(
            transaction_id="txn-001",
            new_values={"category_id": "cat-1", "category_name": "Groceries"},
            original_values={"category_id": None, "category_name": None},
        )

        # Second change: memo (simulates separate edit)
        temp_db.create_pending_change(
            transaction_id="txn-001",
            new_values={"memo": "New memo"},
            original_values={"memo": "Original memo"},
        )

        pending = temp_db.get_pending_change("txn-001")
        assert pending is not None

        new_vals = pending.get("new_values", {})
        # Both updates should be present
        assert new_vals.get("category_id") == "cat-1"
        assert new_vals.get("memo") == "New memo"

        orig_vals = pending.get("original_values", {})
        # Both originals should be preserved
        assert orig_vals.get("category_id") is None
        assert orig_vals.get("memo") == "Original memo"

    def test_three_sequential_field_updates(self, temp_db: Database):
        """Three sequential updates to different fields should all persist."""
        _insert_test_transaction(temp_db, "txn-001", memo=None, approved=False)

        # First: category
        temp_db.create_pending_change(
            transaction_id="txn-001",
            new_values={"category_id": "cat-1", "category_name": "Groceries"},
            original_values={"category_id": None, "category_name": None},
        )

        # Second: memo
        temp_db.create_pending_change(
            transaction_id="txn-001",
            new_values={"memo": "Added memo"},
            original_values={"memo": None},
        )

        # Third: approved
        temp_db.create_pending_change(
            transaction_id="txn-001",
            new_values={"approved": True},
            original_values={"approved": False},
        )

        pending = temp_db.get_pending_change("txn-001")
        new_vals = pending.get("new_values", {})
        orig_vals = pending.get("original_values", {})

        # All three updates should be in new_values
        assert new_vals.get("category_id") == "cat-1"
        assert new_vals.get("memo") == "Added memo"
        assert new_vals.get("approved") is True

        # All three originals should be preserved
        assert orig_vals.get("category_id") is None
        assert orig_vals.get("memo") is None
        assert orig_vals.get("approved") is False


class TestSplitTransactionBug:
    """Tests for split transaction pending change updates."""

    def test_resplit_persists_new_splits(self, temp_db: Database):
        """Re-splitting should persist the new split configuration."""
        _insert_test_transaction(temp_db, "txn-001", amount=-10000)  # $100

        # First split: 2 items
        temp_db.create_pending_change(
            transaction_id="txn-001",
            new_values={"category_id": None, "category_name": "Split"},
            original_values={"category_id": None, "category_name": None},
            change_type="split",
        )
        temp_db.mark_pending_split(
            transaction_id="txn-001",
            splits=[
                {
                    "category_id": "cat-1",
                    "category_name": "Groceries",
                    "amount": -6000,
                    "memo": None,
                },
                {"category_id": "cat-2", "category_name": "Home", "amount": -4000, "memo": None},
            ],
        )

        # Verify first split
        splits1 = temp_db.get_pending_splits("txn-001")
        assert len(splits1) == 2

        # Re-split: 3 items
        temp_db.create_pending_change(
            transaction_id="txn-001",
            new_values={"category_id": None, "category_name": "Split"},
            original_values={"category_id": None, "category_name": None},
            change_type="split",
        )
        temp_db.mark_pending_split(
            transaction_id="txn-001",
            splits=[
                {
                    "category_id": "cat-1",
                    "category_name": "Groceries",
                    "amount": -5000,
                    "memo": None,
                },
                {"category_id": "cat-2", "category_name": "Home", "amount": -3000, "memo": None},
                {
                    "category_id": "cat-3",
                    "category_name": "Electronics",
                    "amount": -2000,
                    "memo": None,
                },
            ],
        )

        # Verify new splits replaced old
        splits2 = temp_db.get_pending_splits("txn-001")
        assert len(splits2) == 3
        assert splits2[0]["category_id"] == "cat-1"
        assert splits2[1]["category_id"] == "cat-2"
        assert splits2[2]["category_id"] == "cat-3"


class TestEndToEndFlow:
    """End-to-end tests simulating TUI restart scenario."""

    def test_tui_restart_preserves_second_category(self, temp_db: Database):
        """Simulates: categorize, exit, reopen, re-categorize, exit, reopen - should show second category."""
        _insert_test_transaction(temp_db, "txn-001")

        # Session 1: User categorizes as Groceries
        temp_db.create_pending_change(
            transaction_id="txn-001",
            new_values={"category_id": "cat-1", "category_name": "Groceries", "approved": True},
            original_values={"category_id": None, "category_name": None, "approved": False},
        )

        # Simulate TUI restart - fetch transactions
        txns_after_first = temp_db.get_ynab_transactions()
        txn1 = next((t for t in txns_after_first if t["id"] == "txn-001"), None)
        assert txn1["category_name"] == "Groceries"

        # Session 2: User changes to Electronics
        temp_db.create_pending_change(
            transaction_id="txn-001",
            new_values={"category_id": "cat-2", "category_name": "Electronics", "approved": True},
            original_values={
                "category_id": "cat-1",
                "category_name": "Groceries",
                "approved": True,
            },
        )

        # Simulate TUI restart - fetch transactions again
        txns_after_second = temp_db.get_ynab_transactions()
        txn2 = next((t for t in txns_after_second if t["id"] == "txn-001"), None)

        # BUG: This currently fails - shows "Groceries" instead of "Electronics"
        assert txn2["category_name"] == "Electronics", (
            f"Expected 'Electronics' but got '{txn2['category_name']}'. "
            "The second category change was not persisted!"
        )
        assert txn2["category_id"] == "cat-2"


class TestRevertToOriginal:
    """Tests for reverting a change back to the original value."""

    def test_revert_category_to_original_removes_pending_change(self, temp_db: Database):
        """When category is changed back to original, pending change should be deleted."""
        # Transaction starts with Downpayment category
        _insert_test_transaction(
            temp_db, "txn-001", category_id="cat-downpayment", category_name="Downpayment"
        )

        # First change: Downpayment -> Dining
        temp_db.create_pending_change(
            transaction_id="txn-001",
            new_values={"category_id": "cat-dining", "category_name": "Dining"},
            original_values={"category_id": "cat-downpayment", "category_name": "Downpayment"},
        )

        # Verify pending change exists
        pending = temp_db.get_pending_change("txn-001")
        assert pending is not None

        # Second change: Dining -> Downpayment (back to original)
        temp_db.create_pending_change(
            transaction_id="txn-001",
            new_values={"category_id": "cat-downpayment", "category_name": "Downpayment"},
            original_values={"category_id": "cat-dining", "category_name": "Dining"},
        )

        # BUG: Pending change should be DELETED since we're back to original
        pending_after = temp_db.get_pending_change("txn-001")
        assert pending_after is None, (
            "Pending change should be deleted when category reverts to original. "
            f"Got: new_values={pending_after.get('new_values') if pending_after else None}"
        )

        # Transaction should show original category (no pending overlay)
        transactions = temp_db.get_ynab_transactions()
        txn = next((t for t in transactions if t["id"] == "txn-001"), None)
        assert txn["category_id"] == "cat-downpayment"
        assert txn["sync_status"] == "synced"  # Not pending_push

    def test_revert_memo_to_original_removes_pending_change(self, temp_db: Database):
        """When memo is changed back to original, pending change should be deleted."""
        _insert_test_transaction(temp_db, "txn-001", memo="Original memo")

        # First change
        temp_db.create_pending_change(
            transaction_id="txn-001",
            new_values={"memo": "New memo"},
            original_values={"memo": "Original memo"},
        )

        # Second change back to original
        temp_db.create_pending_change(
            transaction_id="txn-001",
            new_values={"memo": "Original memo"},
            original_values={"memo": "New memo"},
        )

        # Pending change should be deleted
        pending = temp_db.get_pending_change("txn-001")
        assert pending is None, "Pending change should be deleted when memo reverts to original"

    def test_revert_one_field_keeps_other_pending(self, temp_db: Database):
        """When one field reverts but another has changes, pending change should remain."""
        _insert_test_transaction(
            temp_db, "txn-001", category_id=None, category_name=None, memo="Original memo"
        )

        # First: Add category
        temp_db.create_pending_change(
            transaction_id="txn-001",
            new_values={"category_id": "cat-1", "category_name": "Groceries"},
            original_values={"category_id": None, "category_name": None},
        )

        # Second: Change memo
        temp_db.create_pending_change(
            transaction_id="txn-001",
            new_values={"memo": "New memo"},
            original_values={"memo": "Original memo"},
        )

        # Third: Revert category to original (None)
        temp_db.create_pending_change(
            transaction_id="txn-001",
            new_values={"category_id": None, "category_name": None},
            original_values={"category_id": "cat-1", "category_name": "Groceries"},
        )

        # Pending change should still exist (memo is still changed)
        pending = temp_db.get_pending_change("txn-001")
        assert pending is not None, "Pending change should remain for memo changes"

        new_vals = pending.get("new_values", {})
        orig_vals = pending.get("original_values", {})

        # Category should not be in new_values since it's reverted
        assert new_vals.get("category_id") is None
        # Memo should still be pending
        assert new_vals.get("memo") == "New memo"
        assert orig_vals.get("memo") == "Original memo"

    def test_revert_all_fields_removes_pending_change(self, temp_db: Database):
        """When all changed fields revert to original, pending change should be deleted."""
        _insert_test_transaction(
            temp_db,
            "txn-001",
            category_id="cat-orig",
            category_name="Original",
            memo="Original memo",
        )

        # Change both fields
        temp_db.create_pending_change(
            transaction_id="txn-001",
            new_values={
                "category_id": "cat-new",
                "category_name": "New Category",
                "memo": "New memo",
            },
            original_values={
                "category_id": "cat-orig",
                "category_name": "Original",
                "memo": "Original memo",
            },
        )

        # Revert both back to original
        temp_db.create_pending_change(
            transaction_id="txn-001",
            new_values={
                "category_id": "cat-orig",
                "category_name": "Original",
                "memo": "Original memo",
            },
            original_values={
                "category_id": "cat-new",
                "category_name": "New Category",
                "memo": "New memo",
            },
        )

        # Pending change should be deleted
        pending = temp_db.get_pending_change("txn-001")
        assert pending is None, "Pending change should be deleted when all fields revert"


class TestServiceLayerRevert:
    """Tests for revert behavior at the service layer (CategorizerService)."""

    def test_apply_category_revert_updates_sync_status(
        self, temp_db: Database, sample_config, mock_ynab_client
    ):
        """When category reverts to original, Transaction.sync_status should be 'synced'."""
        from ynab_tui.services.categorizer import CategorizerService

        # Insert transaction with existing category (already approved)
        _insert_test_transaction(
            temp_db,
            "txn-001",
            category_id="cat-downpayment",
            category_name="Downpayment",
            sync_status="synced",
            approved=True,  # Already approved - focus on category revert
        )

        # Create Transaction object matching DB state
        txn = Transaction(
            id="txn-001",
            date=datetime(2025, 1, 15),
            amount=-5000,
            payee_name="Test Store",
            category_id="cat-downpayment",
            category_name="Downpayment",
            sync_status="synced",
            approved=True,  # Already approved
        )

        categorizer = CategorizerService(sample_config, mock_ynab_client, temp_db)

        # First change: Downpayment -> Dining
        txn = categorizer.apply_category(txn, "cat-dining", "Dining")
        assert txn.sync_status == "pending_push"
        assert txn.category_name == "Dining"

        # Second change: Dining -> Downpayment (revert to original)
        txn = categorizer.apply_category(txn, "cat-downpayment", "Downpayment")

        # BUG: sync_status should be "synced" since we reverted to original
        # Currently it stays "pending_push"
        assert txn.sync_status == "synced", (
            f"Expected sync_status='synced' after reverting to original, "
            f"but got '{txn.sync_status}'"
        )
        assert txn.category_name == "Downpayment"

        # Verify no pending change in DB
        pending = temp_db.get_pending_change("txn-001")
        assert pending is None

    def test_apply_memo_revert_updates_sync_status(
        self, temp_db: Database, sample_config, mock_ynab_client
    ):
        """When memo reverts to original, Transaction.sync_status should be 'synced'."""
        from ynab_tui.services.categorizer import CategorizerService

        _insert_test_transaction(temp_db, "txn-001", memo="Original memo", sync_status="synced")

        txn = Transaction(
            id="txn-001",
            date=datetime(2025, 1, 15),
            amount=-5000,
            payee_name="Test Store",
            memo="Original memo",
            sync_status="synced",
        )

        categorizer = CategorizerService(sample_config, mock_ynab_client, temp_db)

        # First change
        txn = categorizer.apply_memo(txn, "New memo")
        assert txn.sync_status == "pending_push"

        # Revert to original
        txn = categorizer.apply_memo(txn, "Original memo")

        # Should be synced again
        assert txn.sync_status == "synced", (
            f"Expected sync_status='synced' after reverting memo, got '{txn.sync_status}'"
        )

    def test_partial_revert_keeps_pending_status(
        self, temp_db: Database, sample_config, mock_ynab_client
    ):
        """When one field reverts but another is still changed, sync_status stays pending."""
        from ynab_tui.services.categorizer import CategorizerService

        _insert_test_transaction(
            temp_db,
            "txn-001",
            category_id=None,
            category_name=None,
            memo="Original memo",
            sync_status="synced",
        )

        txn = Transaction(
            id="txn-001",
            date=datetime(2025, 1, 15),
            amount=-5000,
            payee_name="Test Store",
            category_id=None,
            category_name=None,
            memo="Original memo",
            sync_status="synced",
        )

        categorizer = CategorizerService(sample_config, mock_ynab_client, temp_db)

        # Add category
        txn = categorizer.apply_category(txn, "cat-1", "Groceries")
        assert txn.sync_status == "pending_push"

        # Change memo
        txn = categorizer.apply_memo(txn, "New memo")
        assert txn.sync_status == "pending_push"

        # Revert category to None (but memo is still changed)
        txn = categorizer.apply_category(txn, None, None)

        # Should still be pending because memo is changed
        assert txn.sync_status == "pending_push"
        pending = temp_db.get_pending_change("txn-001")
        assert pending is not None
