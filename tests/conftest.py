"""Shared pytest fixtures for YNAB Categorizer tests."""

from datetime import datetime
from pathlib import Path

import pytest

from src.config import (
    AmazonConfig,
    CategorizationConfig,
    Config,
    DisplayConfig,
    PayeesConfig,
    YNABConfig,
    load_config,
)
from src.db.database import Database
from src.models import (
    AmazonOrder,
    Category,
    CategoryGroup,
    CategoryList,
    OrderItem,
    SubTransaction,
    Transaction,
)


@pytest.fixture
def temp_db_path(tmp_path):
    """Create a temporary database path."""
    return tmp_path / "test_categorizer.db"


@pytest.fixture
def database(temp_db_path):
    """Create a test database instance."""
    return Database(temp_db_path)


@pytest.fixture(scope="session")
def test_config():
    """Load test configuration from tests/test_config.toml."""
    config_path = Path(__file__).parent / "test_config.toml"
    return load_config(config_path)


@pytest.fixture
def sample_config():
    """Create a sample configuration."""
    return Config(
        ynab=YNABConfig(
            api_token="test-token",
            budget_id="test-budget-id",
        ),
        amazon=AmazonConfig(
            username="test@example.com",
            password="test-password",
            otp_secret="",
        ),
        categorization=CategorizationConfig(
            date_match_window_days=3,
        ),
        payees=PayeesConfig(
            amazon_patterns=["AMAZON", "AMZN", "Amazon.com"],
        ),
        display=DisplayConfig(),
    )


@pytest.fixture
def sample_transaction():
    """Create a sample transaction."""
    return Transaction(
        id="txn-001",
        date=datetime(2024, 1, 15),
        amount=-47.82,
        payee_name="AMAZON.COM",
        payee_id="payee-001",
        memo="Online purchase",
        account_name="Checking",
        account_id="acc-001",
    )


@pytest.fixture
def sample_amazon_transaction():
    """Create a sample Amazon transaction with enrichment."""
    txn = Transaction(
        id="txn-002",
        date=datetime(2024, 1, 15),
        amount=-47.82,
        payee_name="AMAZON.COM",
        payee_id="payee-001",
        account_name="Checking",
        account_id="acc-001",
    )
    txn.is_amazon = True
    txn.amazon_items = ["USB-C Cable", "Phone Case"]
    txn.amazon_order_id = "order-123"
    return txn


@pytest.fixture
def sample_non_amazon_transaction():
    """Create a sample non-Amazon transaction."""
    return Transaction(
        id="txn-003",
        date=datetime(2024, 1, 14),
        amount=-127.43,
        payee_name="COSTCO WHOLESALE",
        payee_id="payee-002",
        account_name="Checking",
        account_id="acc-001",
    )


@pytest.fixture
def sample_transactions():
    """Create a list of sample transactions."""
    return [
        Transaction(
            id="txn-001",
            date=datetime(2024, 1, 15),
            amount=-47.82,
            payee_name="AMAZON.COM",
        ),
        Transaction(
            id="txn-002",
            date=datetime(2024, 1, 14),
            amount=-127.43,
            payee_name="COSTCO WHOLESALE",
        ),
        Transaction(
            id="txn-003",
            date=datetime(2024, 1, 13),
            amount=-45.00,
            payee_name="SHELL OIL",
        ),
        Transaction(
            id="txn-004",
            date=datetime(2024, 1, 12),
            amount=-23.99,
            payee_name="AMZN MKTPLACE",
        ),
    ]


@pytest.fixture
def sample_category():
    """Create a sample category."""
    return Category(
        id="cat-001",
        name="Electronics",
        group_id="group-001",
        group_name="Shopping",
    )


@pytest.fixture
def sample_category_list():
    """Create a sample category list."""
    return CategoryList(
        groups=[
            CategoryGroup(
                id="group-001",
                name="Shopping",
                categories=[
                    Category(
                        id="cat-001",
                        name="Electronics",
                        group_id="group-001",
                        group_name="Shopping",
                    ),
                    Category(
                        id="cat-002", name="Clothing", group_id="group-001", group_name="Shopping"
                    ),
                    Category(
                        id="cat-003",
                        name="Home & Garden",
                        group_id="group-001",
                        group_name="Shopping",
                    ),
                ],
            ),
            CategoryGroup(
                id="group-002",
                name="Bills",
                categories=[
                    Category(
                        id="cat-004", name="Utilities", group_id="group-002", group_name="Bills"
                    ),
                    Category(
                        id="cat-005", name="Internet", group_id="group-002", group_name="Bills"
                    ),
                ],
            ),
            CategoryGroup(
                id="group-003",
                name="Everyday",
                categories=[
                    Category(
                        id="cat-006", name="Groceries", group_id="group-003", group_name="Everyday"
                    ),
                    Category(
                        id="cat-007", name="Auto & Gas", group_id="group-003", group_name="Everyday"
                    ),
                    Category(
                        id="cat-008",
                        name="Restaurants",
                        group_id="group-003",
                        group_name="Everyday",
                    ),
                ],
            ),
        ]
    )


