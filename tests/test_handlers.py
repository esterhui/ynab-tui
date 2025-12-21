"""Tests for pure TUI action handlers.

These tests verify the ActionHandler class without requiring
any Textual infrastructure. CategorizerService is mocked.
"""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from ynab_tui.models import Transaction
from ynab_tui.tui.handlers import ActionHandler, ActionResult


class TestActionResult:
    """Tests for ActionResult dataclass."""

    def test_success_result(self):
        """Test creating successful result."""
        result = ActionResult(success=True, message="Done")
        assert result.success is True
        assert result.message == "Done"
        assert result.error is None

    def test_failure_result(self):
        """Test creating failed result."""
        result = ActionResult(success=False, message="", error="Failed")
        assert result.success is False
        assert result.error == "Failed"

    def test_ok_factory(self):
        """Test ActionResult.ok() factory method."""
        result = ActionResult.ok("Success", "txn-123")
        assert result.success is True
        assert result.message == "Success"
        assert result.transaction_id == "txn-123"
        assert result.error is None

    def test_fail_factory(self):
        """Test ActionResult.fail() factory method."""
        result = ActionResult.fail("Error occurred", "txn-123")
        assert result.success is False
        assert result.error == "Error occurred"
        assert result.transaction_id == "txn-123"
        assert result.message == ""


class TestActionHandler:
    """Tests for ActionHandler methods."""

    @pytest.fixture
    def mock_categorizer(self):
        """Create mock categorizer service."""
        return MagicMock()

    @pytest.fixture
    def handler(self, mock_categorizer):
        """Create handler with mock categorizer."""
        return ActionHandler(mock_categorizer)

    @pytest.fixture
    def sample_transaction(self):
        """Create sample transaction."""
        return Transaction(
            id="txn-123",
            date=datetime(2025, 1, 1),
            amount=-50.00,
            payee_name="Store",
            category_id="cat-old",
            category_name="Old Category",
        )


class TestCategorize(TestActionHandler):
    """Tests for categorize action."""

    def test_categorize_success(self, handler, mock_categorizer, sample_transaction):
        """Test successful categorization."""
        result = handler.categorize(sample_transaction, "cat-new", "New Category")

        assert result.success is True
        assert "New Category" in result.message
        assert result.transaction_id == "txn-123"
        mock_categorizer.apply_category.assert_called_once_with(
            sample_transaction, "cat-new", "New Category"
        )

    def test_categorize_failure(self, handler, mock_categorizer, sample_transaction):
        """Test failed categorization."""
        mock_categorizer.apply_category.side_effect = ValueError("Invalid category")

        result = handler.categorize(sample_transaction, "cat-bad", "Bad Category")

        assert result.success is False
        assert "Invalid category" in result.error
        assert result.transaction_id == "txn-123"


class TestCategorizeBatch(TestActionHandler):
    """Tests for batch categorization."""

    @pytest.fixture
    def sample_transactions(self):
        """Create multiple sample transactions."""
        date = datetime(2025, 1, 1)
        return [
            Transaction(id="txn-1", date=date, amount=-10, payee_name="Store 1"),
            Transaction(id="txn-2", date=date, amount=-20, payee_name="Store 2"),
            Transaction(id="txn-3", date=date, amount=-30, payee_name="Store 3"),
        ]

    def test_batch_all_success(self, handler, mock_categorizer, sample_transactions):
        """Test all transactions categorized successfully."""
        result = handler.categorize_batch(sample_transactions, "cat-new", "Groceries")

        assert result.success is True
        assert "3 transactions" in result.message
        assert "Groceries" in result.message
        assert mock_categorizer.apply_category.call_count == 3

    def test_batch_partial_failure(self, handler, mock_categorizer, sample_transactions):
        """Test some transactions fail to categorize."""
        # First call succeeds, second fails, third succeeds
        mock_categorizer.apply_category.side_effect = [
            None,
            ValueError("Error"),
            None,
        ]

        result = handler.categorize_batch(sample_transactions, "cat-new", "Groceries")

        assert result.success is True  # At least some succeeded
        assert "2/3" in result.message

    def test_batch_all_fail(self, handler, mock_categorizer, sample_transactions):
        """Test all transactions fail to categorize."""
        mock_categorizer.apply_category.side_effect = ValueError("Error")

        result = handler.categorize_batch(sample_transactions, "cat-new", "Groceries")

        assert result.success is False
        assert "Failed" in result.error

    def test_batch_empty_list(self, handler, mock_categorizer):
        """Test batch with empty list."""
        result = handler.categorize_batch([], "cat-new", "Groceries")

        assert result.success is False
        assert "No transactions" in result.error
        mock_categorizer.apply_category.assert_not_called()


