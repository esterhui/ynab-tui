"""Tests for database operations."""

from datetime import datetime

from src.db.database import CategorizationRecord, Database
from src.models import Transaction


class TestDatabaseInit:
    """Tests for database initialization."""

    def test_creates_database_file(self, temp_db_path):
        """Test that database file is created."""
        assert not temp_db_path.exists()
        _ = Database(temp_db_path)  # Creating database triggers file creation
        assert temp_db_path.exists()

    def test_creates_tables(self, database):
        """Test that required tables are created."""
        with database._connection() as conn:
            # Check categorization_history table
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='categorization_history'"
            )
            assert cursor.fetchone() is not None

            # Check amazon_orders_cache table
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='amazon_orders_cache'"
            )
            assert cursor.fetchone() is not None

    def test_creates_indexes(self, database):
        """Test that indexes are created."""
        with database._connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_payee_normalized'"
            )
            assert cursor.fetchone() is not None


class TestNormalizePayee:
    """Tests for payee normalization."""

    def test_lowercase(self):
        """Test lowercase conversion."""
        assert Database.normalize_payee("AMAZON") == "amazon"

    def test_trim_whitespace(self):
        """Test whitespace trimming."""
        assert Database.normalize_payee("  Amazon  ") == "amazon"

    def test_combined(self):
        """Test lowercase and trim together."""
        assert Database.normalize_payee("  COSTCO WHOLESALE  ") == "costco wholesale"


class TestCategorizationHistory:
    """Tests for categorization history operations."""

    def test_add_categorization(self, database):
        """Test adding a categorization record."""
        record_id = database.add_categorization(
            payee_name="AMAZON.COM",
            category_name="Electronics",
            category_id="cat-001",
            amount=-47.82,
        )
        assert record_id > 0

    def test_add_categorization_with_amazon_items(self, database):
        """Test adding a categorization with Amazon items."""
        record_id = database.add_categorization(
            payee_name="AMAZON.COM",
            category_name="Electronics",
            category_id="cat-001",
            amount=-47.82,
            amazon_items=["USB-C Cable", "Phone Case"],
        )
        assert record_id > 0

        # Verify items were stored
        history = database.get_payee_history("AMAZON.COM")
        assert len(history) == 1
        assert history[0].amazon_items == ["USB-C Cable", "Phone Case"]

    def test_get_payee_history(self, database):
        """Test retrieving payee history."""
        # Add multiple records
        database.add_categorization("COSTCO", "Groceries", "cat-001", -89.50)
        database.add_categorization("COSTCO", "Groceries", "cat-001", -145.00)
        database.add_categorization("COSTCO", "Home Improvement", "cat-002", -299.00)

        history = database.get_payee_history("COSTCO")

        assert len(history) == 3
        assert all(isinstance(r, CategorizationRecord) for r in history)
        assert all(r.payee_normalized == "costco" for r in history)

    def test_get_payee_history_case_insensitive(self, database):
        """Test that payee lookup is case-insensitive."""
        database.add_categorization("COSTCO", "Groceries", "cat-001", -89.50)

        # Query with different case
        history = database.get_payee_history("costco")
        assert len(history) == 1

        history = database.get_payee_history("Costco")
        assert len(history) == 1

    def test_get_payee_history_limit(self, database):
        """Test history limit parameter."""
        for i in range(10):
            database.add_categorization("COSTCO", "Groceries", "cat-001", -50.0 - i)

        history = database.get_payee_history("COSTCO", limit=5)
        assert len(history) == 5

    def test_get_payee_history_empty(self, database):
        """Test empty history for unknown payee."""
        history = database.get_payee_history("UNKNOWN_PAYEE")
        assert history == []

    def test_get_payee_category_distribution(self, database):
        """Test getting category distribution for a payee."""
        # Add categorizations with different categories
        database.add_categorization("COSTCO", "Groceries", "cat-001", -89.50)
        database.add_categorization("COSTCO", "Groceries", "cat-001", -145.00)
        database.add_categorization("COSTCO", "Groceries", "cat-001", -120.00)
        database.add_categorization("COSTCO", "Home Improvement", "cat-002", -299.00)

        dist = database.get_payee_category_distribution("COSTCO")

        assert "Groceries" in dist
        assert "Home Improvement" in dist
        assert dist["Groceries"]["count"] == 3
        assert dist["Home Improvement"]["count"] == 1
        assert dist["Groceries"]["percentage"] == 0.75
        assert dist["Home Improvement"]["percentage"] == 0.25

    def test_get_payee_category_distribution_avg_amount(self, database):
        """Test average amount calculation in distribution."""
        database.add_categorization("COSTCO", "Groceries", "cat-001", -100.00)
        database.add_categorization("COSTCO", "Groceries", "cat-001", -200.00)

        dist = database.get_payee_category_distribution("COSTCO")

        assert dist["Groceries"]["avg_amount"] == -150.00

    def test_get_payee_category_distribution_empty(self, database):
        """Test empty distribution for unknown payee."""
        dist = database.get_payee_category_distribution("UNKNOWN")
        assert dist == {}


