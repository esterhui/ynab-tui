"""Integration tests for SyncService.

Tests the sync service with mock clients.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ynab_tui.config import AmazonConfig, CategorizationConfig
from ynab_tui.db.database import Database
from ynab_tui.models import Category, CategoryGroup, CategoryList, Transaction
from ynab_tui.services.sync import PullResult, PushResult, SyncService


@dataclass
class MockOrder:
    """Mock Amazon order."""

    order_id: str
    order_date: datetime
    total: float
    items: list = field(default_factory=list)


@dataclass
class MockOrderItem:
    """Mock order item."""

    name: str
    price: float | None = None
    quantity: int = 1


class MockYNABClient:
    """Mock YNAB client for testing."""

    def __init__(self):
        self.transactions: list[Transaction] = []
        self.categories = CategoryList(groups=[])
        self.update_calls: list[dict] = []
        self.split_calls: list[dict] = []
        self.budget_id = "budget-123"

    def get_all_transactions(self, since_date: datetime | None = None) -> list[Transaction]:
        """Return mock transactions."""
        if since_date:
            return [t for t in self.transactions if t.date >= since_date]
        return self.transactions

    def get_categories(self) -> CategoryList:
        """Return mock categories."""
        return self.categories

    def update_transaction(
        self,
        transaction_id: str,
        category_id: str | None = None,
        memo: str | None = None,
        approved: bool | None = None,
    ) -> Transaction:
        """Record and return updated transaction."""
        self.update_calls.append(
            {
                "transaction_id": transaction_id,
                "category_id": category_id,
                "memo": memo,
                "approved": approved,
            }
        )
        # Find and update transaction
        for t in self.transactions:
            if t.id == transaction_id:
                if category_id:
                    t.category_id = category_id
                if memo is not None:
                    t.memo = memo
                if approved is not None:
                    t.approved = approved
                return t
        # Create new transaction if not found
        return Transaction(
            id=transaction_id,
            date=datetime.now(),
            amount=0,
            payee_name="Test",
            account_name="Test",
            category_id=category_id,
            memo=memo,
            approved=approved or True,
        )

    def create_split_transaction(
        self,
        transaction_id: str,
        splits: list[dict],
        approve: bool = True,
    ) -> Transaction:
        """Record and return split transaction."""
        self.split_calls.append(
            {
                "transaction_id": transaction_id,
                "splits": splits,
                "approve": approve,
            }
        )
        return Transaction(
            id=transaction_id,
            date=datetime.now(),
            amount=0,
            payee_name="Test",
            account_name="Test",
            category_name="Split",
            category_id=None,
            approved=True,
            is_split=True,
        )

    def get_current_budget_id(self) -> str:
        return self.budget_id


class MockAmazonClient:
    """Mock Amazon client for testing."""

    def __init__(self):
        self.orders: list[MockOrder] = []
        self.get_orders_calls: list = []
        self.get_recent_calls: list = []

    def get_orders_for_year(self, year: int) -> list[MockOrder]:
        """Return mock orders for year."""
        self.get_orders_calls.append(year)
        return [o for o in self.orders if o.order_date.year == year]

    def get_recent_orders(self, days: int = 30) -> list[MockOrder]:
        """Return mock recent orders."""
        self.get_recent_calls.append(days)
        cutoff = datetime.now() - timedelta(days=days)
        return [o for o in self.orders if o.order_date >= cutoff]


def make_transaction(
    id: str = "txn-001",
    date: datetime | None = None,
    amount: float = -44.99,
    payee_name: str = "Test",
    category_id: str | None = None,
    category_name: str | None = None,
    approved: bool = False,
) -> Transaction:
    """Create test transaction."""
    return Transaction(
        id=id,
        date=date or datetime(2025, 11, 24),
        amount=amount,
        payee_name=payee_name,
        account_name="Checking",
        category_id=category_id,
        category_name=category_name,
        approved=approved,
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
def mock_amazon() -> MockAmazonClient:
    """Create mock Amazon client."""
    return MockAmazonClient()


@pytest.fixture
def sync_service(
    temp_db: Database, mock_ynab: MockYNABClient, mock_amazon: MockAmazonClient
) -> SyncService:
    """Create sync service."""
    return SyncService(
        db=temp_db,
        ynab=mock_ynab,
        amazon=mock_amazon,
        categorization_config=CategorizationConfig(),
        amazon_config=AmazonConfig(earliest_history_year=2024),
    )


class TestPullResult:
    """Tests for PullResult dataclass."""

    def test_success_true_when_no_errors(self) -> None:
        """Success is True when no errors."""
        result = PullResult(source="ynab", fetched=10)
        assert result.success is True

    def test_success_false_when_errors(self) -> None:
        """Success is False when errors exist."""
        result = PullResult(source="ynab", errors=["Error 1"])
        assert result.success is False


class TestPushResult:
    """Tests for PushResult dataclass."""

    def test_success_true_when_all_succeeded(self) -> None:
        """Success is True when no failures."""
        result = PushResult(pushed=5, succeeded=5, failed=0)
        assert result.success is True

    def test_success_false_when_failures(self) -> None:
        """Success is False when failures exist."""
        result = PushResult(pushed=5, succeeded=3, failed=2)
        assert result.success is False

    def test_success_false_when_errors(self) -> None:
        """Success is False when errors exist."""
        result = PushResult(pushed=5, succeeded=5, failed=0, errors=["Error"])
        assert result.success is False


class TestPullYnab:
    """Tests for pull_ynab method."""

    def test_pulls_all_transactions_full(
        self, temp_db: Database, mock_ynab: MockYNABClient, mock_amazon: MockAmazonClient
    ) -> None:
        """Full pull fetches all transactions."""
        mock_ynab.transactions = [
            make_transaction("txn-1", date=datetime(2025, 11, 1)),
            make_transaction("txn-2", date=datetime(2025, 11, 15)),
        ]

        service = SyncService(temp_db, mock_ynab, mock_amazon)
        result = service.pull_ynab(full=True)

        assert result.success is True
        assert result.fetched == 2
        assert result.inserted == 2
        assert result.total == 2

    def test_pulls_incremental(
        self, temp_db: Database, mock_ynab: MockYNABClient, mock_amazon: MockAmazonClient
    ) -> None:
        """Incremental pull uses since_date from sync state."""
        # Use recent dates so they pass the since_date filter
        now = datetime.now()
        recent = now - timedelta(days=1)

        mock_ynab.transactions = [
            make_transaction("txn-1", date=recent),
            make_transaction("txn-2", date=recent),
        ]

        service = SyncService(temp_db, mock_ynab, mock_amazon)

        # First pull
        result1 = service.pull_ynab(full=True)
        assert result1.inserted == 2

        # Second pull - incremental with new transaction
        mock_ynab.transactions = [
            # Include old transactions (they would be returned in real scenario)
            make_transaction("txn-1", date=recent),
            make_transaction("txn-2", date=recent),
            # New transaction
            make_transaction("txn-3", date=now),
        ]

        result2 = service.pull_ynab(full=False)
        # Should fetch all 3 (including overlap) and insert 1 new
        assert result2.fetched == 3
        assert result2.inserted == 1
        assert result2.total == 3

    def test_handles_empty_response(
        self, temp_db: Database, mock_ynab: MockYNABClient, mock_amazon: MockAmazonClient
    ) -> None:
        """Empty response handled gracefully."""
        mock_ynab.transactions = []

        service = SyncService(temp_db, mock_ynab, mock_amazon)
        result = service.pull_ynab()

        assert result.success is True
        assert result.fetched == 0

    def test_records_date_range(
        self, temp_db: Database, mock_ynab: MockYNABClient, mock_amazon: MockAmazonClient
    ) -> None:
        """Captures date range of fetched transactions."""
        mock_ynab.transactions = [
            make_transaction("txn-1", date=datetime(2025, 11, 1)),
            make_transaction("txn-2", date=datetime(2025, 11, 15)),
            make_transaction("txn-3", date=datetime(2025, 11, 30)),
        ]

        service = SyncService(temp_db, mock_ynab, mock_amazon)
        result = service.pull_ynab()

        assert result.oldest_date == datetime(2025, 11, 1)
        assert result.newest_date == datetime(2025, 11, 30)

    def test_pull_ynab_fix_creates_pending_changes_for_conflicts(
        self, temp_db: Database, mock_ynab: MockYNABClient, mock_amazon: MockAmazonClient
    ) -> None:
        """pull_ynab with fix=True creates pending_changes for conflicts."""
        # First, insert a categorized transaction
        original_txn = make_transaction(
            "txn-conflict",
            date=datetime(2025, 11, 15),
            category_id="cat-groceries",
            category_name="Groceries",
        )
        temp_db.upsert_ynab_transaction(original_txn)

        # Now mock YNAB returning it uncategorized (simulating bank re-import)
        mock_ynab.transactions = [
            make_transaction(
                "txn-conflict",
                date=datetime(2025, 11, 15),
                category_id=None,
                category_name=None,
            ),
        ]

        service = SyncService(temp_db, mock_ynab, mock_amazon)
        result = service.pull_ynab(full=True, fix=True)

        assert result.success is True
        assert result.conflicts_found == 1
        assert result.conflicts_fixed == 1

        # Verify the transaction is marked for push
        stored = temp_db.get_ynab_transaction("txn-conflict")
        assert stored["sync_status"] == "pending_push"
        assert stored["category_id"] == "cat-groceries"  # Preserved

        # Verify pending_change was created
        pending = temp_db.get_pending_change("txn-conflict")
        assert pending is not None
        assert pending["new_values"]["category_id"] == "cat-groceries"

    def test_pull_ynab_without_fix_does_not_create_pending_changes(
        self, temp_db: Database, mock_ynab: MockYNABClient, mock_amazon: MockAmazonClient
    ) -> None:
        """pull_ynab without fix=True only detects conflicts, doesn't fix them."""
        # First, insert a categorized transaction
        original_txn = make_transaction(
            "txn-conflict",
            date=datetime(2025, 11, 15),
            category_id="cat-groceries",
            category_name="Groceries",
        )
        temp_db.upsert_ynab_transaction(original_txn)

        # Now mock YNAB returning it uncategorized
        mock_ynab.transactions = [
            make_transaction(
                "txn-conflict",
                date=datetime(2025, 11, 15),
                category_id=None,
                category_name=None,
            ),
        ]

        service = SyncService(temp_db, mock_ynab, mock_amazon)
        result = service.pull_ynab(full=True, fix=False)

        assert result.success is True
        assert result.conflicts_found == 1
        assert result.conflicts_fixed == 0  # Not fixed

        # Verify the transaction is still marked as conflict
        stored = temp_db.get_ynab_transaction("txn-conflict")
        assert stored["sync_status"] == "conflict"
        assert stored["category_id"] == "cat-groceries"  # Preserved

        # Verify no pending_change was created
        pending = temp_db.get_pending_change("txn-conflict")
        assert pending is None


