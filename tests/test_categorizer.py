"""Tests for categorizer service."""

from datetime import datetime

import pytest

from src.models import CategoryList, Transaction
from src.services.categorizer import CategorizerService


class TestApplyCategory:
    """Tests for apply_category method."""

    @pytest.fixture
    def uncategorized_transaction(self, database):
        """Create an uncategorized transaction in the database."""
        txn = Transaction(
            id="txn-test-001",
            date=datetime(2024, 1, 15),
            amount=-47.82,
            payee_name="AMAZON.COM",
            payee_id="payee-001",
            account_name="Checking",
            account_id="acc-001",
            approved=True,
            category_id=None,
            category_name=None,
            sync_status="synced",
        )
        # Insert into database
        database.upsert_ynab_transaction(txn)
        return txn

    def test_apply_category_sets_single_category(
        self, categorizer_service, uncategorized_transaction
    ):
        """Test that apply_category sets a single category, not a split."""
        txn = uncategorized_transaction

        # Apply category
        result = categorizer_service.apply_category(
            transaction=txn,
            category_id="cat-001",
            category_name="Electronics",
        )

        # Verify single category is set
        assert result.category_id == "cat-001"
        assert result.category_name == "Electronics"

    def test_apply_category_does_not_create_splits(
        self, categorizer_service, uncategorized_transaction
    ):
        """Test that apply_category does NOT create split transactions."""
        txn = uncategorized_transaction

        # Apply category
        result = categorizer_service.apply_category(
            transaction=txn,
            category_id="cat-001",
            category_name="Electronics",
        )

        # Verify no split is created
        assert result.is_split is False
        assert len(result.subtransactions) == 0

    def test_apply_category_marks_pending_push(
        self, categorizer_service, uncategorized_transaction, database
    ):
        """Test that apply_category marks transaction as pending_push in DB."""
        txn = uncategorized_transaction

        # Apply category
        categorizer_service.apply_category(
            transaction=txn,
            category_id="cat-001",
            category_name="Electronics",
        )

        # Verify pending_changes table has the change (delta-based design)
        pending = database.get_pending_change(txn.id)
        assert pending is not None
        assert pending["new_category_id"] == "cat-001"
        assert pending["new_category_name"] == "Electronics"
        assert pending["original_category_id"] is None  # Was uncategorized
        assert pending["original_category_name"] is None

        # Note: ynab_transactions is NOT modified until push (delta design)

    def test_apply_category_records_history(
        self, categorizer_service, uncategorized_transaction, database
    ):
        """Test that apply_category records categorization in history."""
        txn = uncategorized_transaction

        # Apply category
        categorizer_service.apply_category(
            transaction=txn,
            category_id="cat-001",
            category_name="Electronics",
        )

        # Verify history was recorded
        history = database.get_payee_category_distribution(txn.payee_name)
        assert len(history) > 0
        assert "Electronics" in history

    def test_apply_category_can_recategorize(self, categorizer_service, database):
        """Test that apply_category can change an existing category."""
        # Create a transaction with existing category
        txn = Transaction(
            id="txn-test-002",
            date=datetime(2024, 1, 15),
            amount=-50.00,
            payee_name="COSTCO",
            category_id="cat-006",
            category_name="Groceries",
            sync_status="synced",
        )
        database.upsert_ynab_transaction(txn)

        # Apply new category
        result = categorizer_service.apply_category(
            transaction=txn,
            category_id="cat-003",
            category_name="Home & Garden",
        )

        # Verify in-memory category changed
        assert result.category_id == "cat-003"
        assert result.category_name == "Home & Garden"

        # Verify no splits created during recategorization
        assert result.is_split is False
        assert len(result.subtransactions) == 0

        # Verify pending_changes has the new category (delta-based design)
        pending = database.get_pending_change(txn.id)
        assert pending is not None
        assert pending["new_category_name"] == "Home & Garden"
        assert pending["original_category_name"] == "Groceries"  # Preserved original

        # Note: ynab_transactions is NOT modified until push (delta design)

    def test_apply_category_persists_across_reload(self, database, sample_config, mock_ynab_client):
        """Test that pending category and approval changes survive app restart.

        This is a regression test for the bug where pending changes were saved
        to the pending_changes table but not merged when loading transactions.
        """
        # Create uncategorized AND unapproved transaction
        txn = Transaction(
            id="txn-persist-001",
            date=datetime(2024, 1, 15),
            amount=-50.00,
            payee_name="TEST STORE",
            category_id=None,
            category_name=None,
            approved=False,  # Starts unapproved
            sync_status="synced",
        )
        database.upsert_ynab_transaction(txn)

        # Create categorizer and apply category
        categorizer = CategorizerService(
            config=sample_config,
            ynab_client=mock_ynab_client,
            db=database,
        )
        categorizer.apply_category(txn, "cat-001", "Electronics")

        # Simulate app restart: NEW categorizer instance (fresh memory)
        categorizer2 = CategorizerService(
            config=sample_config,
            ynab_client=mock_ynab_client,
            db=database,
        )

        # Load transactions from DB (simulating TUI startup)
        batch = categorizer2.get_transactions(filter_mode="all")
        reloaded = next((t for t in batch.transactions if t.id == "txn-persist-001"), None)

        # Verify pending change persisted (merged from pending_changes table)
        assert reloaded is not None
        assert reloaded.sync_status == "pending_push"
        assert reloaded.category_id == "cat-001"
        assert reloaded.category_name == "Electronics"
        assert reloaded.approved is True  # Auto-approved when categorized