@pytest.fixture
def sample_amazon_order():
    """Create a sample Amazon order."""
    return AmazonOrder(
        order_id="order-123",
        order_date=datetime(2024, 1, 14),
        total=47.82,
        items=[
            OrderItem(name="USB-C Cable", price=12.99, quantity=1),
            OrderItem(name="Phone Case", price=34.83, quantity=1),
        ],
    )


@pytest.fixture
def config_toml_content():
    """Sample TOML configuration content."""
    return """
[ynab]
api_token = "toml-token"
budget_id = "toml-budget"

[amazon]
username = "toml@example.com"
password = "toml-password"

[categorization]
date_match_window_days = 5

[payees]
amazon_patterns = ["AMAZON", "AMZN"]
"""


# =============================================================================
# Sync-related fixtures
# =============================================================================


@pytest.fixture(scope="session")
def mock_ynab_client():
    """Create mock YNAB client once for entire test session.

    Uses max_transactions=100 for faster tests.
    """
    from src.clients import MockYNABClient

    return MockYNABClient(max_transactions=100)


@pytest.fixture(scope="session")
def mock_amazon_client():
    """Create mock Amazon client once for entire test session."""
    from src.clients import MockAmazonClient

    return MockAmazonClient()


@pytest.fixture
def sync_service(database, mock_ynab_client, mock_amazon_client):
    """Create SyncService with mock clients and temp database."""
    from src.services.sync import SyncService

    return SyncService(
        db=database,
        ynab=mock_ynab_client,
        amazon=mock_amazon_client,
    )


@pytest.fixture
def sample_sync_transaction():
    """Create a sample Transaction for sync testing."""
    return Transaction(
        id="txn-sync-001",
        date=datetime(2025, 1, 15),
        amount=-47.82,
        payee_name="AMAZON.COM",
        payee_id="payee-001",
        account_name="Checking",
        account_id="acc-001",
        approved=True,
        category_id="cat-001",
        category_name="Electronics",
        sync_status="synced",
    )


@pytest.fixture
def split_transaction():
    """Create a split Transaction with subtransactions for testing."""
    return Transaction(
        id="txn-split-001",
        date=datetime(2025, 1, 15),
        amount=-100.00,
        payee_name="COSTCO WHOLESALE",
        payee_id="payee-002",
        account_name="Checking",
        account_id="acc-001",
        approved=True,
        is_split=True,
        category_id=None,  # Split transactions have no category at parent level
        category_name="Split",
        subtransactions=[
            SubTransaction(
                id="sub-001",
                transaction_id="txn-split-001",
                amount=-60.00,
                payee_name="COSTCO WHOLESALE",
                category_id="cat-006",
                category_name="Groceries",
            ),
            SubTransaction(
                id="sub-002",
                transaction_id="txn-split-001",
                amount=-40.00,
                payee_name="COSTCO WHOLESALE",
                category_id="cat-003",
                category_name="Home & Garden",
            ),
        ],
    )


# =============================================================================
# Shared service fixtures
# =============================================================================


@pytest.fixture
def categorizer_service(database, sample_config, mock_ynab_client):
    """Create a CategorizerService with mock clients.

    This is the shared fixture for all tests that need CategorizerService.
    """
    from src.services.categorizer import CategorizerService

    return CategorizerService(
        config=sample_config,
        ynab_client=mock_ynab_client,
        db=database,
    )


@pytest.fixture
def category_mapping_service(database):
    """Create a CategoryMappingService instance."""
    from src.services.category_mapping import CategoryMappingService

    return CategoryMappingService(database)


@pytest.fixture
def amazon_order_matcher(database):
    """Create an AmazonOrderMatcher instance."""
    from src.services.amazon_matcher import AmazonOrderMatcher

    return AmazonOrderMatcher(database)


@pytest.fixture
def transaction_matcher(database, sample_config):
    """Create a TransactionMatcher instance."""
    from src.services.matcher import TransactionMatcher

    return TransactionMatcher(
        db=database,
        categorization_config=sample_config.categorization,
        payees_config=sample_config.payees,
    )


# =============================================================================
# Test helper functions
# =============================================================================


@pytest.fixture
def add_order_to_db(database):
    """Fixture that returns a helper function to add orders to database.

    Usage:
        def test_something(database, add_order_to_db):
            add_order_to_db("order-123", datetime(2024, 1, 15), 47.82, ["Item 1", "Item 2"])
    """

    def _add_order(order_id, order_date, total, items):
        """Add an order to the database cache.

        Args:
            order_id: Order ID string.
            order_date: Order date.
            total: Order total.
            items: List of item names (strings).
        """
        database.cache_amazon_order(
            order_id=order_id,
            order_date=order_date,
            total=total,
        )
        # Convert string items to dict format expected by upsert_amazon_order_items
        item_dicts = [{"name": name} for name in items]
        database.upsert_amazon_order_items(order_id, item_dicts)

    return _add_order


def assert_pending_change(database, txn_id, **expected):
    """Assert pending change matches expected values.

    Args:
        database: Database instance.
        txn_id: Transaction ID.
        **expected: Key-value pairs to check against pending change.
    """
    pending = database.get_pending_change(txn_id)
    assert pending is not None, f"No pending change found for {txn_id}"
    for key, value in expected.items():
        assert pending[key] == value, f"Expected {key}={value}, got {pending[key]}"