class TestPullAmazonIncremental:
    """Tests for incremental pull_amazon."""

    def test_incremental_with_sync_state(
        self, temp_db: Database, mock_ynab: MockYNABClient, mock_amazon: MockAmazonClient
    ) -> None:
        """Incremental pull uses sync state."""
        recent = datetime.now() - timedelta(days=1)
        mock_amazon.orders = [MockOrder("o1", recent, 50.0)]

        service = SyncService(temp_db, mock_ynab, mock_amazon)

        # First pull
        service.pull_amazon(full=True)

        # Update mock for second pull
        mock_amazon.orders = [
            MockOrder("o1", recent, 50.0),
            MockOrder("o2", datetime.now(), 100.0),
        ]

        # Incremental pull should use sync state
        result = service.pull_amazon(full=False)
        assert result.success is True

    def test_first_sync_fetches_all(
        self, temp_db: Database, mock_ynab: MockYNABClient, mock_amazon: MockAmazonClient
    ) -> None:
        """First sync (no state) fetches all history."""
        mock_amazon.orders = [
            MockOrder("o1", datetime(2024, 6, 1), 50.0),
        ]

        config = AmazonConfig(earliest_history_year=2024)
        service = SyncService(temp_db, mock_ynab, mock_amazon, amazon_config=config)

        # First pull without sync state should fetch all
        service.pull_amazon(full=False)

        # Should have called get_orders_for_year
        assert len(mock_amazon.get_orders_calls) >= 1