class TestApplyCategoryDoesNotSplit:
    """Additional tests specifically to verify no accidental splits are created."""

    def test_amazon_transaction_no_split_on_categorize(self, categorizer_service, database):
        """Test that Amazon transactions with items don't get split when categorized."""
        # Create Amazon transaction with multiple items
        txn = Transaction(
            id="txn-amazon-001",
            date=datetime(2024, 1, 15),
            amount=-100.00,
            payee_name="AMAZON.COM",
            is_amazon=True,
            amazon_items=["USB Cable", "Phone Case", "Screen Protector"],
            amazon_order_id="order-123",
            category_id=None,
            category_name=None,
        )
        database.upsert_ynab_transaction(txn)

        # Apply single category (not using split feature)
        result = categorizer_service.apply_category(
            transaction=txn,
            category_id="cat-001",
            category_name="Electronics",
        )

        # Must NOT create splits - single category for whole transaction
        assert result.is_split is False
        assert len(result.subtransactions) == 0
        assert result.category_id == "cat-001"
        assert result.category_name == "Electronics"

    def test_multiple_categorizations_no_splits(self, categorizer_service, database):
        """Test that categorizing multiple times doesn't create splits."""
        txn = Transaction(
            id="txn-multi-001",
            date=datetime(2024, 1, 15),
            amount=-75.00,
            payee_name="TARGET",
            category_id=None,
            category_name=None,
        )
        database.upsert_ynab_transaction(txn)

        # Categorize multiple times
        for cat_id, cat_name in [
            ("cat-001", "Electronics"),
            ("cat-006", "Groceries"),
            ("cat-003", "Home & Garden"),
        ]:
            result = categorizer_service.apply_category(
                transaction=txn,
                category_id=cat_id,
                category_name=cat_name,
            )
            # Each time, should remain a single category, not accumulate splits
            assert result.is_split is False
            assert len(result.subtransactions) == 0

        # Final category should be the last one applied (in pending_changes)
        pending = database.get_pending_change(txn.id)
        assert pending is not None
        assert pending["new_values"]["category_name"] == "Home & Garden"  # Latest wins
        assert pending["original_values"]["category_id"] is None  # Original was uncategorized


