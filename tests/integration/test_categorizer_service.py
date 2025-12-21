"""Integration tests for CategorizerService.

Tests the categorizer service with mock dependencies.
"""

from datetime import datetime
from pathlib import Path

import pytest

from src.config import CategorizationConfig, Config, DisplayConfig, PayeesConfig
from src.db.database import Database
from src.models import CategoryGroup, CategoryList, Transaction
from src.services.categorizer import CategorizerService


class MockYNABClient:
    """Mock YNAB client for testing."""

    def __init__(self):
        self.budget_id = "budget-123"
        self.budgets = [
            {"id": "budget-123", "name": "Test Budget", "last_modified_on": "2025-01-01"},
            {"id": "budget-456", "name": "Other Budget", "last_modified_on": "2025-01-02"},
        ]
        self.set_budget_id_calls = []

    def get_budgets(self) -> list[dict]:
        return self.budgets

    def get_current_budget_id(self) -> str:
        return self.budget_id

    def set_budget_id(self, budget_id: str) -> None:
        self.set_budget_id_calls.append(budget_id)
        self.budget_id = budget_id

    def get_budget_name(self, budget_id: str | None = None) -> str:
        bid = budget_id or self.budget_id
        for b in self.budgets:
            if b["id"] == bid:
                return b["name"]
        return "Unknown"


def make_config() -> Config:
    """Create a test config."""
    return Config(
        categorization=CategorizationConfig(),
        display=DisplayConfig(search_match_style="fuzzy"),
        payees=PayeesConfig(),
    )


def make_transaction(
    id: str = "txn-001",
    date: datetime | None = None,
    amount: float = -44.99,
    payee_name: str = "Amazon.com",
    category_id: str | None = None,
    category_name: str | None = None,
    approved: bool = False,
    memo: str | None = None,
    sync_status: str = "synced",
    is_split: bool = False,
    transfer_account_id: str | None = None,
) -> Transaction:
    """Create a test transaction."""
    return Transaction(
        id=id,
        date=date or datetime(2025, 11, 24),
        amount=amount,
        payee_name=payee_name,
        account_name="Checking",
        category_id=category_id,
        category_name=category_name,
        approved=approved,
        memo=memo,
        sync_status=sync_status,
        is_split=is_split,
        transfer_account_id=transfer_account_id,
    )


@pytest.fixture
def temp_db(tmp_path: Path) -> Database:
    """Create temporary database."""
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))
    yield db
    db.close()


@pytest.fixture
def mock_ynab() -> MockYNABClient:
    """Create mock YNAB client."""
    return MockYNABClient()


@pytest.fixture
def categorizer(temp_db: Database, mock_ynab: MockYNABClient) -> CategorizerService:
    """Create categorizer service."""
    config = make_config()
    return CategorizerService(config, mock_ynab, temp_db)


class TestFormatPayeeHistorySummary:
    """Tests for _format_payee_history_summary static method."""

    def test_formats_single_category(self) -> None:
        """Single category formatted correctly."""
        history = {"Groceries": {"count": 10, "percentage": 1.0}}
        result = CategorizerService._format_payee_history_summary(history)
        assert result == "100% Groceries"

    def test_formats_multiple_categories(self) -> None:
        """Multiple categories formatted with top 2."""
        history = {
            "Groceries": {"count": 8, "percentage": 0.8},
            "Electronics": {"count": 1, "percentage": 0.1},
            "Other": {"count": 1, "percentage": 0.1},
        }
        result = CategorizerService._format_payee_history_summary(history)
        assert "80% Groceries" in result
        assert "10% Electronics" in result

    def test_formats_empty_history(self) -> None:
        """Empty history returns empty string."""
        result = CategorizerService._format_payee_history_summary({})
        assert result == ""