class TestAmazonOrderCache:
    """Tests for Amazon order caching."""

    def test_cache_amazon_order(self, database):
        """Test caching an Amazon order."""
        database.cache_amazon_order(
            order_id="order-123",
            order_date=datetime(2024, 1, 15),
            total=47.82,
        )
        database.upsert_amazon_order_items(
            "order-123", [{"name": "USB-C Cable"}, {"name": "Phone Case"}]
        )

        # Verify by date range query
        orders = database.get_cached_orders_by_date_range(
            datetime(2024, 1, 1),
            datetime(2024, 1, 31),
        )
        assert len(orders) == 1
        assert orders[0].order_id == "order-123"
        assert set(orders[0].items) == {"USB-C Cable", "Phone Case"}

    def test_cache_order_upsert(self, database):
        """Test that caching same order ID updates it."""
        database.cache_amazon_order(
            order_id="order-123",
            order_date=datetime(2024, 1, 15),
            total=47.82,
        )
        database.upsert_amazon_order_items("order-123", [{"name": "Old Item"}])

        # Cache again with same ID but different items
        database.cache_amazon_order(
            order_id="order-123",
            order_date=datetime(2024, 1, 15),
            total=47.82,
        )
        database.upsert_amazon_order_items("order-123", [{"name": "New Item"}])

        orders = database.get_cached_orders_by_date_range(
            datetime(2024, 1, 1),
            datetime(2024, 1, 31),
        )
        assert len(orders) == 1
        assert orders[0].items == ["New Item"]

    def test_get_cached_orders_by_date_range(self, database):
        """Test retrieving cached orders by date range."""
        database.cache_amazon_order("order-1", datetime(2024, 1, 10), 25.00)
        database.upsert_amazon_order_items("order-1", [{"name": "Item 1"}])
        database.cache_amazon_order("order-2", datetime(2024, 1, 15), 50.00)
        database.upsert_amazon_order_items("order-2", [{"name": "Item 2"}])
        database.cache_amazon_order("order-3", datetime(2024, 1, 20), 75.00)
        database.upsert_amazon_order_items("order-3", [{"name": "Item 3"}])
        database.cache_amazon_order("order-4", datetime(2024, 2, 1), 100.00)
        database.upsert_amazon_order_items("order-4", [{"name": "Item 4"}])

        # Query for mid-January
        orders = database.get_cached_orders_by_date_range(
            datetime(2024, 1, 12),
            datetime(2024, 1, 18),
        )

        assert len(orders) == 1
        assert orders[0].order_id == "order-2"

    def test_get_cached_orders_by_date_range_inclusive(self, database):
        """Test that date range is inclusive."""
        database.cache_amazon_order("order-1", datetime(2024, 1, 15), 50.00)
        database.upsert_amazon_order_items("order-1", [{"name": "Item"}])

        orders = database.get_cached_orders_by_date_range(
            datetime(2024, 1, 15),
            datetime(2024, 1, 15),
        )

        assert len(orders) == 1

    def test_get_cached_order_by_amount(self, database):
        """Test finding cached order by amount."""
        database.cache_amazon_order("order-1", datetime(2024, 1, 15), 47.82)
        database.upsert_amazon_order_items("order-1", [{"name": "USB-C Cable"}])
        database.cache_amazon_order("order-2", datetime(2024, 1, 14), 99.99)
        database.upsert_amazon_order_items("order-2", [{"name": "Other Item"}])

        order = database.get_cached_order_by_amount(
            amount=47.82,
            date=datetime(2024, 1, 16),
            window_days=3,
        )

        assert order is not None
        assert order.order_id == "order-1"
        assert order.total == 47.82

    def test_get_cached_order_by_amount_tolerance(self, database):
        """Test amount matching with tolerance."""
        database.cache_amazon_order("order-1", datetime(2024, 1, 15), 47.82)
        database.upsert_amazon_order_items("order-1", [{"name": "Item"}])

        # Slightly different amount (within tolerance)
        order = database.get_cached_order_by_amount(
            amount=47.81,  # 1 cent difference
            date=datetime(2024, 1, 15),
            window_days=3,
            tolerance=0.02,
        )

        assert order is not None
        assert order.order_id == "order-1"

    def test_get_cached_order_by_amount_outside_tolerance(self, database):
        """Test amount matching fails outside tolerance."""
        database.cache_amazon_order("order-1", datetime(2024, 1, 15), 47.82)

        order = database.get_cached_order_by_amount(
            amount=50.00,  # More than tolerance
            date=datetime(2024, 1, 15),
            window_days=3,
            tolerance=0.01,
        )

        assert order is None

    def test_get_cached_order_by_amount_outside_window(self, database):
        """Test that orders outside date window aren't matched."""
        database.cache_amazon_order("order-1", datetime(2024, 1, 15), 47.82)

        order = database.get_cached_order_by_amount(
            amount=47.82,
            date=datetime(2024, 1, 25),  # 10 days later
            window_days=3,
        )

        assert order is None

    def test_get_cached_order_by_amount_best_match(self, database):
        """Test that best match is returned when multiple options."""
        database.cache_amazon_order("order-1", datetime(2024, 1, 14), 47.80)
        database.cache_amazon_order("order-2", datetime(2024, 1, 15), 47.82)  # Exact

        order = database.get_cached_order_by_amount(
            amount=47.82,
            date=datetime(2024, 1, 15),
            window_days=3,
            tolerance=0.10,
        )

        # Should prefer exact amount match
        assert order is not None
        assert order.order_id == "order-2"

    def test_get_cached_order_not_found(self, database):
        """Test when no matching order exists."""
        order = database.get_cached_order_by_amount(
            amount=100.00,
            date=datetime(2024, 1, 15),
            window_days=3,
        )
        assert order is None


class TestDatabaseEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_payee_name(self, database):
        """Test handling empty payee name."""
        record_id = database.add_categorization("", "Groceries", "cat-001", -50.00)
        assert record_id > 0

        history = database.get_payee_history("")
        assert len(history) == 1

    def test_none_amount(self, database):
        """Test handling None amount."""
        record_id = database.add_categorization("COSTCO", "Groceries", "cat-001", None)
        assert record_id > 0

        history = database.get_payee_history("COSTCO")
        assert len(history) == 1
        assert history[0].amount is None

    def test_special_characters_in_payee(self, database):
        """Test handling special characters in payee name."""
        payee = "O'REILLY AUTO PARTS #123"
        database.add_categorization(payee, "Auto", "cat-001", -50.00)

        history = database.get_payee_history(payee)
        assert len(history) == 1
        assert history[0].payee_name == payee

    def test_unicode_in_items(self, database):
        """Test handling unicode in Amazon items."""
        items = ["Café Coffee Maker", "日本語 Item"]
        database.cache_amazon_order("order-1", datetime(2024, 1, 15), 100.00)
        database.upsert_amazon_order_items("order-1", [{"name": item} for item in items])

        orders = database.get_cached_orders_by_date_range(
            datetime(2024, 1, 1),
            datetime(2024, 1, 31),
        )
        assert set(orders[0].items) == set(items)


# =============================================================================
# YNAB Transaction Tests (new sync infrastructure)
# =============================================================================