class TestApplySplitCategories:
    """Tests for apply_split_categories method."""

    @pytest.fixture
    def amazon_transaction(self, database):
        """Create an Amazon transaction for splitting."""
        txn = Transaction(
            id="txn-split-test-001",
            date=datetime(2024, 1, 15),
            amount=-100.00,
            payee_name="AMAZON.COM",
            payee_id="payee-amazon",
            account_name="Checking",
            account_id="acc-001",
            approved=False,  # Starts unapproved
            is_amazon=True,
            amazon_order_id="order-split-123",
            amazon_items=["USB Cable", "Phone Case"],
            category_id=None,
            category_name=None,
            sync_status="synced",
        )
        database.upsert_ynab_transaction(txn)
        return txn

    def test_apply_split_sets_category_name_with_count(
        self, categorizer_service, amazon_transaction
    ):
        """Test that split category name shows count like '[Split 2]'."""
        splits = [
            {
                "category_id": "cat-001",
                "category_name": "Electronics",
                "amount": -50.00,
                "memo": "USB Cable",
            },
            {
                "category_id": "cat-002",
                "category_name": "Accessories",
                "amount": -50.00,
                "memo": "Phone Case",
            },
        ]

        result = categorizer_service.apply_split_categories(
            transaction=amazon_transaction,
            splits=splits,
        )

        # Category name should show split count
        assert result.category_name == "[Split 2]"
        assert result.is_split is True

    def test_apply_split_marks_approved(self, categorizer_service, amazon_transaction):
        """Test that splitting auto-approves the transaction (same as regular categorize)."""
        # Transaction starts unapproved
        assert amazon_transaction.approved is False

        splits = [
            {
                "category_id": "cat-001",
                "category_name": "Electronics",
                "amount": -50.00,
                "memo": "USB Cable",
            },
            {
                "category_id": "cat-002",
                "category_name": "Accessories",
                "amount": -50.00,
                "memo": "Phone Case",
            },
        ]

        result = categorizer_service.apply_split_categories(
            transaction=amazon_transaction,
            splits=splits,
        )

        # Should be approved after split
        assert result.approved is True

    def test_apply_split_marks_pending_push(
        self, categorizer_service, amazon_transaction, database
    ):
        """Test that split marks transaction as pending_push."""
        splits = [
            {
                "category_id": "cat-001",
                "category_name": "Electronics",
                "amount": -50.00,
                "memo": "USB Cable",
            },
            {
                "category_id": "cat-002",
                "category_name": "Accessories",
                "amount": -50.00,
                "memo": "Phone Case",
            },
        ]

        result = categorizer_service.apply_split_categories(
            transaction=amazon_transaction,
            splits=splits,
        )

        assert result.sync_status == "pending_push"

        # Verify pending_changes table has the split record
        pending = database.get_pending_change(amazon_transaction.id)
        assert pending is not None
        assert pending["change_type"] == "split"
        assert pending["new_category_name"] == "[Split 2]"
        assert pending["new_approved"] == 1  # SQLite stores booleans as 0/1

    def test_apply_split_stores_splits_in_database(
        self, categorizer_service, amazon_transaction, database
    ):
        """Test that individual splits are stored in pending_splits table."""
        splits = [
            {
                "category_id": "cat-001",
                "category_name": "Electronics",
                "amount": -60.00,
                "memo": "USB Cable",
            },
            {
                "category_id": "cat-002",
                "category_name": "Accessories",
                "amount": -40.00,
                "memo": "Phone Case",
            },
        ]

        categorizer_service.apply_split_categories(
            transaction=amazon_transaction,
            splits=splits,
        )

        # Verify pending_splits table has the individual splits
        pending_splits = database.get_pending_splits(amazon_transaction.id)
        assert len(pending_splits) == 2

        # Check first split
        assert pending_splits[0]["category_id"] == "cat-001"
        assert pending_splits[0]["category_name"] == "Electronics"
        assert pending_splits[0]["amount"] == -60.00
        assert pending_splits[0]["memo"] == "USB Cable"

        # Check second split
        assert pending_splits[1]["category_id"] == "cat-002"
        assert pending_splits[1]["category_name"] == "Accessories"
        assert pending_splits[1]["amount"] == -40.00
        assert pending_splits[1]["memo"] == "Phone Case"

    def test_apply_split_persists_across_reload(self, database, sample_config, mock_ynab_client):
        """Test that pending split changes survive app restart."""
        # Create Amazon transaction
        txn = Transaction(
            id="txn-split-persist-001",
            date=datetime(2024, 1, 15),
            amount=-100.00,
            payee_name="AMAZON.COM",
            is_amazon=True,
            amazon_order_id="order-persist-123",
            category_id=None,
            category_name=None,
            approved=False,
            sync_status="synced",
        )
        database.upsert_ynab_transaction(txn)

        # Create categorizer and apply split
        categorizer = CategorizerService(
            config=sample_config,
            ynab_client=mock_ynab_client,
            db=database,
        )
        splits = [
            {
                "category_id": "cat-001",
                "category_name": "Electronics",
                "amount": -60.00,
                "memo": "Item 1",
            },
            {
                "category_id": "cat-002",
                "category_name": "Accessories",
                "amount": -40.00,
                "memo": "Item 2",
            },
        ]
        categorizer.apply_split_categories(txn, splits)

        # Simulate app restart: NEW categorizer instance
        categorizer2 = CategorizerService(
            config=sample_config,
            ynab_client=mock_ynab_client,
            db=database,
        )

        # Load transactions from DB
        batch = categorizer2.get_transactions(filter_mode="all")
        reloaded = next((t for t in batch.transactions if t.id == "txn-split-persist-001"), None)

        # Verify pending split persisted
        assert reloaded is not None
        assert reloaded.sync_status == "pending_push"
        assert reloaded.category_name == "[Split 2]"
        assert reloaded.approved is True

        # Verify splits still in database
        pending_splits = database.get_pending_splits(txn.id)
        assert len(pending_splits) == 2

    def test_apply_split_preserves_original_for_undo(self, categorizer_service, database):
        """Test that original values are preserved for undo."""
        # Create transaction with existing category
        txn = Transaction(
            id="txn-split-undo-001",
            date=datetime(2024, 1, 15),
            amount=-100.00,
            payee_name="AMAZON.COM",
            is_amazon=True,
            category_id="cat-original",
            category_name="Original Category",
            approved=True,
            sync_status="synced",
        )
        database.upsert_ynab_transaction(txn)

        # Apply split
        splits = [
            {
                "category_id": "cat-001",
                "category_name": "Electronics",
                "amount": -50.00,
                "memo": "Item",
            },
            {
                "category_id": "cat-002",
                "category_name": "Accessories",
                "amount": -50.00,
                "memo": "Item2",
            },
        ]
        categorizer_service.apply_split_categories(txn, splits)

        # Verify original values preserved in pending_changes
        pending = database.get_pending_change(txn.id)
        assert pending["original_category_id"] == "cat-original"
        assert pending["original_category_name"] == "Original Category"
        assert pending["original_approved"] == 1  # SQLite stores booleans as 0/1

    def test_apply_split_with_three_items(self, categorizer_service, database):
        """Test split with 3 items shows correct count."""
        txn = Transaction(
            id="txn-split-three-001",
            date=datetime(2024, 1, 15),
            amount=-150.00,
            payee_name="AMAZON.COM",
            is_amazon=True,
            category_id=None,
            category_name=None,
            sync_status="synced",
        )
        database.upsert_ynab_transaction(txn)

        splits = [
            {
                "category_id": "cat-001",
                "category_name": "Electronics",
                "amount": -50.00,
                "memo": "Item1",
            },
            {
                "category_id": "cat-002",
                "category_name": "Accessories",
                "amount": -50.00,
                "memo": "Item2",
            },
            {"category_id": "cat-003", "category_name": "Home", "amount": -50.00, "memo": "Item3"},
        ]

        result = categorizer_service.apply_split_categories(txn, splits)

        assert result.category_name == "[Split 3]"
        assert result.is_split is True