class TestApprove(TestActionHandler):
    """Tests for approve action."""

    def test_approve_success(self, handler, mock_categorizer, sample_transaction):
        """Test successful approval."""
        mock_categorizer.approve_transaction.return_value = MagicMock(approved=True)

        result = handler.approve(sample_transaction)

        assert result.success is True
        assert "approved" in result.message.lower()
        assert result.transaction_id == "txn-123"

    def test_approve_already_approved(self, handler, mock_categorizer, sample_transaction):
        """Test approving already approved transaction."""
        mock_categorizer.approve_transaction.return_value = MagicMock(approved=False)

        result = handler.approve(sample_transaction)

        assert result.success is True
        assert "already approved" in result.message.lower()

    def test_approve_failure(self, handler, mock_categorizer, sample_transaction):
        """Test failed approval."""
        mock_categorizer.approve_transaction.side_effect = RuntimeError("API error")

        result = handler.approve(sample_transaction)

        assert result.success is False
        assert "API error" in result.error


class TestApproveBatch(TestActionHandler):
    """Tests for batch approval."""

    @pytest.fixture
    def sample_transactions(self):
        """Create multiple sample transactions."""
        date = datetime(2025, 1, 1)
        return [
            Transaction(id="txn-1", date=date, amount=-10, payee_name="Store 1"),
            Transaction(id="txn-2", date=date, amount=-20, payee_name="Store 2"),
        ]

    def test_batch_approve_all_success(self, handler, mock_categorizer, sample_transactions):
        """Test all transactions approved successfully."""
        mock_categorizer.approve_transaction.return_value = MagicMock(approved=True)

        result = handler.approve_batch(sample_transactions)

        assert result.success is True
        assert "2" in result.message
        assert mock_categorizer.approve_transaction.call_count == 2

    def test_batch_approve_some_already(self, handler, mock_categorizer, sample_transactions):
        """Test some transactions already approved."""
        mock_categorizer.approve_transaction.side_effect = [
            MagicMock(approved=True),
            MagicMock(approved=False),  # Already approved
        ]

        result = handler.approve_batch(sample_transactions)

        assert result.success is True
        assert "already approved" in result.message.lower()

    def test_batch_approve_all_already(self, handler, mock_categorizer, sample_transactions):
        """Test all transactions already approved."""
        mock_categorizer.approve_transaction.return_value = MagicMock(approved=False)

        result = handler.approve_batch(sample_transactions)

        assert result.success is True
        assert "already approved" in result.message.lower()

    def test_batch_approve_empty(self, handler, mock_categorizer):
        """Test batch with empty list."""
        result = handler.approve_batch([])

        assert result.success is False
        assert "No transactions" in result.error

    def test_batch_approve_some_failed(self, handler, mock_categorizer, sample_transactions):
        """Test some approvals throw exceptions."""
        mock_categorizer.approve_transaction.side_effect = [
            MagicMock(approved=True),
            RuntimeError("API error"),
        ]

        result = handler.approve_batch(sample_transactions)

        # At least one succeeded, so we still show partial success info
        assert result.success is False
        assert "Failed" in result.error


class TestUndo(TestActionHandler):
    """Tests for undo action."""

    def test_undo_success(self, handler, mock_categorizer, sample_transaction):
        """Test successful undo."""
        restored = Transaction(
            id="txn-123",
            date=datetime(2025, 1, 1),
            amount=-50.00,
            payee_name="Store",
            category_name="Original Category",
        )
        mock_categorizer.undo_category.return_value = restored

        result = handler.undo(sample_transaction)

        assert result.success is True
        assert "Original Category" in result.message
        assert result.transaction_id == "txn-123"

    def test_undo_to_uncategorized(self, handler, mock_categorizer, sample_transaction):
        """Test undo restores to uncategorized."""
        restored = Transaction(
            id="txn-123",
            date=datetime(2025, 1, 1),
            amount=-50.00,
            payee_name="Store",
            category_name=None,
        )
        mock_categorizer.undo_category.return_value = restored

        result = handler.undo(sample_transaction)

        assert result.success is True
        assert "Uncategorized" in result.message

    def test_undo_failure(self, handler, mock_categorizer, sample_transaction):
        """Test failed undo."""
        mock_categorizer.undo_category.side_effect = ValueError("Nothing to undo")

        result = handler.undo(sample_transaction)

        assert result.success is False
        assert "Nothing to undo" in result.error

    def test_undo_same_category(self, handler, mock_categorizer):
        """Test undo when category doesn't change (or was already None)."""
        # Transaction with no category change (both old and new are None)
        txn = Transaction(
            id="txn-123",
            date=datetime(2025, 1, 1),
            amount=-50.00,
            payee_name="Store",
            category_name=None,  # Same as restored
        )
        # Restored also has None category
        restored = Transaction(
            id="txn-123",
            date=datetime(2025, 1, 1),
            amount=-50.00,
            payee_name="Store",
            category_name=None,
        )
        mock_categorizer.undo_category.return_value = restored

        result = handler.undo(txn)

        assert result.success is True
        assert "undone" in result.message.lower()