class TestYNABTransactions:
    """Tests for YNAB transaction storage."""

    def test_upsert_ynab_transaction_insert(self, database, sample_sync_transaction):
        """Test inserting a new transaction."""
        was_inserted, was_changed = database.upsert_ynab_transaction(sample_sync_transaction)

        assert was_inserted is True
        assert was_changed is True
        assert database.get_transaction_count() == 1

    def test_upsert_ynab_transaction_update(self, database, sample_sync_transaction):
        """Test updating existing transaction with changed data."""
        database.upsert_ynab_transaction(sample_sync_transaction)
        sample_sync_transaction.memo = "Updated memo"
        was_inserted, was_changed = database.upsert_ynab_transaction(sample_sync_transaction)

        assert was_inserted is False  # Updated, not inserted
        assert was_changed is True  # Data actually changed
        assert database.get_transaction_count() == 1

    def test_upsert_ynab_transaction_no_change(self, database, sample_sync_transaction):
        """Test upserting same transaction with no changes."""
        database.upsert_ynab_transaction(sample_sync_transaction)
        was_inserted, was_changed = database.upsert_ynab_transaction(sample_sync_transaction)

        assert was_inserted is False  # Not inserted (existed)
        assert was_changed is False  # No data change
        assert database.get_transaction_count() == 1

    def test_upsert_preserves_pending_push(self, database, sample_sync_transaction):
        """Test that upsert doesn't overwrite pending_push status."""
        database.upsert_ynab_transaction(sample_sync_transaction)

        # Mark as pending push with new category
        database.mark_pending_push(sample_sync_transaction.id, "cat-002", "Clothing")

        # Re-sync from YNAB with original category
        sample_sync_transaction.category_name = "From YNAB"
        sample_sync_transaction.category_id = "cat-original"
        database.upsert_ynab_transaction(sample_sync_transaction)

        # Local change should be preserved
        txn = database.get_ynab_transaction(sample_sync_transaction.id)
        assert txn["category_name"] == "Clothing"
        assert txn["sync_status"] == "pending_push"

    def test_get_ynab_transaction(self, database, sample_sync_transaction):
        """Test getting a single transaction by ID."""
        database.upsert_ynab_transaction(sample_sync_transaction)

        txn = database.get_ynab_transaction(sample_sync_transaction.id)

        assert txn is not None
        assert txn["id"] == sample_sync_transaction.id
        assert txn["payee_name"] == sample_sync_transaction.payee_name

    def test_get_ynab_transaction_not_found(self, database):
        """Test getting a non-existent transaction."""
        txn = database.get_ynab_transaction("non-existent-id")
        assert txn is None

    def test_get_ynab_transactions_all(self, database, sample_sync_transaction):
        """Test getting all transactions."""
        database.upsert_ynab_transaction(sample_sync_transaction)

        # Add another transaction
        txn2 = Transaction(
            id="txn-sync-002",
            date=datetime(2025, 1, 16),
            amount=-25.00,
            payee_name="COSTCO",
            approved=False,
        )
        database.upsert_ynab_transaction(txn2)

        txns = database.get_ynab_transactions()
        assert len(txns) == 2

    def test_get_ynab_transactions_approved_only(self, database, sample_sync_transaction):
        """Test filtering approved transactions only."""
        database.upsert_ynab_transaction(sample_sync_transaction)

        # Add unapproved transaction
        txn2 = Transaction(
            id="txn-sync-002",
            date=datetime(2025, 1, 16),
            amount=-25.00,
            payee_name="COSTCO",
            approved=False,
        )
        database.upsert_ynab_transaction(txn2)

        txns = database.get_ynab_transactions(approved_only=True)
        assert len(txns) == 1
        assert txns[0]["id"] == sample_sync_transaction.id

    def test_get_ynab_transactions_uncategorized_only(self, database):
        """Test filtering uncategorized transactions only."""
        # Categorized transaction
        txn1 = Transaction(
            id="txn-cat",
            date=datetime(2025, 1, 15),
            amount=-50.00,
            payee_name="AMAZON",
            category_id="cat-001",
            category_name="Electronics",
        )
        database.upsert_ynab_transaction(txn1)

        # Uncategorized transaction
        txn2 = Transaction(
            id="txn-uncat",
            date=datetime(2025, 1, 16),
            amount=-25.00,
            payee_name="Unknown Store",
            category_id=None,
            category_name=None,
        )
        database.upsert_ynab_transaction(txn2)

        txns = database.get_ynab_transactions(uncategorized_only=True)
        assert len(txns) == 1
        assert txns[0]["id"] == "txn-uncat"

    def test_get_ynab_transactions_pending_push_only(self, database, sample_sync_transaction):
        """Test filtering pending push transactions."""
        database.upsert_ynab_transaction(sample_sync_transaction)
        database.mark_pending_push(sample_sync_transaction.id, "cat-002", "Clothing")

        # Add synced transaction
        txn2 = Transaction(
            id="txn-synced",
            date=datetime(2025, 1, 16),
            amount=-25.00,
            payee_name="COSTCO",
        )
        database.upsert_ynab_transaction(txn2)

        txns = database.get_ynab_transactions(pending_push_only=True)
        assert len(txns) == 1
        assert txns[0]["id"] == sample_sync_transaction.id

    def test_get_ynab_transactions_payee_filter(self, database, sample_sync_transaction):
        """Test filtering by payee name."""
        database.upsert_ynab_transaction(sample_sync_transaction)

        # Add different payee
        txn2 = Transaction(
            id="txn-costco",
            date=datetime(2025, 1, 16),
            amount=-100.00,
            payee_name="COSTCO WHOLESALE",
        )
        database.upsert_ynab_transaction(txn2)

        txns = database.get_ynab_transactions(payee_filter="AMAZON")
        assert len(txns) == 1
        assert txns[0]["payee_name"] == "AMAZON.COM"

    def test_get_ynab_transactions_limit(self, database):
        """Test limit parameter."""
        for i in range(10):
            txn = Transaction(
                id=f"txn-{i}",
                date=datetime(2025, 1, i + 1),
                amount=-10.00,
                payee_name=f"Payee {i}",
            )
            database.upsert_ynab_transaction(txn)

        txns = database.get_ynab_transactions(limit=5)
        assert len(txns) == 5

    def test_subtransactions_stored_correctly(self, database, split_transaction):
        """Test split transaction stores subtransactions."""
        database.upsert_ynab_transaction(split_transaction)

        # Get subtransactions
        subs = database.get_subtransactions(split_transaction.id)

        assert len(subs) == 2
        assert subs[0]["parent_transaction_id"] == split_transaction.id

    def test_batch_upsert(self, database):
        """Test batch upsert transactions."""
        txns = [
            Transaction(
                id=f"batch-{i}",
                date=datetime(2025, 1, i + 1),
                amount=-10.00 * i,
                payee_name=f"Batch Payee {i}",
            )
            for i in range(5)
        ]

        inserted, updated = database.upsert_ynab_transactions(txns)

        assert inserted == 5
        assert updated == 0
        assert database.get_transaction_count() == 5


