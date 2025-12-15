"""Tests for data models."""

from datetime import datetime

from src.models import (
    AmazonOrder,
    Category,
    CategoryGroup,
    OrderItem,
    OrderMatch,
    Transaction,
    TransactionBatch,
)


class TestTransaction:
    """Tests for Transaction model."""

    def test_basic_creation(self, sample_transaction):
        """Test basic transaction creation."""
        assert sample_transaction.id == "txn-001"
        assert sample_transaction.date == datetime(2024, 1, 15)
        assert sample_transaction.amount == -47.82
        assert sample_transaction.payee_name == "AMAZON.COM"

    def test_is_uncategorized(self):
        """Test is_uncategorized property."""
        txn = Transaction(
            id="txn-001",
            date=datetime(2024, 1, 15),
            amount=-47.82,
            payee_name="AMAZON",
        )
        assert txn.is_uncategorized is True

        txn.category_id = "cat-001"
        txn.category_name = "Electronics"
        assert txn.is_uncategorized is False

    def test_is_unapproved(self):
        """Test is_unapproved property."""
        txn = Transaction(
            id="txn-001",
            date=datetime(2024, 1, 15),
            amount=-47.82,
            payee_name="AMAZON",
        )
        assert txn.is_unapproved is True

        txn.approved = True
        assert txn.is_unapproved is False

    def test_display_amount_negative(self):
        """Test display_amount for outflows."""
        txn = Transaction(
            id="txn-001",
            date=datetime(2024, 1, 15),
            amount=-47.82,
            payee_name="AMAZON",
        )
        assert txn.display_amount == "-$47.82"

    def test_display_amount_positive(self):
        """Test display_amount for inflows."""
        txn = Transaction(
            id="txn-001",
            date=datetime(2024, 1, 15),
            amount=100.50,
            payee_name="Refund",
        )
        assert txn.display_amount == "$100.50"

    def test_display_amount_large(self):
        """Test display_amount with thousands separator."""
        txn = Transaction(
            id="txn-001",
            date=datetime(2024, 1, 15),
            amount=-1234.56,
            payee_name="Big Purchase",
        )
        assert txn.display_amount == "-$1,234.56"

    def test_display_date(self, sample_transaction):
        """Test display_date formatting."""
        assert sample_transaction.display_date == "2024-01-15"

    def test_enrichment_summary_with_amazon_items(self, sample_amazon_transaction):
        """Test enrichment_summary with Amazon items."""
        summary = sample_amazon_transaction.enrichment_summary
        assert "USB-C Cable" in summary
        assert "Phone Case" in summary

    def test_enrichment_summary_with_many_items(self):
        """Test enrichment_summary truncates many items."""
        txn = Transaction(
            id="txn-001",
            date=datetime(2024, 1, 15),
            amount=-100.00,
            payee_name="AMAZON",
        )
        txn.is_amazon = True
        txn.amazon_items = ["Item 1", "Item 2", "Item 3", "Item 4", "Item 5"]

        summary = txn.enrichment_summary
        assert "+2 more" in summary

    def test_enrichment_summary_with_history(self):
        """Test enrichment_summary with payee history."""
        txn = Transaction(
            id="txn-001",
            date=datetime(2024, 1, 15),
            amount=-100.00,
            payee_name="COSTCO",
        )
        txn.payee_history_summary = "85% Groceries"

        summary = txn.enrichment_summary
        assert "Historical: 85% Groceries" in summary

    def test_enrichment_summary_empty(self):
        """Test enrichment_summary when no data."""
        txn = Transaction(
            id="txn-001",
            date=datetime(2024, 1, 15),
            amount=-100.00,
            payee_name="Unknown",
        )
        assert txn.enrichment_summary == ""


class TestTransactionBatch:
    """Tests for TransactionBatch model."""

    def test_empty_batch(self):
        """Test empty batch properties."""
        batch = TransactionBatch()
        assert batch.total_count == 0
        assert batch.amazon_count == 0
        assert batch.other_count == 0

    def test_counts(self, sample_transactions):
        """Test batch count properties."""
        # Mark some as Amazon
        sample_transactions[0].is_amazon = True  # AMAZON.COM
        sample_transactions[3].is_amazon = True  # AMZN MKTPLACE

        batch = TransactionBatch(transactions=sample_transactions)

        assert batch.total_count == 4
        assert batch.amazon_count == 2
        assert batch.other_count == 2

    def test_filter_amazon(self, sample_transactions):
        """Test filtering Amazon transactions."""
        sample_transactions[0].is_amazon = True
        sample_transactions[3].is_amazon = True

        batch = TransactionBatch(transactions=sample_transactions)
        amazon = batch.filter_amazon()

        assert len(amazon) == 2
        assert all(t.is_amazon for t in amazon)

    def test_filter_other(self, sample_transactions):
        """Test filtering non-Amazon transactions."""
        sample_transactions[0].is_amazon = True
        sample_transactions[3].is_amazon = True

        batch = TransactionBatch(transactions=sample_transactions)
        other = batch.filter_other()

        assert len(other) == 2
        assert all(not t.is_amazon for t in other)