class TestUndoBatch(TestActionHandler):
    """Tests for batch undo."""

    @pytest.fixture
    def sample_transactions(self):
        """Create multiple sample transactions."""
        date = datetime(2025, 1, 1)
        return [
            Transaction(id="txn-1", date=date, amount=-10, payee_name="Store 1"),
            Transaction(id="txn-2", date=date, amount=-20, payee_name="Store 2"),
        ]

    def test_batch_undo_all_success(self, handler, mock_categorizer, sample_transactions):
        """Test all transactions undone successfully."""
        result = handler.undo_batch(sample_transactions)

        assert result.success is True
        assert "2" in result.message
        assert mock_categorizer.undo_category.call_count == 2

    def test_batch_undo_partial(self, handler, mock_categorizer, sample_transactions):
        """Test some transactions fail to undo."""
        mock_categorizer.undo_category.side_effect = [None, ValueError("Error")]

        result = handler.undo_batch(sample_transactions)

        assert result.success is True
        assert "1/2" in result.message

    def test_batch_undo_empty(self, handler, mock_categorizer):
        """Test batch with empty list."""
        result = handler.undo_batch([])

        assert result.success is False
        assert "No transactions" in result.error

    def test_batch_undo_all_fail(self, handler, mock_categorizer, sample_transactions):
        """Test all undo operations fail."""
        mock_categorizer.undo_category.side_effect = ValueError("Nothing to undo")

        result = handler.undo_batch(sample_transactions)

        assert result.success is False
        assert "Failed" in result.error


class TestUpdateMemo(TestActionHandler):
    """Tests for memo update action."""

    def test_update_memo_success(self, handler, mock_categorizer, sample_transaction):
        """Test successful memo update."""
        result = handler.update_memo(sample_transaction, "New memo text")

        assert result.success is True
        assert "updated" in result.message.lower()
        mock_categorizer.apply_memo.assert_called_once_with(sample_transaction, "New memo text")

    def test_clear_memo(self, handler, mock_categorizer, sample_transaction):
        """Test clearing memo."""
        result = handler.update_memo(sample_transaction, "")

        assert result.success is True
        assert "cleared" in result.message.lower()

    def test_update_memo_failure(self, handler, mock_categorizer, sample_transaction):
        """Test failed memo update."""
        mock_categorizer.apply_memo.side_effect = RuntimeError("DB error")

        result = handler.update_memo(sample_transaction, "New memo")

        assert result.success is False
        assert "DB error" in result.error


class TestSplit(TestActionHandler):
    """Tests for split action."""

    def test_split_success(self, handler, mock_categorizer, sample_transaction):
        """Test successful split."""
        splits = [
            {"category_id": "cat-1", "category_name": "Food", "amount": -25.00},
            {"category_id": "cat-2", "category_name": "Clothes", "amount": -25.00},
        ]

        result = handler.split(sample_transaction, splits)

        assert result.success is True
        assert "2 categories" in result.message
        mock_categorizer.apply_split_categories.assert_called_once()

    def test_split_empty_splits(self, handler, mock_categorizer, sample_transaction):
        """Test split with empty splits list."""
        result = handler.split(sample_transaction, [])

        assert result.success is False
        assert "No splits" in result.error
        mock_categorizer.apply_split_categories.assert_not_called()

    def test_split_failure(self, handler, mock_categorizer, sample_transaction):
        """Test failed split."""
        mock_categorizer.apply_split_categories.side_effect = ValueError("Amounts don't match")

        splits = [{"category_id": "cat-1", "category_name": "Food", "amount": -10.00}]
        result = handler.split(sample_transaction, splits)

        assert result.success is False
        assert "Amounts don't match" in result.error