class TestPullAmazon:
    """Tests for pull_amazon method."""

    def test_pulls_orders_for_year(
        self, temp_db: Database, mock_ynab: MockYNABClient, mock_amazon: MockAmazonClient
    ) -> None:
        """Can pull orders for specific year."""
        mock_amazon.orders = [
            MockOrder("o1", datetime(2024, 11, 1), 44.99, items=[MockOrderItem("Item A")]),
            MockOrder("o2", datetime(2025, 1, 15), 99.99, items=[]),
        ]

        service = SyncService(temp_db, mock_ynab, mock_amazon)
        result = service.pull_amazon(year=2024)

        assert result.success is True
        assert result.fetched == 1
        assert result.inserted == 1

    def test_pulls_recent_orders(
        self, temp_db: Database, mock_ynab: MockYNABClient, mock_amazon: MockAmazonClient
    ) -> None:
        """Can pull recent orders by days."""
        # Add orders within last 30 days
        recent_date = datetime.now() - timedelta(days=5)
        mock_amazon.orders = [
            MockOrder("o1", recent_date, 44.99, items=[]),
        ]

        service = SyncService(temp_db, mock_ynab, mock_amazon)
        result = service.pull_amazon(since_days=30)

        assert result.success is True
        assert result.fetched == 1

    def test_returns_error_when_no_client(
        self, temp_db: Database, mock_ynab: MockYNABClient
    ) -> None:
        """Returns error when Amazon client not configured."""
        service = SyncService(temp_db, mock_ynab, amazon=None)
        result = service.pull_amazon()

        assert result.success is False
        assert "not configured" in result.errors[0]

    def test_stores_order_items(
        self, temp_db: Database, mock_ynab: MockYNABClient, mock_amazon: MockAmazonClient
    ) -> None:
        """Stores order items in database."""
        mock_amazon.orders = [
            MockOrder(
                "o1",
                datetime(2024, 11, 1),
                44.99,
                items=[
                    MockOrderItem("Item A", 24.99),
                    MockOrderItem("Item B", 20.00),
                ],
            ),
        ]

        service = SyncService(temp_db, mock_ynab, mock_amazon)
        result = service.pull_amazon(year=2024)

        assert result.success is True

        # Verify items stored
        items = temp_db.get_amazon_order_items_with_prices("o1")
        assert len(items) == 2