class TestCategory:
    """Tests for Category model."""

    def test_basic_creation(self, sample_category):
        """Test basic category creation."""
        assert sample_category.id == "cat-001"
        assert sample_category.name == "Electronics"
        assert sample_category.group_name == "Shopping"

    def test_full_name(self, sample_category):
        """Test full_name property."""
        assert sample_category.full_name == "Shopping: Electronics"

    def test_default_values(self):
        """Test default values."""
        cat = Category(
            id="cat-001",
            name="Test",
            group_id="grp-001",
            group_name="Test Group",
        )
        assert cat.hidden is False
        assert cat.deleted is False
        assert cat.budgeted is None


class TestCategoryGroup:
    """Tests for CategoryGroup model."""

    def test_available_categories(self):
        """Test filtering available categories."""
        group = CategoryGroup(
            id="grp-001",
            name="Shopping",
            categories=[
                Category(id="cat-1", name="Electronics", group_id="grp-001", group_name="Shopping"),
                Category(
                    id="cat-2",
                    name="Clothing",
                    group_id="grp-001",
                    group_name="Shopping",
                    hidden=True,
                ),
                Category(
                    id="cat-3",
                    name="Deleted",
                    group_id="grp-001",
                    group_name="Shopping",
                    deleted=True,
                ),
            ],
        )

        available = group.available_categories
        assert len(available) == 1
        assert available[0].name == "Electronics"


class TestCategoryList:
    """Tests for CategoryList model."""

    def test_all_categories(self, sample_category_list):
        """Test getting all categories."""
        all_cats = sample_category_list.all_categories()  # Method, not property
        assert len(all_cats) == 8  # 3 + 2 + 3

    def test_available_categories(self, sample_category_list):
        """Test getting available categories."""
        available = sample_category_list.available_categories()
        assert len(available) == 8

    def test_find_by_name_exact(self, sample_category_list):
        """Test finding category by exact name."""
        cat = sample_category_list.find_by_name("Electronics")
        assert cat is not None
        assert cat.name == "Electronics"

    def test_find_by_name_case_insensitive(self, sample_category_list):
        """Test finding category is case-insensitive."""
        cat = sample_category_list.find_by_name("electronics")
        assert cat is not None
        assert cat.name == "Electronics"

    def test_find_by_name_not_found(self, sample_category_list):
        """Test finding non-existent category."""
        cat = sample_category_list.find_by_name("NonExistent")
        assert cat is None

    def test_find_by_id(self, sample_category_list):
        """Test finding category by ID."""
        cat = sample_category_list.find_by_id("cat-001")
        assert cat is not None
        assert cat.name == "Electronics"

    def test_find_by_id_not_found(self, sample_category_list):
        """Test finding non-existent category by ID."""
        cat = sample_category_list.find_by_id("cat-999")
        assert cat is None

    def test_search_partial_match(self, sample_category_list):
        """Test searching with partial match."""
        results = sample_category_list.search("Elect")
        assert len(results) >= 1
        assert any(c.name == "Electronics" for c in results)

    def test_search_case_insensitive(self, sample_category_list):
        """Test search is case-insensitive."""
        results = sample_category_list.search("groceries")
        assert len(results) == 1
        assert results[0].name == "Groceries"

    def test_search_no_results(self, sample_category_list):
        """Test search with no results."""
        results = sample_category_list.search("ZZZZZ")
        assert results == []


class TestAmazonOrder:
    """Tests for AmazonOrder model."""

    def test_basic_creation(self, sample_amazon_order):
        """Test basic order creation."""
        assert sample_amazon_order.order_id == "order-123"
        assert sample_amazon_order.total == 47.82
        assert len(sample_amazon_order.items) == 2

    def test_item_names(self, sample_amazon_order):
        """Test item_names property."""
        names = sample_amazon_order.item_names
        assert names == ["USB-C Cable", "Phone Case"]

    def test_item_names_empty(self):
        """Test item_names with no items."""
        order = AmazonOrder(
            order_id="order-123",
            order_date=datetime(2024, 1, 15),
            total=0.0,
            items=[],
        )
        assert order.item_names == []

    def test_display_items_short(self):
        """Test display_items with few items."""
        order = AmazonOrder(
            order_id="order-123",
            order_date=datetime(2024, 1, 15),
            total=50.00,
            items=[OrderItem(name="Item 1"), OrderItem(name="Item 2")],
        )
        summary = order.display_items
        assert "Item 1" in summary
        assert "Item 2" in summary

    def test_display_items_long(self):
        """Test display_items truncates many items."""
        order = AmazonOrder(
            order_id="order-123",
            order_date=datetime(2024, 1, 15),
            total=100.00,
            items=[OrderItem(name=f"Item {i}") for i in range(10)],
        )
        summary = order.display_items
        assert "+7 more" in summary