class TestDbRowToTransaction:
    """Tests for _db_row_to_transaction method."""

    def test_converts_full_row(self, categorizer: CategorizerService) -> None:
        """Converts complete row to transaction."""
        row = {
            "id": "txn-123",
            "date": "2025-11-24",
            "amount": -44.99,
            "payee_name": "Amazon.com",
            "payee_id": "payee-1",
            "memo": "Test memo",
            "account_name": "Checking",
            "account_id": "acct-1",
            "category_id": "cat-1",
            "category_name": "Shopping",
            "approved": True,
            "cleared": "cleared",
            "is_split": False,
            "sync_status": "synced",
        }
        txn = categorizer._db_row_to_transaction(row)

        assert txn.id == "txn-123"
        assert txn.amount == -44.99
        assert txn.payee_name == "Amazon.com"
        assert txn.category_id == "cat-1"
        assert txn.approved is True

    def test_handles_null_payee(self, categorizer: CategorizerService) -> None:
        """Null payee_name converted to empty string."""
        row = {
            "id": "txn-1",
            "date": "2025-11-24",
            "amount": -10.0,
            "payee_name": None,
        }
        txn = categorizer._db_row_to_transaction(row)
        assert txn.payee_name == ""

    def test_handles_datetime_date(self, categorizer: CategorizerService) -> None:
        """Datetime object date handled correctly."""
        row = {
            "id": "txn-1",
            "date": datetime(2025, 11, 24),
            "amount": -10.0,
            "payee_name": "Test",
        }
        txn = categorizer._db_row_to_transaction(row)
        assert txn.date == datetime(2025, 11, 24)


class TestDbCategoriesToList:
    """Tests for _db_categories_to_list method."""

    def test_converts_empty_groups(self, categorizer: CategorizerService) -> None:
        """Empty groups return empty CategoryList."""
        result = categorizer._db_categories_to_list([])
        assert isinstance(result, CategoryList)
        assert len(result.groups) == 0

    def test_converts_groups_with_categories(self, categorizer: CategorizerService) -> None:
        """Groups with categories converted correctly."""
        groups = [
            {
                "id": "grp-1",
                "name": "Essentials",
                "categories": [
                    {
                        "id": "cat-1",
                        "name": "Groceries",
                        "group_id": "grp-1",
                        "group_name": "Essentials",
                    },
                    {
                        "id": "cat-2",
                        "name": "Rent",
                        "group_id": "grp-1",
                        "group_name": "Essentials",
                    },
                ],
            }
        ]
        result = categorizer._db_categories_to_list(groups)

        assert len(result.groups) == 1
        assert result.groups[0].name == "Essentials"
        assert len(result.groups[0].categories) == 2


class TestCategories:
    """Tests for categories property."""

    def test_loads_from_database(self, temp_db: Database, mock_ynab: MockYNABClient) -> None:
        """Categories loaded from database."""
        # Add categories to database using CategoryList
        from src.models.category import Category, CategoryGroup, CategoryList

        cat_list = CategoryList(
            groups=[
                CategoryGroup(
                    id="grp-1",
                    name="Essentials",
                    categories=[
                        Category(
                            id="cat-1",
                            name="Groceries",
                            group_id="grp-1",
                            group_name="Essentials",
                        )
                    ],
                )
            ]
        )
        temp_db.upsert_categories(cat_list)

        config = make_config()
        categorizer = CategorizerService(config, mock_ynab, temp_db)

        result = categorizer.categories
        assert isinstance(result, CategoryList)

    def test_caches_categories(self, categorizer: CategorizerService) -> None:
        """Categories are cached after first load."""
        _ = categorizer.categories
        _ = categorizer.categories  # Second call should use cache

        # No assertion needed - just verifying no error


class TestRefreshCategories:
    """Tests for refresh_categories method."""

    def test_refreshes_from_database(self, temp_db: Database, mock_ynab: MockYNABClient) -> None:
        """Refreshes categories from database."""
        from src.models.category import Category, CategoryGroup, CategoryList

        config = make_config()
        categorizer = CategorizerService(config, mock_ynab, temp_db)

        # Initial load
        _ = categorizer.categories

        # Add more categories
        cat_list = CategoryList(
            groups=[
                CategoryGroup(
                    id="grp-1",
                    name="Group",
                    categories=[
                        Category(
                            id="cat-new",
                            name="New Category",
                            group_id="grp-1",
                            group_name="Group",
                        )
                    ],
                )
            ]
        )
        temp_db.upsert_categories(cat_list)

        # Refresh
        result = categorizer.refresh_categories()
        assert isinstance(result, CategoryList)


