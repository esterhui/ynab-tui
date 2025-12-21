"""Tests for MockYNABClient."""

import csv
from datetime import datetime

import pytest

from ynab_tui.clients.mock_ynab_client import MockYNABClient
from ynab_tui.clients.ynab_client import YNABClientError


@pytest.fixture
def mock_data_dir(tmp_path):
    """Create a temporary directory with mock CSV data."""
    # Create transactions.csv
    transactions_csv = tmp_path / "transactions.csv"
    transactions_data = [
        {
            "id": "txn-001",
            "date": "2024-01-15",
            "amount": "-50.00",
            "payee_name": "Test Store",
            "category_id": "cat-001",
            "category_name": "Shopping",
            "account_name": "Checking",
            "memo": "Test memo",
            "approved": "1",
            "cleared": "cleared",
            "transfer_account_id": "",
            "transfer_account_name": "",
            "debt_transaction_type": "",
            "is_split": "0",
            "parent_transaction_id": "",
        },
        {
            "id": "txn-002",
            "date": "2024-01-16",
            "amount": "-25.00",
            "payee_name": "Grocery Store",
            "category_id": "",
            "category_name": "",
            "account_name": "Checking",
            "memo": "",
            "approved": "0",
            "cleared": "uncleared",
            "transfer_account_id": "",
            "transfer_account_name": "",
            "debt_transaction_type": "",
            "is_split": "0",
            "parent_transaction_id": "",
        },
        {
            "id": "txn-003",
            "date": "2024-01-17",
            "amount": "-100.00",
            "payee_name": "Transfer",
            "category_id": "",
            "category_name": "",
            "account_name": "Checking",
            "memo": "",
            "approved": "1",
            "cleared": "cleared",
            "transfer_account_id": "acct-savings",
            "transfer_account_name": "Savings",
            "debt_transaction_type": "",
            "is_split": "0",
            "parent_transaction_id": "",
        },
        {
            "id": "txn-004",
            "date": "2024-01-18",
            "amount": "-75.00",
            "payee_name": "Restaurant",
            "category_id": "",
            "category_name": "Uncategorized",
            "account_name": "Credit Card",
            "memo": "",
            "approved": "1",
            "cleared": "cleared",
            "transfer_account_id": "",
            "transfer_account_name": "",
            "debt_transaction_type": "",
            "is_split": "0",
            "parent_transaction_id": "",
        },
        {
            "id": "sub-001",
            "date": "2024-01-19",
            "amount": "-10.00",
            "payee_name": "Split Parent",
            "category_id": "cat-001",
            "category_name": "Shopping",
            "account_name": "Checking",
            "memo": "",
            "approved": "1",
            "cleared": "cleared",
            "transfer_account_id": "",
            "transfer_account_name": "",
            "debt_transaction_type": "",
            "is_split": "0",
            "parent_transaction_id": "txn-parent",
        },
    ]

    with open(transactions_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=transactions_data[0].keys())
        writer.writeheader()
        writer.writerows(transactions_data)

    # Create categories.csv
    categories_csv = tmp_path / "categories.csv"
    categories_data = [
        {
            "category_id": "cat-001",
            "category_name": "Shopping",
            "group_id": "group-001",
            "group_name": "Everyday Expenses",
            "hidden": "false",
            "deleted": "false",
        },
        {
            "category_id": "cat-002",
            "category_name": "Groceries",
            "group_id": "group-001",
            "group_name": "Everyday Expenses",
            "hidden": "false",
            "deleted": "false",
        },
        {
            "category_id": "cat-003",
            "category_name": "Rent",
            "group_id": "group-002",
            "group_name": "Bills",
            "hidden": "false",
            "deleted": "false",
        },
    ]

    with open(categories_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=categories_data[0].keys())
        writer.writeheader()
        writer.writerows(categories_data)

    return tmp_path


@pytest.fixture
def mock_client(mock_data_dir):
    """Create a MockYNABClient with test data."""
    return MockYNABClient(data_dir=str(mock_data_dir))


