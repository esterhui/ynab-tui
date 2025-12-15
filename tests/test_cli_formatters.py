"""Tests for CLI formatting functions in src/cli/formatters.py."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from src.cli.formatters import (
    display_amazon_match_results,
    display_verbose_items,
    echo_error,
    echo_header,
    echo_success,
    echo_warning,
    format_category_row,
    format_item_prediction,
    format_pull_result,
    format_push_result,
    format_sync_time,
    format_transaction_row,
)
from src.db.database import AmazonOrderCache
from src.services.amazon_matcher import AmazonMatchResult, TransactionInfo
from src.services.category_mapping import ItemCategoryPrediction, OrderCategoryPrediction
from src.services.sync import PullResult, PushResult


class TestFormatSyncTime:
    """Tests for format_sync_time function."""

    def test_with_datetime(self):
        """Test formatting with a datetime value."""
        sync_state = {"last_sync_at": datetime(2024, 6, 15, 14, 30)}
        result = format_sync_time(sync_state)
        assert result == "2024-06-15 14:30"

    def test_with_none_sync_state(self):
        """Test formatting with None sync state."""
        result = format_sync_time(None)
        assert result == "Never"

    def test_with_empty_sync_state(self):
        """Test formatting with empty sync state dict."""
        result = format_sync_time({})
        assert result == "Never"

    def test_with_none_last_sync_at(self):
        """Test formatting with None last_sync_at."""
        sync_state = {"last_sync_at": None}
        result = format_sync_time(sync_state)
        assert result == "Never"


class TestFormatTransactionRow:
    """Tests for format_transaction_row function."""

    def test_basic_transaction(self):
        """Test formatting a basic transaction."""
        txn = {
            "date": "2024-06-15",
            "amount": -47.82,
            "payee_name": "AMAZON.COM",
            "category_name": "Electronics",
        }
        result = format_transaction_row(txn)
        assert "2024-06-15" in result
        assert "$47.82" in result
        assert "AMAZON.COM" in result
        assert "Electronics" in result

    def test_transaction_without_category(self):
        """Test formatting a transaction without category."""
        txn = {
            "date": "2024-06-15",
            "amount": -100.00,
            "payee_name": "Test Payee",
            "category_name": None,
        }
        result = format_transaction_row(txn)
        assert "Uncategorized" in result

    def test_transaction_with_status_pending(self):
        """Test formatting a transaction with pending status."""
        txn = {
            "date": "2024-06-15",
            "amount": -50.00,
            "payee_name": "Test",
            "category_name": "Test Category",
            "sync_status": "pending_push",
        }
        result = format_transaction_row(txn, show_status=True)
        assert "[PENDING]" in result

    def test_transaction_with_status_synced(self):
        """Test formatting a synced transaction doesn't show status."""
        txn = {
            "date": "2024-06-15",
            "amount": -50.00,
            "payee_name": "Test",
            "category_name": "Test Category",
            "sync_status": "synced",
        }
        result = format_transaction_row(txn, show_status=True)
        assert "[PENDING]" not in result

    def test_long_payee_truncation(self):
        """Test that long payee names are truncated to 25 chars."""
        txn = {
            "date": "2024-06-15",
            "amount": -50.00,
            "payee_name": "A" * 50,  # Very long payee name
            "category_name": "Test",
        }
        result = format_transaction_row(txn)
        # Payee should be truncated and padded to 25 chars
        assert len(result) < 150  # Reasonable total length

    def test_transaction_with_empty_values(self):
        """Test formatting a transaction with missing values."""
        txn = {}
        result = format_transaction_row(txn)
        # Should not crash and should show defaults
        assert "Uncategorized" in result
        assert "$0.00" in result


class TestFormatCategoryRow:
    """Tests for format_category_row function."""

    def test_basic_category(self):
        """Test formatting a basic category."""
        cat = {"name": "Electronics"}
        result = format_category_row(cat)
        assert "Electronics" in result

    def test_category_with_group(self):
        """Test formatting a category with group name."""
        cat = {"name": "Electronics"}
        result = format_category_row(cat, group_name="Shopping")
        assert "Shopping" in result
        assert "Electronics" in result

    def test_category_without_name(self):
        """Test formatting a category without name."""
        cat = {}
        result = format_category_row(cat)
        assert result.strip() == ""