class TestFormatPayeeHistorySummary:
    """Tests for _format_payee_history_summary static method."""

    def test_format_single_category(self):
        """Test formatting with a single category."""
        history = {
            "Groceries": {"count": 10, "percentage": 1.0},
        }
        result = CategorizerService._format_payee_history_summary(history)
        assert result == "100% Groceries"

    def test_format_two_categories(self):
        """Test formatting with two categories shows both."""
        history = {
            "Groceries": {"count": 8, "percentage": 0.8},
            "Home": {"count": 2, "percentage": 0.2},
        }
        result = CategorizerService._format_payee_history_summary(history)
        assert "80% Groceries" in result
        assert "20% Home" in result

    def test_format_three_categories_shows_top_two(self):
        """Test that only top 2 categories are shown."""
        history = {
            "Groceries": {"count": 5, "percentage": 0.5},
            "Home": {"count": 3, "percentage": 0.3},
            "Electronics": {"count": 2, "percentage": 0.2},
        }
        result = CategorizerService._format_payee_history_summary(history)
        assert "50% Groceries" in result
        assert "30% Home" in result
        assert "Electronics" not in result


class TestRefreshCategories:
    """Tests for refresh_categories method."""

    def test_refresh_categories_reloads_from_db(self, categorizer_service, database):
        """Test that refresh_categories reloads from database."""
        # Add some categories to the database using upsert_category
        database.upsert_category(
            category_id="cat-new-001",
            name="New Category",
            group_id="group-001",
            group_name="Test Group",
        )

        # Refresh and check
        result = categorizer_service.refresh_categories()
        assert isinstance(result, CategoryList)

    def test_refresh_clears_cache(self, categorizer_service, database):
        """Test that refresh clears the cached categories."""
        # Access categories to populate cache
        _ = categorizer_service.categories

        # Add more categories
        database.upsert_category(
            category_id="cat-refresh-001",
            name="Refresh Test",
            group_id="group-001",
            group_name="Test Group",
        )

        # Refresh should get new data
        result = categorizer_service.refresh_categories()
        all_cats = [cat for group in result.groups for cat in group.categories]
        assert any(c.id == "cat-refresh-001" for c in all_cats)


