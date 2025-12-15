"""Tests for TUI modal components.

These tests verify that modals work correctly and don't crash,
using Textual's testing framework.
"""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from src.models import Transaction
from src.tui.modals.category_picker import (
    CategoryPickerModal,
    CategorySelection,
    TransactionSummary,
)
from src.tui.modals.fuzzy_select import FuzzySelectItem, FuzzySelectModal
from src.tui.modals.transaction_search import TransactionSearchModal


@pytest.fixture
def sample_categories():
    """Sample categories for testing."""
    return [
        {"id": "cat-1", "name": "Groceries", "group_name": "Food"},
        {"id": "cat-2", "name": "Restaurants", "group_name": "Food"},
        {"id": "cat-3", "name": "Gas", "group_name": "Transport"},
        {"id": "cat-4", "name": "Parking", "group_name": "Transport"},
        {"id": "cat-5", "name": "Rent", "group_name": "Bills"},
    ]


@pytest.fixture
def sample_transaction_summary():
    """Sample transaction summary for testing."""
    return TransactionSummary(
        date="2024-01-15",
        payee="Test Store",
        amount="-$50.00",
        current_category="Groceries",
        current_category_id="cat-1",
        amazon_items=["Item 1", "Item 2"],
    )


@pytest.fixture
def sample_transactions():
    """Sample transactions for testing."""
    from datetime import datetime

    return [
        Transaction(
            id="txn-1",
            date=datetime(2024, 1, 15),
            amount=-50.00,
            payee_name="Grocery Store",
            category_name="Groceries",
            category_id="cat-1",
            account_name="Checking",
            approved=True,
        ),
        Transaction(
            id="txn-2",
            date=datetime(2024, 1, 16),
            amount=-25.00,
            payee_name="Gas Station",
            category_name="Gas",
            category_id="cat-2",
            account_name="Credit",
            approved=True,
        ),
        Transaction(
            id="txn-3",
            date=datetime(2024, 1, 17),
            amount=-100.00,
            payee_name="Amazon",
            category_name=None,
            category_id=None,
            account_name="Credit",
            approved=False,
        ),
    ]


# Test App wrapper for modal testing
class ModalTestApp(App):
    """Test app for mounting modals."""

    def __init__(self, modal):
        super().__init__()
        self._modal = modal
        self._result = None

    def compose(self) -> ComposeResult:
        yield Static("Test App")

    def on_mount(self) -> None:
        """Push modal on mount."""
        self.push_screen(self._modal, self._on_result)

    def _on_result(self, result):
        """Store result and exit."""
        self._result = result
        self.exit()


class TestCategorySelection:
    """Tests for CategorySelection dataclass."""

    def test_category_selection_creation(self):
        """Test creating a CategorySelection."""
        selection = CategorySelection(category_id="cat-1", category_name="Groceries")
        assert selection.category_id == "cat-1"
        assert selection.category_name == "Groceries"


class TestTransactionSummary:
    """Tests for TransactionSummary dataclass."""

    def test_transaction_summary_creation(self):
        """Test creating a TransactionSummary."""
        summary = TransactionSummary(
            date="2024-01-15",
            payee="Test Payee",
            amount="-$50.00",
        )
        assert summary.date == "2024-01-15"
        assert summary.payee == "Test Payee"
        assert summary.amount == "-$50.00"
        assert summary.current_category is None
        assert summary.amazon_items is None

    def test_transaction_summary_with_all_fields(self):
        """Test TransactionSummary with all optional fields."""
        summary = TransactionSummary(
            date="2024-01-15",
            payee="Amazon",
            amount="-$100.00",
            current_category="Shopping",
            current_category_id="cat-shop",
            amazon_items=["USB Cable", "Phone Case"],
        )
        assert summary.current_category == "Shopping"
        assert summary.current_category_id == "cat-shop"
        assert len(summary.amazon_items) == 2