class TestPullCategories:
    """Tests for pull_categories method."""

    def test_pulls_categories(
        self, temp_db: Database, mock_ynab: MockYNABClient, mock_amazon: MockAmazonClient
    ) -> None:
        """Pulls categories from YNAB."""
        mock_ynab.categories = CategoryList(
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
                        ),
                        Category(
                            id="cat-2",
                            name="Rent",
                            group_id="grp-1",
                            group_name="Essentials",
                        ),
                    ],
                )
            ]
        )

        service = SyncService(temp_db, mock_ynab, mock_amazon)
        result = service.pull_categories()

        assert result.success is True
        assert result.fetched == 2
        assert result.total >= 2


class TestPullAll:
    """Tests for pull_all method."""

    def test_pulls_all_sources(
        self, temp_db: Database, mock_ynab: MockYNABClient, mock_amazon: MockAmazonClient
    ) -> None:
        """Pulls from categories, YNAB, and Amazon."""
        mock_ynab.transactions = [make_transaction()]
        mock_ynab.categories = CategoryList(
            groups=[
                CategoryGroup(
                    id="grp-1",
                    name="Test",
                    categories=[
                        Category(
                            id="cat-1",
                            name="Cat",
                            group_id="grp-1",
                            group_name="Test",
                        )
                    ],
                )
            ]
        )
        mock_amazon.orders = []

        service = SyncService(temp_db, mock_ynab, mock_amazon)
        results = service.pull_all()

        assert "categories" in results
        assert "ynab" in results
        assert "amazon" in results
        assert results["ynab"].fetched == 1