class TestGetters:
    """Tests for getter methods."""

    def test_get_config(self, categorizer: CategorizerService) -> None:
        """get_config returns config."""
        config = categorizer.get_config()
        assert isinstance(config, Config)

    def test_get_search_match_style(self, categorizer: CategorizerService) -> None:
        """get_search_match_style returns style."""
        style = categorizer.get_search_match_style()
        assert style == "fuzzy"

    def test_get_category_groups(self, temp_db: Database, mock_ynab: MockYNABClient) -> None:
        """get_category_groups returns groups."""
        from src.models.category import Category, CategoryList
        from src.models.category import CategoryGroup as CategoryGrp

        cat_list = CategoryList(
            groups=[
                CategoryGrp(
                    id="grp-1",
                    name="Group",
                    categories=[
                        Category(
                            id="cat-1",
                            name="Test",
                            group_id="grp-1",
                            group_name="Group",
                        )
                    ],
                )
            ]
        )
        temp_db.upsert_categories(cat_list)
        config = make_config()
        categorizer = CategorizerService(config, mock_ynab, temp_db)

        groups = categorizer.get_category_groups()
        assert isinstance(groups, list)
        assert all(isinstance(g, CategoryGroup) for g in groups)


class TestApplyCategory:
    """Tests for apply_category method."""

    def test_creates_pending_change(self, temp_db: Database, mock_ynab: MockYNABClient) -> None:
        """Applying category creates pending change."""
        # Add transaction to database
        txn = make_transaction()
        temp_db.upsert_ynab_transaction(txn)

        config = make_config()
        categorizer = CategorizerService(config, mock_ynab, temp_db)

        result = categorizer.apply_category(txn, "cat-1", "Groceries")

        assert result.category_id == "cat-1"
        assert result.category_name == "Groceries"
        assert result.sync_status == "pending_push"
        assert result.approved is True

        # Verify pending change in database
        pending = temp_db.get_pending_change("txn-001")
        assert pending is not None

    def test_records_categorization_history(
        self, temp_db: Database, mock_ynab: MockYNABClient
    ) -> None:
        """Applying category records history."""
        txn = make_transaction()
        temp_db.upsert_ynab_transaction(txn)

        config = make_config()
        categorizer = CategorizerService(config, mock_ynab, temp_db)

        categorizer.apply_category(txn, "cat-1", "Groceries")

        # Verify history was recorded
        history = temp_db.get_payee_history("Amazon.com")
        assert len(history) >= 1


class TestApplySplitCategories:
    """Tests for apply_split_categories method."""

    def test_creates_split_pending_change(
        self, temp_db: Database, mock_ynab: MockYNABClient
    ) -> None:
        """Applying split creates pending change."""
        txn = make_transaction(amount=-100.0)
        temp_db.upsert_ynab_transaction(txn)

        config = make_config()
        categorizer = CategorizerService(config, mock_ynab, temp_db)

        splits = [
            {"category_id": "cat-1", "category_name": "Groceries", "amount": -60.0},
            {"category_id": "cat-2", "category_name": "Household", "amount": -40.0},
        ]

        result = categorizer.apply_split_categories(txn, splits)

        assert result.is_split is True
        assert result.sync_status == "pending_push"
        assert "[Split 2]" in result.category_name

        # Verify splits are stored
        pending_splits = temp_db.get_pending_splits("txn-001")
        assert len(pending_splits) == 2


class TestUndoCategory:
    """Tests for undo_category method."""

    def test_undoes_pending_change(self, temp_db: Database, mock_ynab: MockYNABClient) -> None:
        """Undo removes pending change and restores original."""
        # Add transaction
        txn = make_transaction(category_id=None, category_name=None)
        temp_db.upsert_ynab_transaction(txn)

        config = make_config()
        categorizer = CategorizerService(config, mock_ynab, temp_db)

        # Apply category
        categorizer.apply_category(txn, "cat-1", "Groceries")

        # Undo
        result = categorizer.undo_category(txn)

        assert result.category_id is None
        assert result.sync_status == "synced"

        # Verify pending change removed
        pending = temp_db.get_pending_change("txn-001")
        assert pending is None

    def test_undo_raises_for_no_pending(self, categorizer: CategorizerService) -> None:
        """Undo raises error when no pending change."""
        txn = make_transaction()

        with pytest.raises(ValueError, match="No pending change"):
            categorizer.undo_category(txn)