class TestGetTransactionsFilters:
    """Tests for get_transactions with filters."""

    @pytest.fixture
    def transactions_for_filtering(self, database):
        """Create transactions with various categories and payees."""
        transactions = [
            Transaction(
                id="txn-filter-001",
                date=datetime(2024, 1, 15),
                amount=-50.00,
                payee_name="COSTCO",
                category_id="cat-groceries",
                category_name="Groceries",
                approved=True,
            ),
            Transaction(
                id="txn-filter-002",
                date=datetime(2024, 1, 16),
                amount=-100.00,
                payee_name="AMAZON.COM",
                category_id="cat-electronics",
                category_name="Electronics",
                approved=True,
            ),
            Transaction(
                id="txn-filter-003",
                date=datetime(2024, 1, 17),
                amount=-25.00,
                payee_name="COSTCO",
                category_id="cat-groceries",
                category_name="Groceries",
                approved=False,
            ),
        ]
        for txn in transactions:
            database.upsert_ynab_transaction(txn)
        return transactions

    def test_filter_by_category_id(self, categorizer_service, transactions_for_filtering):
        """Test filtering transactions by category ID."""
        batch = categorizer_service.get_transactions(category_id="cat-groceries")
        ids = [t.id for t in batch.transactions]
        assert "txn-filter-001" in ids
        assert "txn-filter-003" in ids
        assert "txn-filter-002" not in ids

    def test_filter_by_payee_name(self, categorizer_service, transactions_for_filtering):
        """Test filtering transactions by payee name."""
        batch = categorizer_service.get_transactions(payee_name="COSTCO")
        ids = [t.id for t in batch.transactions]
        assert "txn-filter-001" in ids
        assert "txn-filter-003" in ids
        assert "txn-filter-002" not in ids