class TestSyncState:
    """Tests for sync state tracking."""

    def test_get_sync_state_returns_none_initially(self, database):
        """Test sync state is None before any sync."""
        state = database.get_sync_state("ynab")
        assert state is None

    def test_update_and_get_sync_state(self, database):
        """Test updating and retrieving sync state."""
        database.update_sync_state("ynab", datetime(2025, 1, 15), 100)

        state = database.get_sync_state("ynab")

        assert state is not None
        assert state["key"] == "ynab"
        assert state["record_count"] == 100
        assert state["last_sync_date"].year == 2025
        assert state["last_sync_date"].month == 1
        assert state["last_sync_date"].day == 15

    def test_update_sync_state_overwrites(self, database):
        """Test updating sync state replaces previous values."""
        database.update_sync_state("ynab", datetime(2025, 1, 10), 50)
        database.update_sync_state("ynab", datetime(2025, 1, 20), 100)

        state = database.get_sync_state("ynab")

        assert state["record_count"] == 100
        assert state["last_sync_date"].day == 20

    def test_separate_sync_states(self, database):
        """Test YNAB and Amazon have separate sync states."""
        database.update_sync_state("ynab", datetime(2025, 1, 15), 100)
        database.update_sync_state("amazon", datetime(2025, 1, 10), 50)

        ynab_state = database.get_sync_state("ynab")
        amazon_state = database.get_sync_state("amazon")

        assert ynab_state["record_count"] == 100
        assert amazon_state["record_count"] == 50