class TestOrderMatch:
    """Tests for OrderMatch model."""

    def test_basic_creation(self, sample_amazon_order):
        """Test basic match creation."""
        match = OrderMatch(
            transaction_id="txn-001",
            order=sample_amazon_order,
            amount_diff=0.0,
            days_diff=1,
        )
        assert match.transaction_id == "txn-001"
        assert match.amount_diff == 0.0
        assert match.days_diff == 1


# =============================================================================
# Sync-related model tests
# =============================================================================


class TestSubTransaction:
    """Tests for SubTransaction model."""

    def test_basic_creation(self):
        """Test basic subtransaction creation."""
        from src.models import SubTransaction

        sub = SubTransaction(
            id="sub-001",
            transaction_id="txn-001",
            amount=-25.00,
        )
        assert sub.id == "sub-001"
        assert sub.transaction_id == "txn-001"
        assert sub.amount == -25.00

    def test_optional_fields(self):
        """Test optional fields default to None."""
        from src.models import SubTransaction

        sub = SubTransaction(
            id="sub-001",
            transaction_id="txn-001",
            amount=-50.00,
        )
        assert sub.payee_id is None
        assert sub.payee_name is None
        assert sub.memo is None
        assert sub.category_id is None
        assert sub.category_name is None

    def test_full_subtransaction(self):
        """Test subtransaction with all fields."""
        from src.models import SubTransaction

        sub = SubTransaction(
            id="sub-001",
            transaction_id="txn-001",
            amount=-75.00,
            payee_id="payee-001",
            payee_name="COSTCO",
            memo="Groceries portion",
            category_id="cat-006",
            category_name="Groceries",
        )
        assert sub.payee_name == "COSTCO"
        assert sub.category_name == "Groceries"

    def test_is_uncategorized(self):
        """Test is_uncategorized property."""
        from src.models import SubTransaction

        # Uncategorized (no category_id)
        sub1 = SubTransaction(
            id="sub-001",
            transaction_id="txn-001",
            amount=-25.00,
        )
        assert sub1.is_uncategorized is True

        # Categorized
        sub2 = SubTransaction(
            id="sub-002",
            transaction_id="txn-001",
            amount=-25.00,
            category_id="cat-001",
            category_name="Electronics",
        )
        assert sub2.is_uncategorized is False

    def test_display_amount(self):
        """Test display_amount property."""
        from src.models import SubTransaction

        # Negative (outflow)
        sub1 = SubTransaction(id="sub-1", transaction_id="txn-1", amount=-47.82)
        assert sub1.display_amount == "-$47.82"

        # Positive (inflow)
        sub2 = SubTransaction(id="sub-2", transaction_id="txn-1", amount=100.00)
        assert sub2.display_amount == "$100.00"


class TestTransactionSyncFields:
    """Tests for new Transaction sync-related fields."""

    def test_is_split_default_false(self):
        """Test is_split defaults to False."""
        txn = Transaction(
            id="txn-001",
            date=datetime(2025, 1, 15),
            amount=-100.00,
            payee_name="Test",
        )
        assert txn.is_split is False

    def test_is_split_with_subtransactions(self, split_transaction):
        """Test is_split is True when subtransactions exist."""
        assert split_transaction.is_split is True
        assert len(split_transaction.subtransactions) == 2

    def test_sync_status_default(self):
        """Test sync_status defaults to 'synced'."""
        txn = Transaction(
            id="txn-001",
            date=datetime(2025, 1, 15),
            amount=-50.00,
            payee_name="Test",
        )
        assert txn.sync_status == "synced"

    def test_needs_push_property(self):
        """Test needs_push property."""
        txn = Transaction(
            id="txn-001",
            date=datetime(2025, 1, 15),
            amount=-50.00,
            payee_name="Test",
        )

        # Default is synced
        assert txn.needs_push is False

        # After local change
        txn.sync_status = "pending_push"
        assert txn.needs_push is True

    def test_has_conflict_property(self):
        """Test has_conflict property."""
        txn = Transaction(
            id="txn-001",
            date=datetime(2025, 1, 15),
            amount=-50.00,
            payee_name="Test",
        )

        # Default is synced
        assert txn.has_conflict is False

        # When conflict detected
        txn.sync_status = "conflict"
        assert txn.has_conflict is True

    def test_subtransactions_default_empty(self):
        """Test subtransactions defaults to empty list."""
        txn = Transaction(
            id="txn-001",
            date=datetime(2025, 1, 15),
            amount=-50.00,
            payee_name="Test",
        )
        assert txn.subtransactions == []

    def test_approved_field(self):
        """Test approved field."""
        txn = Transaction(
            id="txn-001",
            date=datetime(2025, 1, 15),
            amount=-50.00,
            payee_name="Test",
            approved=True,
        )
        assert txn.approved is True
        assert txn.is_unapproved is False

        txn.approved = False
        assert txn.is_unapproved is True