class TestUndoCategory:
    """Tests for undo_category method."""

    @pytest.fixture
    def categorized_transaction(self, categorizer_service, database):
        """Create a transaction with a pending category change."""
        txn = Transaction(
            id="txn-undo-001",
            date=datetime(2024, 1, 15),
            amount=-50.00,
            payee_name="TEST STORE",
            category_id=None,
            category_name=None,
            approved=False,
            sync_status="synced",
        )
        database.upsert_ynab_transaction(txn)
        categorizer_service.apply_category(txn, "cat-001", "Electronics")
        return txn

    def test_undo_restores_original_category(self, categorizer_service, categorized_transaction):
        """Test that undo restores the original category."""
        result = categorizer_service.undo_category(categorized_transaction)
        assert result.category_id is None
        assert result.category_name is None
        assert result.sync_status == "synced"

    def test_undo_clears_pending_change(
        self, categorizer_service, categorized_transaction, database
    ):
        """Test that undo removes the pending change from database."""
        categorizer_service.undo_category(categorized_transaction)
        pending = database.get_pending_change(categorized_transaction.id)
        assert pending is None

    def test_undo_raises_if_no_pending_change(self, categorizer_service, database):
        """Test that undo raises error if no pending change exists."""
        txn = Transaction(
            id="txn-no-pending",
            date=datetime(2024, 1, 15),
            amount=-50.00,
            payee_name="TEST STORE",
        )
        database.upsert_ynab_transaction(txn)

        with pytest.raises(ValueError, match="No pending change"):
            categorizer_service.undo_category(txn)

    def test_undo_split_clears_pending_splits(self, categorizer_service, database):
        """Test that undoing a split also clears pending_splits."""
        txn = Transaction(
            id="txn-undo-split-001",
            date=datetime(2024, 1, 15),
            amount=-100.00,
            payee_name="AMAZON.COM",
            category_id=None,
            category_name=None,
            sync_status="synced",
        )
        database.upsert_ynab_transaction(txn)

        splits = [
            {"category_id": "cat-001", "category_name": "Electronics", "amount": -50.00},
            {"category_id": "cat-002", "category_name": "Home", "amount": -50.00},
        ]
        categorizer_service.apply_split_categories(txn, splits)

        # Verify splits exist
        assert len(database.get_pending_splits(txn.id)) == 2

        # Undo
        categorizer_service.undo_category(txn)

        # Verify splits are cleared
        assert len(database.get_pending_splits(txn.id)) == 0


class TestApproveTransaction:
    """Tests for approve_transaction method."""

    @pytest.fixture
    def unapproved_transaction(self, database):
        """Create an unapproved transaction."""
        txn = Transaction(
            id="txn-approve-001",
            date=datetime(2024, 1, 15),
            amount=-50.00,
            payee_name="TEST STORE",
            category_id="cat-001",
            category_name="Electronics",
            approved=False,
            sync_status="synced",
        )
        database.upsert_ynab_transaction(txn)
        return txn

    def test_approve_sets_approved_flag(self, categorizer_service, unapproved_transaction):
        """Test that approve_transaction sets approved to True."""
        result = categorizer_service.approve_transaction(unapproved_transaction)
        assert result.approved is True
        assert result.sync_status == "pending_push"

    def test_approve_creates_pending_change(
        self, categorizer_service, unapproved_transaction, database
    ):
        """Test that approve creates a pending change record."""
        categorizer_service.approve_transaction(unapproved_transaction)
        pending = database.get_pending_change(unapproved_transaction.id)
        assert pending is not None
        assert pending["change_type"] == "update"
        assert pending["new_values"]["approved"] is True

    def test_approve_already_approved_is_noop(self, categorizer_service, database):
        """Test that approving an already approved transaction is a no-op."""
        txn = Transaction(
            id="txn-already-approved",
            date=datetime(2024, 1, 15),
            amount=-50.00,
            payee_name="TEST STORE",
            approved=True,
            sync_status="synced",
        )
        database.upsert_ynab_transaction(txn)

        result = categorizer_service.approve_transaction(txn)

        # Should return unchanged
        assert result.sync_status == "synced"
        # No pending change created
        assert database.get_pending_change(txn.id) is None