class TestApproveTransaction:
    """Tests for approve_transaction method."""

    def test_approves_unapproved_transaction(
        self, temp_db: Database, mock_ynab: MockYNABClient
    ) -> None:
        """Approving unapproved transaction creates pending change."""
        txn = make_transaction(approved=False)
        temp_db.upsert_ynab_transaction(txn)

        config = make_config()
        categorizer = CategorizerService(config, mock_ynab, temp_db)

        result = categorizer.approve_transaction(txn)

        assert result.approved is True
        assert result.sync_status == "pending_push"

    def test_noop_for_already_approved(self, temp_db: Database, mock_ynab: MockYNABClient) -> None:
        """Approving already approved transaction is no-op."""
        txn = make_transaction(approved=True)
        temp_db.upsert_ynab_transaction(txn)

        config = make_config()
        categorizer = CategorizerService(config, mock_ynab, temp_db)

        result = categorizer.approve_transaction(txn)

        assert result.approved is True
        assert result.sync_status == "synced"  # Unchanged


class TestApplyMemo:
    """Tests for apply_memo method."""

    def test_applies_memo(self, temp_db: Database, mock_ynab: MockYNABClient) -> None:
        """Applying memo creates pending change."""
        txn = make_transaction(memo=None)
        temp_db.upsert_ynab_transaction(txn)

        config = make_config()
        categorizer = CategorizerService(config, mock_ynab, temp_db)

        result = categorizer.apply_memo(txn, "New memo")

        assert result.memo == "New memo"
        assert result.sync_status == "pending_push"

    def test_clears_memo(self, temp_db: Database, mock_ynab: MockYNABClient) -> None:
        """Empty memo string clears memo."""
        txn = make_transaction(memo="Old memo")
        temp_db.upsert_ynab_transaction(txn)

        config = make_config()
        categorizer = CategorizerService(config, mock_ynab, temp_db)

        result = categorizer.apply_memo(txn, "")

        assert result.memo == ""


class TestSyncStatus:
    """Tests for get_sync_status method."""

    def test_returns_sync_states(self, categorizer: CategorizerService) -> None:
        """get_sync_status returns ynab and amazon states."""
        result = categorizer.get_sync_status()

        assert "ynab" in result
        assert "amazon" in result


class TestGetPendingChanges:
    """Tests for get_pending_changes method."""

    def test_returns_all_pending(self, temp_db: Database, mock_ynab: MockYNABClient) -> None:
        """Returns all pending changes."""
        # Add transactions and pending changes
        for i in range(3):
            txn = make_transaction(id=f"txn-{i}")
            temp_db.upsert_ynab_transaction(txn)
            temp_db.create_pending_change(
                f"txn-{i}",
                {"category_id": "cat-1"},
                {"category_id": None},
                "update",
            )

        config = make_config()
        categorizer = CategorizerService(config, mock_ynab, temp_db)

        result = categorizer.get_pending_changes()

        assert len(result) == 3


class TestBudgetMethods:
    """Tests for budget management methods."""

    def test_get_budgets(self, categorizer: CategorizerService) -> None:
        """get_budgets returns budgets from client."""
        result = categorizer.get_budgets()
        assert len(result) == 2
        assert result[0]["name"] == "Test Budget"

    def test_get_current_budget_id(self, categorizer: CategorizerService) -> None:
        """get_current_budget_id returns current ID."""
        result = categorizer.get_current_budget_id()
        assert result == "budget-123"

    def test_set_budget_id(self, temp_db: Database, mock_ynab: MockYNABClient) -> None:
        """set_budget_id updates client and clears cache."""
        config = make_config()
        categorizer = CategorizerService(config, mock_ynab, temp_db)

        # Load categories to cache
        _ = categorizer.categories

        # Change budget
        categorizer.set_budget_id("budget-456")

        assert mock_ynab.budget_id == "budget-456"
        # Cache should be cleared (will reload on next access)

    def test_get_budget_name(self, categorizer: CategorizerService) -> None:
        """get_budget_name returns name for ID."""
        result = categorizer.get_budget_name("budget-123")
        assert result == "Test Budget"


