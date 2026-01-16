"""Tests for push preview screen."""

from ynab_tui.tui.screens.push_preview import PushChangeItem


def test_push_change_item_format_transfer_incoming():
    """Test that incoming transfers show destination account (FROM is in payee)."""
    change = {
        "date": "2026-01-14",
        "payee_name": "Transfer : Savings",  # FROM is here
        "amount": 10000.0,  # Positive = incoming to this account
        "change_type": "approve",
        "new_values": {},
        "original_values": {},
        "category_name": None,
        "account_name": "Checking",  # TO - this account is the destination
        "transfer_account_id": "abc123",
        "transfer_account_name": "Savings",
        "new_approved": True,
        "original_approved": False,
    }
    item = PushChangeItem(change)
    row = item._format_row()

    # Category should show "-> Checking" (destination)
    assert "Uncategorized" not in row
    amount_pos = row.find("$10000.00")
    category_area = row[amount_pos:]
    assert "-> Checking" in category_area


def test_push_change_item_format_transfer_outgoing():
    """Test that outgoing transfers show destination account (FROM is in payee)."""
    change = {
        "date": "2026-01-14",
        "payee_name": "Transfer : Checking",  # TO is here (confusingly named by YNAB)
        "amount": -10000.0,  # Negative = outgoing from this account
        "change_type": "approve",
        "new_values": {},
        "original_values": {},
        "category_name": None,
        "account_name": "Savings",  # FROM - this account is the source
        "transfer_account_id": "abc123",
        "transfer_account_name": "Checking",  # TO - destination
        "new_approved": True,
        "original_approved": False,
    }
    item = PushChangeItem(change)
    row = item._format_row()

    # Category should show "-> Checking" (destination)
    assert "Uncategorized" not in row
    amount_pos = row.find("$10000.00")
    category_area = row[amount_pos:]
    assert "-> Checking" in category_area


def test_push_change_item_format_non_transfer():
    """Test that non-transfers still show category name correctly."""
    change = {
        "date": "2026-01-14",
        "payee_name": "Netflix",
        "amount": 17.99,
        "change_type": "category",
        "new_values": {"category_id": "cat123", "category_name": "Software Subscriptions"},
        "original_values": {},
        "category_name": None,
        "transfer_account_id": None,
        "transfer_account_name": None,
        "new_approved": None,
        "original_approved": False,
    }
    item = PushChangeItem(change)
    row = item._format_row()

    # Should show category change (may be truncated, so check for "Software")
    assert "Software" in row