class TestEchoFunctions:
    """Tests for echo_success, echo_error, echo_warning, echo_header."""

    def test_echo_success(self, capsys):
        """Test echo_success outputs green checkmark message."""
        echo_success("Operation completed")
        captured = capsys.readouterr()
        assert "✓" in captured.out
        assert "Operation completed" in captured.out

    def test_echo_error(self, capsys):
        """Test echo_error outputs red X message."""
        echo_error("Something failed")
        captured = capsys.readouterr()
        assert "✗" in captured.out
        assert "Something failed" in captured.out

    def test_echo_warning(self, capsys):
        """Test echo_warning outputs yellow warning message."""
        echo_warning("Be careful")
        captured = capsys.readouterr()
        assert "⚠" in captured.out
        assert "Be careful" in captured.out

    def test_echo_header(self, capsys):
        """Test echo_header outputs header with underline."""
        echo_header("Test Header")
        captured = capsys.readouterr()
        assert "Test Header" in captured.out
        assert "===========" in captured.out


class TestFormatPullResult:
    """Tests for format_pull_result function."""

    def test_successful_pull_with_dates(self, capsys):
        """Test formatting a successful pull result with date range."""
        result = PullResult(
            source="ynab",
            fetched=100,
            inserted=50,
            updated=25,
            total=500,
            oldest_date=datetime(2024, 1, 1),
            newest_date=datetime(2024, 6, 15),
        )
        format_pull_result("YNAB", result)
        captured = capsys.readouterr()
        assert "✓" in captured.out
        assert "100" in captured.out
        assert "YNAB" in captured.out
        assert "2024-01-01" in captured.out
        assert "2024-06-15" in captured.out
        assert "Inserted: 50" in captured.out
        assert "Updated: 25" in captured.out
        assert "Total in database: 500" in captured.out

    def test_successful_pull_without_dates(self, capsys):
        """Test formatting a successful pull result without date range."""
        result = PullResult(
            source="amazon",
            fetched=25,
            inserted=10,
            updated=5,
            total=100,
        )
        format_pull_result("Amazon", result)
        captured = capsys.readouterr()
        assert "✓" in captured.out
        assert "25" in captured.out
        assert "Amazon" in captured.out
        # Should not show date range
        assert "Date range" not in captured.out

    def test_failed_pull(self, capsys):
        """Test formatting a failed pull result."""
        result = PullResult(
            source="ynab",
            errors=["Connection failed", "API rate limit exceeded"],
        )
        format_pull_result("YNAB", result)
        captured = capsys.readouterr()
        assert "✗" in captured.out
        assert "Error" in captured.out


class TestFormatPushResult:
    """Tests for format_push_result function."""

    def test_successful_push(self, capsys):
        """Test formatting a successful push result."""
        result = PushResult(pushed=5, succeeded=5)
        format_push_result(result)
        captured = capsys.readouterr()
        assert "✓" in captured.out
        assert "5" in captured.out
        assert "YNAB" in captured.out

    def test_failed_push(self, capsys):
        """Test formatting a failed push result."""
        result = PushResult(
            pushed=5,
            succeeded=3,
            failed=2,
            errors=["Transaction not found", "Invalid category"],
        )
        format_push_result(result)
        captured = capsys.readouterr()
        assert "✗" in captured.out
        assert "2 failures" in captured.out
        assert "Transaction not found" in captured.out
        assert "Invalid category" in captured.out


class TestFormatItemPrediction:
    """Tests for format_item_prediction function."""

    def test_with_category_prediction(self):
        """Test formatting an item with category prediction."""
        prediction = ItemCategoryPrediction(
            item_name="USB Cable",
            category_id="cat-001",
            category_name="Electronics",
            confidence=0.95,
            occurrence_count=10,
        )
        result = format_item_prediction("USB Cable", prediction)
        assert "USB Cable" in result
        assert "Electronics" in result
        assert "95%" in result

    def test_without_category_prediction(self):
        """Test formatting an item without category prediction."""
        prediction = ItemCategoryPrediction(
            item_name="Unknown Item",
            category_id=None,
            category_name=None,
            confidence=0.0,
            occurrence_count=0,
        )
        result = format_item_prediction("Unknown Item", prediction)
        assert "Unknown Item" in result
        assert "[?]" in result


