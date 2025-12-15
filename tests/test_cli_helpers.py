"""Tests for CLI helper functions in src/cli/helpers.py."""

from datetime import datetime

from src.cli.helpers import (
    display_pending_changes,
    format_date_for_display,
    require_data,
)


class TestFormatDateForDisplay:
    """Tests for format_date_for_display function."""

    def test_with_none(self):
        """Test formatting None returns empty string."""
        result = format_date_for_display(None)
        assert result == ""

    def test_with_string(self):
        """Test formatting a string date."""
        result = format_date_for_display("2024-06-15")
        assert result == "2024-06-15"

    def test_with_long_string(self):
        """Test formatting a string with extra characters (like timestamp)."""
        result = format_date_for_display("2024-06-15T14:30:00Z")
        assert result == "2024-06-15"

    def test_with_datetime(self):
        """Test formatting a datetime object."""
        result = format_date_for_display(datetime(2024, 6, 15, 14, 30, 0))
        assert result == "2024-06-15"


class TestRequireData:
    """Tests for require_data function."""

    def test_empty_transactions(self, database, capsys):
        """Test require_data returns False with empty transactions."""
        result = require_data(database, "transactions")
        assert result is False
        captured = capsys.readouterr()
        assert "No transactions" in captured.out
        assert "pull" in captured.out.lower()

    def test_empty_orders(self, database, capsys):
        """Test require_data returns False with empty orders."""
        result = require_data(database, "orders")
        assert result is False
        captured = capsys.readouterr()
        assert "No orders" in captured.out
        assert "pull" in captured.out.lower()

    def test_with_transactions(self, database, sample_sync_transaction, capsys):
        """Test require_data returns True when transactions exist."""
        # Add a transaction to the database
        database.upsert_ynab_transaction(sample_sync_transaction)
        result = require_data(database, "transactions")
        assert result is True
        captured = capsys.readouterr()
        # Should not print anything when data exists
        assert captured.out == ""

    def test_with_orders(self, database, add_order_to_db, capsys):
        """Test require_data returns True when orders exist."""
        # Add an order to the database
        add_order_to_db("order-123", datetime(2024, 6, 15), 47.82, ["USB Cable"])
        result = require_data(database, "orders")
        assert result is True
        captured = capsys.readouterr()
        # Should not print anything when data exists
        assert captured.out == ""

    def test_unknown_data_type(self, database, capsys):
        """Test require_data with unknown data type returns False."""
        result = require_data(database, "unknown_type")
        assert result is False


class TestDisplayPendingChanges:
    """Tests for display_pending_changes function."""

    def test_empty_pending_changes(self, capsys):
        """Test displaying empty pending changes."""
        display_pending_changes([])
        captured = capsys.readouterr()
        assert "Pending changes (0)" in captured.out
        assert "Date" in captured.out
        assert "Payee" in captured.out
        assert "Amount" in captured.out

    def test_with_pending_changes(self, capsys):
        """Test displaying pending changes."""
        changes = [
            {
                "date": "2024-06-15",
                "payee_name": "AMAZON.COM",
                "amount": -47.82,
                "original_category_name": None,
                "new_category_name": "Electronics",
            },
            {
                "date": "2024-06-14",
                "payee_name": "COSTCO",
                "amount": -127.43,
                "original_category_name": "Groceries",
                "new_category_name": "Home & Garden",
            },
        ]
        display_pending_changes(changes)
        captured = capsys.readouterr()
        assert "Pending changes (2)" in captured.out
        assert "2024-06-15" in captured.out
        assert "AMAZON.COM" in captured.out
        assert "-47.82" in captured.out
        assert "Uncategorized" in captured.out  # None becomes "Uncategorized"
        assert "Electronics" in captured.out
        assert "COSTCO" in captured.out
        assert "Groceries" in captured.out
        assert "Home & Garden" in captured.out

    def test_split_transaction_shows_split(self, capsys):
        """Test that split transaction shows 'Split' as new category."""
        changes = [
            {
                "date": "2024-06-15",
                "payee_name": "Test Payee",
                "amount": -100.00,
                "original_category_name": "Groceries",
                "new_category_name": None,  # Split transactions have None
            },
        ]
        display_pending_changes(changes)
        captured = capsys.readouterr()
        assert "Split" in captured.out

    def test_long_payee_truncation(self, capsys):
        """Test that long payee names are truncated in display."""
        changes = [
            {
                "date": "2024-06-15",
                "payee_name": "A" * 50,  # Very long payee name
                "amount": -50.00,
                "original_category_name": "Test",
                "new_category_name": "Other",
            },
        ]
        display_pending_changes(changes)
        captured = capsys.readouterr()
        # Payee should be truncated to 25 chars
        assert "A" * 25 in captured.out
        assert "A" * 50 not in captured.out