class TestAmazonOrderItems:
    """Tests for Amazon order item storage."""

    def test_upsert_amazon_order_items(self, database):
        """Test storing Amazon order items."""
        # First cache the order
        database.cache_amazon_order(
            "order-123",
            datetime(2025, 1, 15),
            47.82,
        )

        # Then store items with detail
        items = [
            {"name": "USB Cable", "price": 9.99, "quantity": 2},
            {"name": "Phone Case", "price": 27.84, "quantity": 1},
        ]
        count = database.upsert_amazon_order_items("order-123", items)

        assert count == 2
        assert database.get_order_item_count() == 2

    def test_upsert_amazon_order_items_replaces(self, database):
        """Test that upserting items replaces existing items."""
        database.cache_amazon_order("order-123", datetime(2025, 1, 15), 50.00)

        # First upsert
        database.upsert_amazon_order_items("order-123", [{"name": "Item 1"}])
        assert database.get_order_item_count() == 1

        # Second upsert replaces
        database.upsert_amazon_order_items(
            "order-123",
            [{"name": "Item A"}, {"name": "Item B"}],
        )
        assert database.get_order_item_count() == 2

    def test_set_amazon_item_category(self, database):
        """Test setting category for Amazon items."""
        database.cache_amazon_order("order-123", datetime(2025, 1, 15), 50.00)
        database.upsert_amazon_order_items(
            "order-123",
            [{"name": "USB Cable"}, {"name": "USB Cable"}],  # Same item twice
        )

        # Set category for all matching items
        updated = database.set_amazon_item_category("USB Cable", "cat-001", "Electronics")

        assert updated == 2

    def test_get_amazon_item_categories_empty(self, database):
        """Test getting categories when none set."""
        result = database.get_amazon_item_categories()
        assert result == {}


class TestTransactionCounts:
    """Tests for count methods."""

    def test_get_transaction_count_empty(self, database):
        """Test count is zero for empty database."""
        assert database.get_transaction_count() == 0

    def test_get_transaction_count(self, database, sample_sync_transaction):
        """Test transaction count."""
        database.upsert_ynab_transaction(sample_sync_transaction)
        assert database.get_transaction_count() == 1

    def test_get_transaction_count_excludes_subtransactions(self, database, split_transaction):
        """Test that subtransactions are excluded from count by default."""
        database.upsert_ynab_transaction(split_transaction)

        # Should be 1 (parent only), not 3 (parent + 2 subs)
        assert database.get_transaction_count() == 1

    def test_get_uncategorized_count(self, database):
        """Test uncategorized count."""
        # Categorized
        txn1 = Transaction(
            id="cat-1",
            date=datetime(2025, 1, 15),
            amount=-50.00,
            payee_name="Amazon",
            category_id="cat-001",
            category_name="Electronics",
        )
        database.upsert_ynab_transaction(txn1)

        # Uncategorized
        txn2 = Transaction(
            id="uncat-1",
            date=datetime(2025, 1, 16),
            amount=-25.00,
            payee_name="Unknown",
        )
        database.upsert_ynab_transaction(txn2)

        assert database.get_uncategorized_count() == 1

    def test_get_pending_push_count(self, database, sample_sync_transaction):
        """Test pending push count."""
        database.upsert_ynab_transaction(sample_sync_transaction)

        assert database.get_pending_push_count() == 0

        database.mark_pending_push(sample_sync_transaction.id, "cat-002", "Clothing")

        assert database.get_pending_push_count() == 1

    def test_get_order_count(self, database):
        """Test order count."""
        assert database.get_order_count() == 0

        database.cache_amazon_order("order-1", datetime(2025, 1, 15), 50.00)
        database.cache_amazon_order("order-2", datetime(2025, 1, 16), 75.00)

        assert database.get_order_count() == 2

    def test_get_order_item_count(self, database):
        """Test order item count."""
        assert database.get_order_item_count() == 0

        database.cache_amazon_order("order-1", datetime(2025, 1, 15), 50.00)
        database.upsert_amazon_order_items(
            "order-1",
            [{"name": "Item 1"}, {"name": "Item 2"}, {"name": "Item 3"}],
        )

        assert database.get_order_item_count() == 3


class TestMarkPendingPush:
    """Tests for mark_pending_push method."""

    def test_mark_pending_push_updates_category(self, database, sample_sync_transaction):
        """Test marking transaction as pending push."""
        database.upsert_ynab_transaction(sample_sync_transaction)

        success = database.mark_pending_push(
            sample_sync_transaction.id,
            "cat-new",
            "New Category",
        )

        assert success is True

        txn = database.get_ynab_transaction(sample_sync_transaction.id)
        assert txn["category_id"] == "cat-new"
        assert txn["category_name"] == "New Category"
        assert txn["sync_status"] == "pending_push"
        assert txn["modified_at"] is not None

    def test_mark_pending_push_not_found(self, database):
        """Test marking non-existent transaction."""
        success = database.mark_pending_push("non-existent", "cat-1", "Cat")
        assert success is False