class TestMockYNABClientInit:
    """Tests for MockYNABClient initialization."""

    def test_init_with_custom_data_dir(self, mock_data_dir):
        """Test initialization with custom data directory."""
        client = MockYNABClient(data_dir=str(mock_data_dir))
        assert len(client._transactions) > 0

    def test_init_with_max_transactions(self, mock_data_dir):
        """Test initialization with max_transactions limit."""
        client = MockYNABClient(data_dir=str(mock_data_dir), max_transactions=2)
        assert len(client._transactions) == 2

    def test_init_missing_transactions_csv(self, tmp_path):
        """Test initialization when transactions.csv doesn't exist."""
        client = MockYNABClient(data_dir=str(tmp_path))
        assert len(client._transactions) == 0

    def test_init_missing_categories_csv(self, tmp_path):
        """Test initialization when categories.csv doesn't exist."""
        # Create transactions.csv only
        transactions_csv = tmp_path / "transactions.csv"
        with open(transactions_csv, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "id",
                    "date",
                    "amount",
                    "payee_name",
                    "category_id",
                    "category_name",
                    "account_name",
                    "memo",
                    "approved",
                    "cleared",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "id": "txn-001",
                    "date": "2024-01-15",
                    "amount": "-50.00",
                    "payee_name": "Test",
                    "category_id": "",
                    "category_name": "",
                    "account_name": "Checking",
                    "memo": "",
                    "approved": "1",
                    "cleared": "cleared",
                }
            )

        client = MockYNABClient(data_dir=str(tmp_path))
        assert len(client._categories.groups) == 0

    def test_skips_subtransactions(self, mock_data_dir):
        """Test that subtransactions are skipped during loading."""
        client = MockYNABClient(data_dir=str(mock_data_dir))
        # Should have 4 parent transactions, not the subtransaction (sub-001)
        assert len(client._transactions) == 4
        assert not any(t.id == "sub-001" for t in client._transactions)


class TestMockYNABClientTransactions:
    """Tests for transaction retrieval methods."""

    def test_get_uncategorized_transactions(self, mock_client):
        """Test getting uncategorized transactions."""
        uncategorized = mock_client.get_uncategorized_transactions()
        # txn-002 (no category) and txn-004 (Uncategorized) should be included
        # txn-003 is a transfer (has transfer_account_id) so excluded
        assert len(uncategorized) >= 2
        ids = [t.id for t in uncategorized]
        assert "txn-002" in ids
        assert "txn-004" in ids
        assert "txn-003" not in ids  # Transfer excluded

    def test_get_uncategorized_with_since_date(self, mock_client):
        """Test getting uncategorized transactions with date filter."""
        since = datetime(2024, 1, 17)
        uncategorized = mock_client.get_uncategorized_transactions(since_date=since)
        # Only txn-004 (Jan 18) should be included
        assert len(uncategorized) == 1
        assert uncategorized[0].id == "txn-004"

    def test_get_unapproved_transactions(self, mock_client):
        """Test getting unapproved transactions."""
        unapproved = mock_client.get_unapproved_transactions()
        assert len(unapproved) == 1
        assert unapproved[0].id == "txn-002"

    def test_get_unapproved_with_since_date(self, mock_client):
        """Test getting unapproved transactions with date filter."""
        since = datetime(2024, 1, 20)  # After all test transactions
        unapproved = mock_client.get_unapproved_transactions(since_date=since)
        assert len(unapproved) == 0

    def test_get_all_pending_transactions(self, mock_client):
        """Test getting all pending transactions (uncategorized + unapproved)."""
        pending = mock_client.get_all_pending_transactions()
        # Should include both uncategorized and unapproved, deduped
        ids = [t.id for t in pending]
        assert "txn-002" in ids  # Both uncategorized and unapproved
        assert "txn-004" in ids  # Uncategorized

    def test_get_recent_transactions(self, mock_client):
        """Test getting recent transactions."""
        recent = mock_client.get_recent_transactions(limit=2)
        assert len(recent) == 2
        # Should be sorted by date descending
        assert recent[0].date >= recent[1].date

    def test_get_recent_transactions_with_since_date(self, mock_client):
        """Test getting recent transactions with date filter."""
        since = datetime(2024, 1, 17)
        recent = mock_client.get_recent_transactions(since_date=since)
        assert all(t.date >= since for t in recent)

    def test_get_all_transactions(self, mock_client):
        """Test getting all transactions."""
        all_txns = mock_client.get_all_transactions()
        assert len(all_txns) == 4  # Excludes subtransaction

    def test_get_all_transactions_with_since_date(self, mock_client):
        """Test getting all transactions with date filter."""
        since = datetime(2024, 1, 17)
        txns = mock_client.get_all_transactions(since_date=since)
        assert all(t.date >= since for t in txns)