class TestApplyMemo:
    """Tests for apply_memo method."""

    @pytest.fixture
    def transaction_with_memo(self, database):
        """Create a transaction with an existing memo."""
        txn = Transaction(
            id="txn-memo-test-001",
            date=datetime(2024, 1, 15),
            amount=-50.00,
            payee_name="TEST STORE",
            memo="Original memo",
            sync_status="synced",
        )
        database.upsert_ynab_transaction(txn)
        return txn

    @pytest.fixture
    def transaction_without_memo(self, database):
        """Create a transaction without a memo."""
        txn = Transaction(
            id="txn-no-memo-001",
            date=datetime(2024, 1, 15),
            amount=-50.00,
            payee_name="TEST STORE",
            memo=None,
            sync_status="synced",
        )
        database.upsert_ynab_transaction(txn)
        return txn

    def test_apply_memo_sets_memo(self, categorizer_service, transaction_without_memo):
        """Test that apply_memo sets the memo field."""
        result = categorizer_service.apply_memo(transaction_without_memo, "New memo text")
        assert result.memo == "New memo text"

    def test_apply_memo_marks_pending_push(self, categorizer_service, transaction_without_memo):
        """Test that apply_memo marks transaction as pending_push."""
        result = categorizer_service.apply_memo(transaction_without_memo, "New memo")
        assert result.sync_status == "pending_push"

    def test_apply_memo_creates_pending_change(
        self, categorizer_service, transaction_without_memo, database
    ):
        """Test that apply_memo creates a pending change record."""
        categorizer_service.apply_memo(transaction_without_memo, "New memo")
        pending = database.get_pending_change(transaction_without_memo.id)
        assert pending is not None
        assert pending["new_values"]["memo"] == "New memo"
        assert pending["original_values"]["memo"] is None

    def test_apply_memo_preserves_original(
        self, categorizer_service, transaction_with_memo, database
    ):
        """Test that apply_memo preserves original memo for undo."""
        categorizer_service.apply_memo(transaction_with_memo, "Updated memo")
        pending = database.get_pending_change(transaction_with_memo.id)
        assert pending["original_values"]["memo"] == "Original memo"

    def test_apply_memo_can_clear_memo(self, categorizer_service, transaction_with_memo):
        """Test that empty string clears memo."""
        result = categorizer_service.apply_memo(transaction_with_memo, "")
        assert result.memo == ""

    def test_apply_memo_combined_with_category(
        self, categorizer_service, transaction_without_memo, database
    ):
        """Test that memo change can be combined with category change."""
        # First apply category
        categorizer_service.apply_category(transaction_without_memo, "cat-001", "Groceries")
        # Then apply memo
        categorizer_service.apply_memo(transaction_without_memo, "Weekly shopping")

        pending = database.get_pending_change(transaction_without_memo.id)
        # Should have both changes merged
        assert pending["new_values"]["category_id"] == "cat-001"
        assert pending["new_values"]["memo"] == "Weekly shopping"

    def test_undo_memo_restores_original(
        self, categorizer_service, transaction_with_memo, database
    ):
        """Test that undo restores original memo."""
        categorizer_service.apply_memo(transaction_with_memo, "Changed memo")
        categorizer_service.undo_category(transaction_with_memo)
        assert transaction_with_memo.memo == "Original memo"
        assert transaction_with_memo.sync_status == "synced"


class TestGetAmazonOrderItems:
    """Tests for get_amazon_order_items_with_prices method."""

    def test_get_amazon_order_items(self, categorizer_service, database, add_order_to_db):
        """Test getting Amazon order items with prices."""
        # Add an order with items
        add_order_to_db("order-items-001", datetime(2024, 1, 15), 50.00, ["Item A", "Item B"])

        # Get items
        items = categorizer_service.get_amazon_order_items_with_prices("order-items-001")
        assert len(items) == 2
        names = [i["item_name"] for i in items]
        assert "Item A" in names
        assert "Item B" in names


class TestGetPendingSplits:
    """Tests for get_pending_splits method."""

    def test_get_pending_splits(self, categorizer_service, database):
        """Test getting pending splits for a transaction."""
        txn = Transaction(
            id="txn-pending-splits-001",
            date=datetime(2024, 1, 15),
            amount=-100.00,
            payee_name="TEST STORE",
            sync_status="synced",
        )
        database.upsert_ynab_transaction(txn)

        splits = [
            {
                "category_id": "cat-001",
                "category_name": "Electronics",
                "amount": -60.00,
                "memo": "Test",
            },
            {"category_id": "cat-002", "category_name": "Home", "amount": -40.00},
        ]
        categorizer_service.apply_split_categories(txn, splits)

        # Get pending splits via service method
        result = categorizer_service.get_pending_splits(txn.id)
        assert len(result) == 2


class TestBudgetMethods:
    """Tests for budget-related methods."""

    def test_get_budget_name(self, categorizer_service):
        """Test getting budget name."""
        name = categorizer_service.get_budget_name()
        assert name == "Mock Budget"

    def test_get_budget_name_with_id(self, categorizer_service):
        """Test getting budget name by specific ID."""
        name = categorizer_service.get_budget_name("mock-budget-id-2")
        assert name == "Second Mock Budget"