class TestPushYnab:
    """Tests for push_ynab method."""

    def test_dry_run_no_changes(
        self, temp_db: Database, mock_ynab: MockYNABClient, mock_amazon: MockAmazonClient
    ) -> None:
        """Dry run doesn't push changes."""
        # Add transaction and pending change
        txn = make_transaction()
        temp_db.upsert_ynab_transaction(txn)
        temp_db.create_pending_change(
            "txn-001",
            {"category_id": "cat-1", "category_name": "Groceries"},
            {"category_id": None, "category_name": None},
            "update",
        )

        service = SyncService(temp_db, mock_ynab, mock_amazon)
        result = service.push_ynab(dry_run=True)

        assert result.pushed == 1
        assert result.succeeded == 0  # Dry run doesn't succeed
        assert len(mock_ynab.update_calls) == 0

    def test_pushes_category_change(
        self, temp_db: Database, mock_ynab: MockYNABClient, mock_amazon: MockAmazonClient
    ) -> None:
        """Pushes category change to YNAB."""
        # Add transaction
        txn = make_transaction()
        mock_ynab.transactions = [txn]
        temp_db.upsert_ynab_transaction(txn)

        # Create pending change
        temp_db.create_pending_change(
            "txn-001",
            {"category_id": "cat-1", "category_name": "Groceries", "approved": True},
            {"category_id": None, "category_name": None, "approved": False},
            "update",
        )

        service = SyncService(temp_db, mock_ynab, mock_amazon)
        result = service.push_ynab()

        assert result.pushed == 1
        assert result.succeeded == 1
        assert len(mock_ynab.update_calls) == 1

    def test_pushes_split_transaction(
        self, temp_db: Database, mock_ynab: MockYNABClient, mock_amazon: MockAmazonClient
    ) -> None:
        """Pushes split transaction to YNAB."""
        # Add transaction
        txn = make_transaction(amount=-100.0)
        temp_db.upsert_ynab_transaction(txn)

        # Create pending split
        temp_db.create_pending_change(
            "txn-001",
            {"category_name": "Split", "approved": True},
            {"category_id": None},
            "split",
        )
        temp_db.mark_pending_split(
            "txn-001",
            [
                {"category_id": "cat-1", "category_name": "A", "amount": -60.0},
                {"category_id": "cat-2", "category_name": "B", "amount": -40.0},
            ],
        )

        service = SyncService(temp_db, mock_ynab, mock_amazon)
        result = service.push_ynab()

        assert result.pushed == 1
        assert result.succeeded == 1
        assert len(mock_ynab.split_calls) == 1

    def test_returns_empty_when_no_pending(
        self, temp_db: Database, mock_ynab: MockYNABClient, mock_amazon: MockAmazonClient
    ) -> None:
        """Returns success with 0 pushed when no pending."""
        service = SyncService(temp_db, mock_ynab, mock_amazon)
        result = service.push_ynab()

        assert result.success is True
        assert result.pushed == 0

    def test_calls_progress_callback(
        self, temp_db: Database, mock_ynab: MockYNABClient, mock_amazon: MockAmazonClient
    ) -> None:
        """Calls progress callback during push."""
        # Add transactions with pending changes
        for i in range(3):
            txn = make_transaction(id=f"txn-{i}")
            mock_ynab.transactions.append(txn)
            temp_db.upsert_ynab_transaction(txn)
            temp_db.create_pending_change(
                f"txn-{i}",
                {"category_id": "cat-1", "approved": True},
                {"category_id": None},
                "update",
            )

        progress_calls = []

        def progress_callback(current: int, total: int) -> None:
            progress_calls.append((current, total))

        service = SyncService(temp_db, mock_ynab, mock_amazon)
        result = service.push_ynab(progress_callback=progress_callback)

        assert result.succeeded == 3
        assert len(progress_calls) == 3
        assert progress_calls[-1] == (3, 3)

    def test_pushed_ids_populated(
        self, temp_db: Database, mock_ynab: MockYNABClient, mock_amazon: MockAmazonClient
    ) -> None:
        """Verifies pushed_ids contains successfully pushed transaction IDs."""
        # Add transactions with pending changes
        for i in range(3):
            txn = make_transaction(id=f"txn-{i}")
            mock_ynab.transactions.append(txn)
            temp_db.upsert_ynab_transaction(txn)
            temp_db.create_pending_change(
                f"txn-{i}",
                {"category_id": "cat-1", "approved": True},
                {"category_id": None},
                "update",
            )

        service = SyncService(temp_db, mock_ynab, mock_amazon)
        result = service.push_ynab()

        assert result.succeeded == 3
        assert len(result.pushed_ids) == 3
        assert set(result.pushed_ids) == {"txn-0", "txn-1", "txn-2"}

    def test_pushed_ids_empty_when_dry_run(
        self, temp_db: Database, mock_ynab: MockYNABClient, mock_amazon: MockAmazonClient
    ) -> None:
        """Verifies pushed_ids is empty on dry run."""
        txn = make_transaction()
        mock_ynab.transactions = [txn]
        temp_db.upsert_ynab_transaction(txn)
        temp_db.create_pending_change(
            "txn-001",
            {"category_id": "cat-1", "approved": True},
            {"category_id": None},
            "update",
        )

        service = SyncService(temp_db, mock_ynab, mock_amazon)
        result = service.push_ynab(dry_run=True)

        assert result.pushed == 1
        assert result.succeeded == 0
        assert len(result.pushed_ids) == 0