class TestCategoryPickerModal:
    """Tests for CategoryPickerModal."""

    async def test_modal_opens_without_crash(self, sample_categories):
        """Test modal opens successfully."""
        modal = CategoryPickerModal(categories=sample_categories)
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Modal should be visible
            assert len(app.screen_stack) >= 1
            # Press escape to close
            await pilot.press("escape")
            await pilot.pause()

    async def test_modal_with_transaction_summary(
        self, sample_categories, sample_transaction_summary
    ):
        """Test modal with transaction summary displayed."""
        modal = CategoryPickerModal(
            categories=sample_categories,
            transaction=sample_transaction_summary,
        )
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Should show transaction info in modal
            await pilot.press("escape")
            await pilot.pause()

    async def test_modal_navigation_keys(self, sample_categories):
        """Test navigation keys don't crash."""
        modal = CategoryPickerModal(categories=sample_categories)
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Test navigation keys
            await pilot.press("down")
            await pilot.pause()
            await pilot.press("up")
            await pilot.pause()
            await pilot.press("pagedown")
            await pilot.pause()
            await pilot.press("pageup")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

    async def test_modal_typing_filter(self, sample_categories):
        """Test typing to filter categories."""
        modal = CategoryPickerModal(categories=sample_categories)
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Type to filter
            await pilot.press("g")
            await pilot.pause()
            await pilot.press("r")
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()
            # Press escape to close
            await pilot.press("escape")
            await pilot.pause()

    async def test_modal_enter_selects(self, sample_categories):
        """Test Enter key selects category."""
        modal = CategoryPickerModal(categories=sample_categories)
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Press Enter to select first category
            await pilot.press("enter")
            await pilot.pause()

    async def test_modal_empty_categories(self):
        """Test modal with empty categories list."""
        modal = CategoryPickerModal(categories=[])
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()


class TestFuzzySelectItem:
    """Tests for FuzzySelectItem widget."""

    def test_fuzzy_select_item_creation(self):
        """Test creating a FuzzySelectItem."""
        item = FuzzySelectItem("Display Text", {"key": "value"})
        assert item._display_text == "Display Text"
        assert item.item == {"key": "value"}


class TestFuzzySelectModal:
    """Tests for FuzzySelectModal."""

    async def test_modal_opens_without_crash(self):
        """Test modal opens successfully."""
        items = ["Apple", "Banana", "Cherry"]
        modal = FuzzySelectModal(
            items=items,
            display_fn=str,
            search_fn=str,
            result_fn=str,
            title="Select Fruit",
        )
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

    async def test_modal_typing_search(self):
        """Test typing to search in fuzzy select."""
        items = ["Apple", "Banana", "Cherry", "Date"]
        modal = FuzzySelectModal(
            items=items,
            display_fn=str,
            search_fn=str,
            result_fn=str,
        )
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Type search
            await pilot.press("a")
            await pilot.pause()
            await pilot.press("p")
            await pilot.pause()
            # Wait for debounce
            await pilot.pause()
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

    async def test_modal_navigation(self):
        """Test navigation in fuzzy select."""
        items = ["Item 1", "Item 2", "Item 3"]
        modal = FuzzySelectModal(
            items=items,
            display_fn=str,
            search_fn=str,
            result_fn=str,
        )
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Type something to populate results
            await pilot.press("i")
            await pilot.pause()
            await pilot.pause()  # debounce
            # Navigate
            await pilot.press("down")
            await pilot.pause()
            await pilot.press("up")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

    async def test_modal_with_custom_functions(self):
        """Test modal with custom display/search/result functions."""
        items = [
            {"name": "Apple", "color": "red"},
            {"name": "Banana", "color": "yellow"},
        ]
        modal = FuzzySelectModal(
            items=items,
            display_fn=lambda x: f"{x['name']} ({x['color']})",
            search_fn=lambda x: x["name"],
            result_fn=lambda x: x["name"],
            placeholder="Search fruits...",
        )
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()


class TestTransactionSearchModal:
    """Tests for TransactionSearchModal."""

    async def test_modal_opens_without_crash(self, sample_transactions):
        """Test modal opens successfully."""
        modal = TransactionSearchModal(transactions=sample_transactions)
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

    async def test_modal_typing_search(self, sample_transactions):
        """Test typing to search transactions."""
        modal = TransactionSearchModal(transactions=sample_transactions)
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Type to search by payee
            await pilot.press("g")
            await pilot.pause()
            await pilot.press("r")
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()
            # Wait for debounce
            await pilot.pause()
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

    async def test_modal_navigation_keys(self, sample_transactions):
        """Test navigation keys in transaction search."""
        modal = TransactionSearchModal(transactions=sample_transactions)
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Type to get results
            await pilot.press("a")
            await pilot.pause()
            await pilot.pause()  # debounce
            # Navigate results
            await pilot.press("down")
            await pilot.pause()
            await pilot.press("up")
            await pilot.pause()
            await pilot.press("pagedown")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

    async def test_modal_empty_transactions(self):
        """Test modal with empty transactions list."""
        modal = TransactionSearchModal(transactions=[])
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

    async def test_modal_enter_selects(self, sample_transactions):
        """Test Enter key selects transaction."""
        modal = TransactionSearchModal(transactions=sample_transactions)
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Type to get results
            await pilot.press("g")
            await pilot.pause()
            await pilot.pause()  # debounce
            # Press Enter
            await pilot.press("enter")
            await pilot.pause()