class TestMarkSynced:
    """Tests for mark_synced method."""

    def test_mark_synced_clears_pending(self, database, sample_sync_transaction):
        """Test marking transaction as synced."""
        database.upsert_ynab_transaction(sample_sync_transaction)
        database.mark_pending_push(sample_sync_transaction.id, "cat-1", "Cat")

        success = database.mark_synced(sample_sync_transaction.id)

        assert success is True

        txn = database.get_ynab_transaction(sample_sync_transaction.id)
        assert txn["sync_status"] == "synced"

    def test_mark_synced_not_found(self, database):
        """Test marking non-existent transaction as synced."""
        success = database.mark_synced("non-existent")
        assert success is False


class TestGetYNABTransactionByAmountDate:
    """Tests for finding transactions by amount and date."""

    def test_find_exact_match(self, database, sample_sync_transaction):
        """Test finding transaction with exact amount and date."""
        database.upsert_ynab_transaction(sample_sync_transaction)

        txn = database.get_ynab_transaction_by_amount_date(
            amount=sample_sync_transaction.amount,
            date=sample_sync_transaction.date,
        )

        assert txn is not None
        assert txn["id"] == sample_sync_transaction.id

    def test_find_within_tolerance(self, database, sample_sync_transaction):
        """Test finding transaction within amount tolerance."""
        database.upsert_ynab_transaction(sample_sync_transaction)

        txn = database.get_ynab_transaction_by_amount_date(
            amount=sample_sync_transaction.amount + 0.05,  # Within default 0.10 tolerance
            date=sample_sync_transaction.date,
        )

        assert txn is not None

    def test_not_found_outside_window(self, database, sample_sync_transaction):
        """Test not finding transaction outside date window."""
        database.upsert_ynab_transaction(sample_sync_transaction)

        txn = database.get_ynab_transaction_by_amount_date(
            amount=sample_sync_transaction.amount,
            date=datetime(2025, 2, 1),  # Far outside window
            window_days=3,
        )

        assert txn is None