class TestBuildPushSummary:
    """Tests for _build_push_summary method."""

    def test_empty_changes_returns_message(self, sync_service: SyncService) -> None:
        """Empty changes returns 'No pending changes'."""
        result = sync_service._build_push_summary([])
        assert result == "No pending changes."

    def test_formats_category_change(self, sync_service: SyncService) -> None:
        """Formats category changes."""
        changes = [
            {
                "transaction_id": "txn-1",
                "date": datetime(2025, 11, 24),
                "payee_name": "Amazon.com",
                "amount": -44.99,
                "new_values": {"category_id": "cat-1", "category_name": "Groceries"},
                "original_values": {"category_name": "Uncategorized"},
            }
        ]

        result = sync_service._build_push_summary(changes)

        payee = changes[0]["payee_name"]
        assert "2025-11-24" in result
        assert payee in result
        assert "Groceries" in result

    def test_formats_memo_change(self, sync_service: SyncService) -> None:
        """Formats memo changes."""
        changes = [
            {
                "transaction_id": "txn-1",
                "date": datetime(2025, 11, 24),
                "payee_name": "Store",
                "amount": -10.0,
                "new_values": {"memo": "New memo text"},
                "original_values": {},
            }
        ]

        result = sync_service._build_push_summary(changes)

        assert "memo:" in result


class TestGetStatus:
    """Tests for get_status method."""

    def test_returns_all_sources(
        self, temp_db: Database, mock_ynab: MockYNABClient, mock_amazon: MockAmazonClient
    ) -> None:
        """Returns status for all sources."""
        service = SyncService(temp_db, mock_ynab, mock_amazon)
        status = service.get_status()

        assert "categories" in status
        assert "ynab" in status
        assert "amazon" in status

    def test_includes_counts(
        self, temp_db: Database, mock_ynab: MockYNABClient, mock_amazon: MockAmazonClient
    ) -> None:
        """Includes transaction and order counts."""
        # Add some data
        temp_db.upsert_ynab_transaction(make_transaction("txn-1"))
        temp_db.upsert_ynab_transaction(make_transaction("txn-2", category_id=None))

        service = SyncService(temp_db, mock_ynab, mock_amazon)
        status = service.get_status()

        assert status["ynab"]["transaction_count"] == 2
        assert status["ynab"]["uncategorized_count"] >= 1