class TestMockYNABClientUpdates:
    """Tests for transaction update methods."""

    def test_update_transaction_category(self, mock_client):
        """Test updating a transaction's category."""
        result = mock_client.update_transaction_category("txn-002", "cat-002", approve=True)
        assert result.category_id == "cat-002"
        assert result.category_name == "Groceries"
        assert result.approved is True

    def test_update_transaction_category_not_found(self, mock_client):
        """Test updating a non-existent transaction returns minimal transaction."""
        result = mock_client.update_transaction_category("nonexistent", "cat-001")
        assert result.id == "nonexistent"
        assert result.payee_name == "Mock Update"

    def test_update_excludes_from_uncategorized(self, mock_client):
        """Test that updated transactions are excluded from uncategorized list."""
        mock_client.update_transaction_category("txn-002", "cat-001")
        uncategorized = mock_client.get_uncategorized_transactions()
        assert "txn-002" not in [t.id for t in uncategorized]

    def test_approve_transaction(self, mock_client):
        """Test approving a transaction."""
        result = mock_client.approve_transaction("txn-002")
        assert result.approved is True

    def test_approve_transaction_not_found(self, mock_client):
        """Test approving a non-existent transaction raises error."""
        with pytest.raises(YNABClientError, match="not found"):
            mock_client.approve_transaction("nonexistent")

    def test_approve_excludes_from_unapproved(self, mock_client):
        """Test that approved transactions are excluded from unapproved list."""
        mock_client.approve_transaction("txn-002")
        unapproved = mock_client.get_unapproved_transactions()
        assert "txn-002" not in [t.id for t in unapproved]

    def test_create_split_transaction(self, mock_client):
        """Test creating a split transaction."""
        splits = [
            {"amount": -30.0, "category_id": "cat-001", "memo": "Part 1"},
            {"amount": -20.0, "category_id": "cat-002", "memo": "Part 2"},
        ]
        result = mock_client.create_split_transaction("txn-001", splits)
        assert result.is_split is True
        assert result.category_name == "Split"
        assert len(result.subtransactions) == 2
        assert result.subtransactions[0].amount == -30.0
        assert result.subtransactions[1].category_id == "cat-002"

    def test_create_split_transaction_not_found(self, mock_client):
        """Test creating split for non-existent transaction raises error."""
        with pytest.raises(YNABClientError, match="not found"):
            mock_client.create_split_transaction("nonexistent", [{"amount": -10.0}])