class TestDisplayVerboseItems:
    """Tests for display_verbose_items function."""

    def test_display_items_with_predictions(self, capsys):
        """Test displaying verbose items with category predictions."""
        # Create mock order
        order = MagicMock()
        order.order_id = "order-123"

        # Create mock mapping service
        mapping_service = MagicMock()
        mapping_service.predict_order_categories.return_value = OrderCategoryPrediction(
            order_id="order-123",
            item_predictions=[
                ItemCategoryPrediction(
                    item_name="USB Cable",
                    category_id="cat-001",
                    category_name="Electronics",
                    confidence=0.90,
                    occurrence_count=5,
                ),
                ItemCategoryPrediction(
                    item_name="Phone Case",
                    category_id="cat-002",
                    category_name="Accessories",
                    confidence=0.75,
                    occurrence_count=3,
                ),
            ],
        )

        display_verbose_items(order, mapping_service)
        captured = capsys.readouterr()
        assert "USB Cable" in captured.out
        assert "Electronics" in captured.out
        assert "Phone Case" in captured.out


class TestDisplayAmazonMatchResults:
    """Tests for display_amazon_match_results function."""

    @pytest.fixture
    def sample_transaction_info(self):
        """Create sample TransactionInfo for tests."""
        return TransactionInfo(
            transaction_id="txn-001",
            amount=47.82,
            date=datetime(2024, 6, 15),
            date_str="2024-06-15",
            display_amount="-$47.82",
            approved=False,
        )

    @pytest.fixture
    def sample_order(self):
        """Create sample AmazonOrderCache for tests."""
        return AmazonOrderCache(
            order_id="order-123",
            order_date=datetime(2024, 6, 14),
            total=47.82,
            items=["USB Cable", "Phone Case"],
            fetched_at=datetime(2024, 6, 15),
        )

    def test_empty_results(self, capsys):
        """Test displaying empty match results."""
        result = AmazonMatchResult(
            stage1_matches=[],
            stage2_matches=[],
            duplicate_matches=[],
            combo_matches=[],
            unmatched_transactions=[],
            unmatched_orders=[],
        )
        display_amazon_match_results(result, stage1_window=7, stage2_window=24)
        captured = capsys.readouterr()
        # Should show summary
        assert "Summary:" in captured.out

    def test_stage1_matches(self, capsys, sample_transaction_info, sample_order):
        """Test displaying stage 1 matches."""
        result = AmazonMatchResult(
            stage1_matches=[(sample_transaction_info, sample_order)],
            stage2_matches=[],
            duplicate_matches=[],
            combo_matches=[],
            unmatched_transactions=[],
            unmatched_orders=[],
        )
        display_amazon_match_results(result, stage1_window=7, stage2_window=24)
        captured = capsys.readouterr()
        assert "7-day window" in captured.out
        assert "order-123" in captured.out
        assert "USB Cable" in captured.out
        assert "MATCH:" in captured.out

    def test_stage2_matches(self, capsys, sample_transaction_info, sample_order):
        """Test displaying stage 2 extended matches."""
        result = AmazonMatchResult(
            stage1_matches=[],
            stage2_matches=[(sample_transaction_info, sample_order)],
            duplicate_matches=[],
            combo_matches=[],
            unmatched_transactions=[],
            unmatched_orders=[],
        )
        display_amazon_match_results(result, stage1_window=7, stage2_window=24)
        captured = capsys.readouterr()
        assert "24-day extended window" in captured.out
        assert "EXTENDED MATCH:" in captured.out
        assert "order-123" in captured.out

    def test_approved_transaction_marker(self, capsys, sample_order):
        """Test that approved transactions show 'A' marker."""
        txn = TransactionInfo(
            transaction_id="txn-001",
            amount=47.82,
            date=datetime(2024, 6, 15),
            date_str="2024-06-15",
            display_amount="-$47.82",
            approved=True,  # Approved transaction
        )
        result = AmazonMatchResult(
            stage1_matches=[(txn, sample_order)],
            stage2_matches=[],
            duplicate_matches=[],
            combo_matches=[],
            unmatched_transactions=[],
            unmatched_orders=[],
        )
        display_amazon_match_results(result, stage1_window=7, stage2_window=24)
        captured = capsys.readouterr()
        # Should contain "A" marker (styled in cyan)
        assert "A" in captured.out

    def test_duplicate_matches(self, capsys, sample_transaction_info, sample_order):
        """Test displaying duplicate matches."""
        original_txn = TransactionInfo(
            transaction_id="txn-original",
            amount=47.82,
            date=datetime(2024, 6, 14),
            date_str="2024-06-14",
            display_amount="-$47.82",
            approved=False,
        )
        result = AmazonMatchResult(
            stage1_matches=[(original_txn, sample_order)],
            stage2_matches=[],
            duplicate_matches=[(sample_transaction_info, sample_order)],
            combo_matches=[],
            unmatched_transactions=[],
            unmatched_orders=[],
        )
        display_amazon_match_results(result, stage1_window=7, stage2_window=24)
        captured = capsys.readouterr()
        assert "Duplicate" in captured.out
        assert "Also matches" in captured.out

    def test_combo_matches(self, capsys, sample_order):
        """Test displaying combination matches (split shipments)."""
        txn1 = TransactionInfo(
            transaction_id="txn-001",
            amount=25.00,
            date=datetime(2024, 6, 15),
            date_str="2024-06-15",
            display_amount="-$25.00",
            approved=False,
        )
        txn2 = TransactionInfo(
            transaction_id="txn-002",
            amount=22.82,
            date=datetime(2024, 6, 16),
            date_str="2024-06-16",
            display_amount="-$22.82",
            approved=False,
        )
        result = AmazonMatchResult(
            stage1_matches=[],
            stage2_matches=[],
            duplicate_matches=[],
            combo_matches=[(sample_order, (txn1, txn2))],
            unmatched_transactions=[],
            unmatched_orders=[],
        )
        display_amazon_match_results(result, stage1_window=7, stage2_window=24)
        captured = capsys.readouterr()
        assert "Combination" in captured.out or "COMBO" in captured.out
        assert "2 transactions" in captured.out

    def test_unmatched_items(self, capsys, sample_transaction_info, sample_order):
        """Test displaying unmatched transactions and orders."""
        result = AmazonMatchResult(
            stage1_matches=[],
            stage2_matches=[],
            duplicate_matches=[],
            combo_matches=[],
            unmatched_transactions=[sample_transaction_info],
            unmatched_orders=[sample_order],
        )
        display_amazon_match_results(result, stage1_window=7, stage2_window=24)
        captured = capsys.readouterr()
        assert "Unmatched" in captured.out
        assert "Transactions without matching orders" in captured.out
        assert "Orders without matching transactions" in captured.out

    def test_long_items_truncation(self, capsys, sample_transaction_info):
        """Test that long item lists are truncated."""
        order = AmazonOrderCache(
            order_id="order-123",
            order_date=datetime(2024, 6, 14),
            total=47.82,
            items=[
                "Very Long Item Name Number One",
                "Another Extremely Long Item Name",
                "Third Item",
            ],
            fetched_at=datetime(2024, 6, 15),
        )
        result = AmazonMatchResult(
            stage1_matches=[(sample_transaction_info, order)],
            stage2_matches=[],
            duplicate_matches=[],
            combo_matches=[],
            unmatched_transactions=[],
            unmatched_orders=[],
        )
        display_amazon_match_results(result, stage1_window=7, stage2_window=24)
        captured = capsys.readouterr()
        # Should contain truncation indicator
        assert "..." in captured.out

    def test_verbose_mode_with_mapping_service(self, capsys, sample_transaction_info, sample_order):
        """Test verbose mode displays item predictions."""
        # Create mock mapping service
        mapping_service = MagicMock()
        mapping_service.predict_order_categories.return_value = OrderCategoryPrediction(
            order_id="order-123",
            item_predictions=[
                ItemCategoryPrediction(
                    item_name="USB Cable",
                    category_id="cat-001",
                    category_name="Electronics",
                    confidence=0.90,
                    occurrence_count=5,
                ),
            ],
        )

        result = AmazonMatchResult(
            stage1_matches=[(sample_transaction_info, sample_order)],
            stage2_matches=[],
            duplicate_matches=[],
            combo_matches=[],
            unmatched_transactions=[],
            unmatched_orders=[],
        )
        display_amazon_match_results(
            result, stage1_window=7, stage2_window=24, verbose=True, mapping_service=mapping_service
        )
        captured = capsys.readouterr()
        assert "Electronics" in captured.out

    def test_summary_includes_all_sections(self, capsys, sample_transaction_info, sample_order):
        """Test that summary includes counts from all sections."""
        result = AmazonMatchResult(
            stage1_matches=[(sample_transaction_info, sample_order)],
            stage2_matches=[],
            duplicate_matches=[],
            combo_matches=[],
            unmatched_transactions=[sample_transaction_info],
            unmatched_orders=[sample_order],
        )
        display_amazon_match_results(result, stage1_window=7, stage2_window=24)
        captured = capsys.readouterr()
        assert "Summary:" in captured.out
        assert "matched" in captured.out.lower()
        assert "unmatched" in captured.out.lower()