class TestGetOriginalValues:
    """Tests for _get_original_values method."""

    def test_returns_current_values_when_no_pending(self, categorizer: CategorizerService) -> None:
        """Returns transaction values when no pending change."""
        txn = make_transaction(
            category_id="cat-1",
            category_name="Groceries",
            approved=True,
            memo="Test",
        )

        result = categorizer._get_original_values(txn)

        assert result["category_id"] == "cat-1"
        assert result["category_name"] == "Groceries"
        assert result["approved"] is True
        assert result["memo"] == "Test"

    def test_preserves_original_from_pending(
        self, temp_db: Database, mock_ynab: MockYNABClient
    ) -> None:
        """Preserves first original values when pending exists."""
        txn = make_transaction(id="txn-1")
        temp_db.upsert_ynab_transaction(txn)

        # Create first pending change with original values
        temp_db.create_pending_change(
            "txn-1",
            {"category_id": "cat-1"},
            {"category_id": None, "category_name": None},
            "update",
        )

        config = make_config()
        categorizer = CategorizerService(config, mock_ynab, temp_db)

        # Modify transaction object (as if UI updated it)
        txn.category_id = "cat-1"
        txn.category_name = "Groceries"

        # Get original values - should use pending's originals
        result = categorizer._get_original_values(txn, ["category_id", "category_name"])

        assert result["category_id"] is None
        assert result["category_name"] is None


class TestGetTransactions:
    """Tests for get_transactions method."""

    def test_returns_all_transactions(self, temp_db: Database, mock_ynab: MockYNABClient) -> None:
        """Returns all transactions by default."""
        for i in range(3):
            temp_db.upsert_ynab_transaction(make_transaction(id=f"txn-{i}", payee_name="Store"))

        config = make_config()
        categorizer = CategorizerService(config, mock_ynab, temp_db)

        result = categorizer.get_transactions()

        assert len(result.transactions) == 3

    def test_filters_by_mode(self, temp_db: Database, mock_ynab: MockYNABClient) -> None:
        """Filters transactions by mode."""
        temp_db.upsert_ynab_transaction(
            make_transaction(id="txn-1", approved=True, category_id="cat-1")
        )
        temp_db.upsert_ynab_transaction(
            make_transaction(id="txn-2", approved=False, category_id=None)
        )

        config = make_config()
        categorizer = CategorizerService(config, mock_ynab, temp_db)

        approved = categorizer.get_transactions(filter_mode="approved")
        assert len(approved.transactions) == 1
        assert approved.transactions[0].id == "txn-1"

        new = categorizer.get_transactions(filter_mode="new")
        assert len(new.transactions) == 1
        assert new.transactions[0].id == "txn-2"


class TestGetPendingTransactions:
    """Tests for get_pending_transactions method."""

    def test_returns_uncategorized_enriched(
        self, temp_db: Database, mock_ynab: MockYNABClient
    ) -> None:
        """Returns enriched uncategorized transactions."""
        temp_db.upsert_ynab_transaction(
            make_transaction(id="txn-1", category_id=None, category_name=None, payee_name="Store")
        )
        temp_db.upsert_ynab_transaction(
            make_transaction(
                id="txn-2",
                category_id="cat-1",
                category_name="Groceries",
                payee_name="Store",
            )
        )

        config = make_config()
        categorizer = CategorizerService(config, mock_ynab, temp_db)

        result = categorizer.get_pending_transactions()

        # Only uncategorized should be returned
        assert len(result.transactions) == 1
        assert result.transactions[0].id == "txn-1"

    def test_adds_payee_history_summary(self, temp_db: Database, mock_ynab: MockYNABClient) -> None:
        """Adds history summary for payees with history."""
        temp_db.upsert_ynab_transaction(
            make_transaction(id="txn-1", category_id=None, payee_name="TestPayee")
        )

        # Add categorization history
        temp_db.add_categorization("TestPayee", "Groceries", "cat-1", 50.0)
        temp_db.add_categorization("TestPayee", "Groceries", "cat-1", 60.0)

        config = make_config()
        categorizer = CategorizerService(config, mock_ynab, temp_db)

        result = categorizer.get_pending_transactions()

        assert len(result.transactions) == 1
        txn = result.transactions[0]
        assert txn.payee_history_summary is not None
        assert "100% Groceries" in txn.payee_history_summary