class TestMockYNABClientBudgets:
    """Tests for budget-related methods."""

    def test_get_budgets(self, mock_client):
        """Test getting budget list."""
        budgets = mock_client.get_budgets()
        assert len(budgets) == 2
        assert budgets[0]["name"] == "Mock Budget"

    def test_set_budget_id_by_id(self, mock_client):
        """Test setting budget by ID."""
        mock_client.set_budget_id("mock-budget-id-2")
        assert mock_client.get_current_budget_id() == "mock-budget-id-2"

    def test_set_budget_id_by_name(self, mock_client):
        """Test setting budget by name."""
        mock_client.set_budget_id("Second Mock Budget")
        assert mock_client.get_current_budget_id() == "mock-budget-id-2"

    def test_set_budget_id_not_found(self, mock_client):
        """Test setting unknown budget defaults to mock budget."""
        mock_client.set_budget_id("Unknown Budget Name")
        assert mock_client.get_current_budget_id() == "mock-budget-id"

    def test_get_current_budget_id_default(self, mock_client):
        """Test default budget ID."""
        assert mock_client.get_current_budget_id() == "mock-budget-id"

    def test_get_budget_name(self, mock_client):
        """Test getting budget name by ID."""
        name = mock_client.get_budget_name("mock-budget-id-2")
        assert name == "Second Mock Budget"

    def test_get_budget_name_default(self, mock_client):
        """Test getting budget name for current budget."""
        name = mock_client.get_budget_name()
        assert name == "Mock Budget"

    def test_get_budget_name_unknown(self, mock_client):
        """Test getting name for unknown budget."""
        name = mock_client.get_budget_name("unknown-id")
        assert name == "Unknown Budget"


class TestMockYNABClientMisc:
    """Tests for miscellaneous methods."""

    def test_test_connection(self, mock_client):
        """Test the test_connection method."""
        result = mock_client.test_connection()
        assert result["success"] is True
        assert result["user_id"] == "mock-user-id"

    def test_get_categories(self, mock_client):
        """Test getting categories."""
        categories = mock_client.get_categories()
        assert len(categories.groups) == 2
        all_cats = [cat for group in categories.groups for cat in group.categories]
        assert len(all_cats) == 3

    def test_get_category_name(self, mock_client):
        """Test looking up category name by ID."""
        name = mock_client._get_category_name("cat-001")
        assert name == "Shopping"

    def test_get_category_name_not_found(self, mock_client):
        """Test looking up non-existent category."""
        name = mock_client._get_category_name("nonexistent")
        assert name is None


class TestMockYNABClientSaveTransactions:
    """Tests for save_transactions persistence."""

    def test_save_no_updates(self, mock_client):
        """Test save with no updates returns 0."""
        count = mock_client.save_transactions()
        assert count == 0

    def test_save_category_update(self, mock_client, mock_data_dir):
        """Test saving category updates."""
        mock_client.update_transaction_category("txn-002", "cat-001")
        count = mock_client.save_transactions()
        assert count == 1

        # Verify the CSV was updated
        with open(mock_data_dir / "transactions.csv") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["id"] == "txn-002":
                    assert row["category_id"] == "cat-001"
                    break

    def test_save_approval_update(self, mock_client, mock_data_dir):
        """Test saving approval updates."""
        mock_client.approve_transaction("txn-002")
        count = mock_client.save_transactions()
        assert count == 1

        # Verify the CSV was updated
        with open(mock_data_dir / "transactions.csv") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["id"] == "txn-002":
                    assert row["approved"] == "1"
                    break

    def test_save_split_transaction(self, mock_client, mock_data_dir):
        """Test saving split transaction creates subtransactions."""
        splits = [
            {"amount": -30.0, "category_id": "cat-001"},
            {"amount": -20.0, "category_id": "cat-002"},
        ]
        mock_client.create_split_transaction("txn-001", splits)
        count = mock_client.save_transactions()
        assert count == 1

        # Verify subtransactions were created in CSV
        with open(mock_data_dir / "transactions.csv") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        parent = next(r for r in rows if r["id"] == "txn-001")
        assert parent["is_split"] == "1"

        subtxns = [r for r in rows if r.get("parent_transaction_id") == "txn-001"]
        assert len(subtxns) == 2

    def test_save_clears_updates(self, mock_client):
        """Test that save clears the in-memory updates."""
        mock_client.update_transaction_category("txn-002", "cat-001")
        assert len(mock_client._updated_transactions) == 1

        mock_client.save_transactions()
        assert len(mock_client._updated_transactions) == 0

    def test_save_no_csv(self, tmp_path):
        """Test save with no CSV file returns 0."""
        client = MockYNABClient(data_dir=str(tmp_path))
        client._updated_transactions["fake"] = {"category_id": "cat-001"}
        count = client.save_transactions()
        assert count == 0