class TestPullYnabErrors:
    """Tests for error handling in pull_ynab."""

    def test_handles_fetch_error(self, temp_db: Database, mock_amazon: MockAmazonClient) -> None:
        """Handles exception during YNAB fetch."""

        class FailingYNABClient(MockYNABClient):
            def get_all_transactions(self, since_date=None):
                raise Exception("API error")

        failing_ynab = FailingYNABClient()
        service = SyncService(temp_db, failing_ynab, mock_amazon)

        result = service.pull_ynab()

        assert result.success is False
        assert "API error" in result.errors[0]


class TestPullAmazonErrors:
    """Tests for error handling in pull_amazon."""

    def test_handles_fetch_error(self, temp_db: Database, mock_ynab: MockYNABClient) -> None:
        """Handles exception during Amazon fetch."""

        class FailingAmazonClient(MockAmazonClient):
            def get_orders_for_year(self, year):
                raise Exception("Amazon error")

        failing_amazon = FailingAmazonClient()
        service = SyncService(temp_db, mock_ynab, failing_amazon)

        result = service.pull_amazon(year=2024)

        assert result.success is False
        assert "Amazon error" in result.errors[0]


class TestPullCategoriesErrors:
    """Tests for error handling in pull_categories."""

    def test_handles_fetch_error(self, temp_db: Database, mock_amazon: MockAmazonClient) -> None:
        """Handles exception during category fetch."""

        class FailingYNABClient(MockYNABClient):
            def get_categories(self):
                raise Exception("Category fetch error")

        failing_ynab = FailingYNABClient()
        service = SyncService(temp_db, failing_ynab, mock_amazon)

        result = service.pull_categories()

        assert result.success is False
        assert "Category fetch error" in result.errors[0]


class TestFetchAllAmazonOrders:
    """Tests for _fetch_all_amazon_orders method."""

    def test_handles_year_error_gracefully(
        self, temp_db: Database, mock_ynab: MockYNABClient
    ) -> None:
        """Handles error for individual year gracefully."""

        class PartiallyFailingAmazonClient(MockAmazonClient):
            def get_orders_for_year(self, year):
                if year == 2025:
                    raise Exception("Year 2025 error")
                return [MockOrder("o1", datetime(2024, 6, 1), 50.0)]

        failing_amazon = PartiallyFailingAmazonClient()
        config = AmazonConfig(earliest_history_year=2024)
        service = SyncService(temp_db, mock_ynab, failing_amazon, amazon_config=config)

        orders = service._fetch_all_amazon_orders("Test")

        # Should still return orders from years that worked
        assert len(orders) >= 1

    def test_fetches_all_years(
        self, temp_db: Database, mock_ynab: MockYNABClient, mock_amazon: MockAmazonClient
    ) -> None:
        """Fetches orders for all years from current to earliest."""
        mock_amazon.orders = [
            MockOrder("o1", datetime(2024, 6, 1), 50.0),
            MockOrder("o2", datetime(2025, 1, 1), 100.0),
        ]

        earliest_year = 2024
        current_year = datetime.now().year
        config = AmazonConfig(earliest_history_year=earliest_year)
        service = SyncService(temp_db, mock_ynab, mock_amazon, amazon_config=config)

        service._fetch_all_amazon_orders("Test")

        # Should have called for each year from current down to earliest
        expected_years = current_year - earliest_year + 1
        assert len(mock_amazon.get_orders_calls) == expected_years
        assert earliest_year in mock_amazon.get_orders_calls
        assert current_year in mock_amazon.get_orders_calls

    def test_returns_empty_when_no_client(
        self, temp_db: Database, mock_ynab: MockYNABClient
    ) -> None:
        """Returns empty when no Amazon client."""
        service = SyncService(temp_db, mock_ynab, amazon=None)
        orders = service._fetch_all_amazon_orders("Test")
        assert orders == []