class TestAmazonItemCategoryHistory:
    """Tests for Amazon item category history methods."""

    def test_record_item_category_learning_new(self, database):
        """Test recording a new item category mapping."""
        result = database.record_item_category_learning(
            item_name="Cat Food Premium",
            category_id="cat-001",
            category_name="Pet Supplies",
            source_transaction_id="txn-123",
            source_order_id="order-456",
        )

        assert result is True
        assert database.get_item_category_history_count() == 1

    def test_record_item_category_learning_duplicate(self, database):
        """Test that duplicate mappings are rejected."""
        # First insert
        database.record_item_category_learning(
            item_name="Cat Food",
            category_id="cat-001",
            category_name="Pet Supplies",
            source_transaction_id="txn-123",
            source_order_id="order-456",
        )

        # Duplicate with same normalized name, category, and transaction
        result = database.record_item_category_learning(
            item_name="cat food",  # Different case
            category_id="cat-001",
            category_name="Pet Supplies",
            source_transaction_id="txn-123",
            source_order_id="order-456",
        )

        assert result is False
        assert database.get_item_category_history_count() == 1

    def test_record_item_same_item_different_category(self, database):
        """Test recording same item with different category."""
        database.record_item_category_learning(
            item_name="Mixed Item",
            category_id="cat-001",
            category_name="Pet Supplies",
            source_transaction_id="txn-1",
        )

        # Same item, different category
        result = database.record_item_category_learning(
            item_name="Mixed Item",
            category_id="cat-002",
            category_name="Groceries",
            source_transaction_id="txn-2",
        )

        assert result is True
        assert database.get_item_category_history_count() == 2

    def test_get_item_category_distribution(self, database):
        """Test getting category distribution for an item."""
        # Record same item with different categories
        for i in range(8):
            database.record_item_category_learning(
                item_name="Cat Food",
                category_id="cat-pet",
                category_name="Pet Supplies",
                source_transaction_id=f"txn-pet-{i}",
            )

        for i in range(2):
            database.record_item_category_learning(
                item_name="Cat Food",
                category_id="cat-grocery",
                category_name="Groceries",
                source_transaction_id=f"txn-grocery-{i}",
            )

        dist = database.get_item_category_distribution("cat food")  # Test case insensitivity

        assert len(dist) == 2
        assert dist["cat-pet"]["count"] == 8
        assert dist["cat-pet"]["percentage"] == 0.8
        assert dist["cat-grocery"]["count"] == 2
        assert dist["cat-grocery"]["percentage"] == 0.2

    def test_get_item_category_distribution_empty(self, database):
        """Test getting distribution for non-existent item."""
        dist = database.get_item_category_distribution("nonexistent item")
        assert dist == {}

    def test_get_all_item_category_mappings(self, database):
        """Test getting all mappings."""
        database.record_item_category_learning(
            item_name="Cat Food",
            category_id="cat-001",
            category_name="Pet Supplies",
            source_transaction_id="txn-1",
        )
        database.record_item_category_learning(
            item_name="Dog Food",
            category_id="cat-001",
            category_name="Pet Supplies",
            source_transaction_id="txn-2",
        )
        database.record_item_category_learning(
            item_name="Milk",
            category_id="cat-002",
            category_name="Groceries",
            source_transaction_id="txn-3",
        )

        mappings = database.get_all_item_category_mappings()

        assert len(mappings) == 3
        item_names = {m["item_name_normalized"] for m in mappings}
        assert "cat food" in item_names
        assert "dog food" in item_names
        assert "milk" in item_names

    def test_get_all_item_category_mappings_search(self, database):
        """Test searching mappings by item name."""
        database.record_item_category_learning(
            item_name="Cat Food",
            category_id="cat-001",
            category_name="Pet Supplies",
            source_transaction_id="txn-1",
        )
        database.record_item_category_learning(
            item_name="Dog Food",
            category_id="cat-001",
            category_name="Pet Supplies",
            source_transaction_id="txn-2",
        )
        database.record_item_category_learning(
            item_name="Cat Toy",
            category_id="cat-001",
            category_name="Pet Supplies",
            source_transaction_id="txn-3",
        )

        mappings = database.get_all_item_category_mappings(search_term="cat")

        assert len(mappings) == 2
        item_names = {m["item_name_normalized"] for m in mappings}
        assert "cat food" in item_names
        assert "cat toy" in item_names

    def test_get_all_item_category_mappings_category_filter(self, database):
        """Test filtering mappings by category."""
        database.record_item_category_learning(
            item_name="Cat Food",
            category_id="cat-001",
            category_name="Pet Supplies",
            source_transaction_id="txn-1",
        )
        database.record_item_category_learning(
            item_name="Milk",
            category_id="cat-002",
            category_name="Groceries",
            source_transaction_id="txn-2",
        )

        mappings = database.get_all_item_category_mappings(category_filter="Groceries")

        assert len(mappings) == 1
        assert mappings[0]["item_name_normalized"] == "milk"

    def test_get_amazon_order_items_with_prices(self, database):
        """Test getting order items with prices."""
        database.cache_amazon_order("order-1", datetime(2025, 1, 15), 100.00)
        database.upsert_amazon_order_items(
            "order-1",
            [
                {"name": "Item A", "price": 30.00, "quantity": 1},
                {"name": "Item B", "price": 70.00, "quantity": 2},
            ],
        )

        items = database.get_amazon_order_items_with_prices("order-1")

        assert len(items) == 2
        # Should be ordered by price DESC
        assert items[0]["item_name"] == "Item B"
        assert items[0]["item_price"] == 70.00
        assert items[0]["quantity"] == 2
        assert items[1]["item_name"] == "Item A"
        assert items[1]["item_price"] == 30.00

    def test_get_amazon_order_items_with_prices_empty(self, database):
        """Test getting items for non-existent order."""
        items = database.get_amazon_order_items_with_prices("nonexistent")
        assert items == []

    def test_get_unique_item_count(self, database):
        """Test counting unique items."""
        # Same item multiple times (different categories)
        database.record_item_category_learning(
            item_name="Cat Food",
            category_id="cat-001",
            category_name="Pet Supplies",
            source_transaction_id="txn-1",
        )
        database.record_item_category_learning(
            item_name="Cat Food",
            category_id="cat-002",
            category_name="Groceries",
            source_transaction_id="txn-2",
        )
        # Different item
        database.record_item_category_learning(
            item_name="Dog Food",
            category_id="cat-001",
            category_name="Pet Supplies",
            source_transaction_id="txn-3",
        )

        assert database.get_unique_item_count() == 2
        assert database.get_item_category_history_count() == 3
