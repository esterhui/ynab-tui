"""Tests for TUI modal components.

These tests verify that modals work correctly and don't crash,
using Textual's testing framework.
"""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from ynab_tui.models import Transaction
from ynab_tui.tui.modals.category_picker import (
    CategoryPickerModal,
    CategorySelection,
    TransactionSummary,
)
from ynab_tui.tui.modals.fuzzy_select import FuzzySelectItem, FuzzySelectModal
from ynab_tui.tui.modals.transaction_search import TransactionSearchModal


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


class TestBudgetPickerModal:
    """Tests for BudgetPickerModal."""

    @pytest.fixture
    def sample_budgets(self):
        """Sample budgets for testing."""
        from datetime import datetime

        return [
            {
                "id": "budget-1",
                "name": "Personal Budget",
                "last_modified_on": datetime(2024, 1, 15),
            },
            {
                "id": "budget-2",
                "name": "Business Budget",
                "last_modified_on": "2024-02-20",
            },
            {
                "id": "budget-3",
                "name": "Savings Budget",
                "last_modified_on": None,
            },
        ]

    async def test_modal_opens_without_crash(self, sample_budgets):
        """Test modal opens successfully."""
        from ynab_tui.tui.modals.budget_picker import BudgetPickerModal

        modal = BudgetPickerModal(budgets=sample_budgets)
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

    async def test_modal_with_current_budget(self, sample_budgets):
        """Test modal with current budget highlighted."""
        from ynab_tui.tui.modals.budget_picker import BudgetPickerModal

        modal = BudgetPickerModal(
            budgets=sample_budgets,
            current_budget_id="budget-1",
        )
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

    async def test_modal_enter_selects(self, sample_budgets):
        """Test Enter key selects budget."""
        from ynab_tui.tui.modals.budget_picker import BudgetPickerModal

        modal = BudgetPickerModal(budgets=sample_budgets)
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

    async def test_modal_typing_filter(self, sample_budgets):
        """Test typing to filter budgets."""
        from ynab_tui.tui.modals.budget_picker import BudgetPickerModal

        modal = BudgetPickerModal(budgets=sample_budgets)
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("p")
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()


class TestBudgetSelection:
    """Tests for BudgetSelection dataclass."""

    def test_budget_selection_creation(self):
        """Test creating a BudgetSelection."""
        from ynab_tui.tui.modals.budget_picker import BudgetSelection

        selection = BudgetSelection(budget_id="budget-1", budget_name="My Budget")
        assert selection.budget_id == "budget-1"
        assert selection.budget_name == "My Budget"


class TestCategoryFilterModal:
    """Tests for CategoryFilterModal."""

    async def test_modal_opens_without_crash(self, sample_categories):
        """Test modal opens successfully."""
        from ynab_tui.tui.modals.category_filter import CategoryFilterModal

        modal = CategoryFilterModal(categories=sample_categories)
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

    async def test_modal_enter_selects(self, sample_categories):
        """Test Enter key selects category."""
        from ynab_tui.tui.modals.category_filter import CategoryFilterModal

        modal = CategoryFilterModal(categories=sample_categories)
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

    async def test_modal_typing_filter(self, sample_categories):
        """Test typing to filter categories."""
        from ynab_tui.tui.modals.category_filter import CategoryFilterModal

        modal = CategoryFilterModal(categories=sample_categories)
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("g")
            await pilot.pause()
            await pilot.press("r")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()


class TestCategoryFilterResult:
    """Tests for CategoryFilterResult dataclass."""

    def test_category_filter_result_creation(self):
        """Test creating a CategoryFilterResult."""
        from ynab_tui.tui.modals.category_filter import CategoryFilterResult

        result = CategoryFilterResult(category_id="cat-1", category_name="Groceries")
        assert result.category_id == "cat-1"
        assert result.category_name == "Groceries"


class TestPayeeFilterModal:
    """Tests for PayeeFilterModal."""

    @pytest.fixture
    def sample_payees(self):
        """Sample payees for testing."""
        return ["Amazon", "Walmart", "Target", "Costco"]

    async def test_modal_opens_without_crash(self, sample_payees):
        """Test modal opens successfully."""
        from ynab_tui.tui.modals.payee_filter import PayeeFilterModal

        modal = PayeeFilterModal(payees=sample_payees)
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

    async def test_modal_enter_selects(self, sample_payees):
        """Test Enter key selects payee."""
        from ynab_tui.tui.modals.payee_filter import PayeeFilterModal

        modal = PayeeFilterModal(payees=sample_payees)
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

    async def test_modal_navigation(self, sample_payees):
        """Test navigation in payee filter."""
        from ynab_tui.tui.modals.payee_filter import PayeeFilterModal

        modal = PayeeFilterModal(payees=sample_payees)
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            await pilot.press("up")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()


class TestGetUniquePayees:
    """Tests for get_unique_payees function."""

    def test_get_unique_payees(self, sample_transactions):
        """Test extracting unique payees from transactions."""
        from ynab_tui.tui.modals.payee_filter import get_unique_payees

        payees = get_unique_payees(sample_transactions)
        assert len(payees) == 3
        assert "Grocery Store" in payees
        assert "Gas Station" in payees
        assert "Amazon" in payees

    def test_get_unique_payees_empty(self):
        """Test extracting payees from empty list."""
        from ynab_tui.tui.modals.payee_filter import get_unique_payees

        payees = get_unique_payees([])
        assert len(payees) == 0


# =============================================================================
# MemoEditModal Tests
# =============================================================================


class TestMemoEditResult:
    """Tests for MemoEditResult dataclass."""

    def test_memo_edit_result_creation(self):
        """Test creating a MemoEditResult."""
        from ynab_tui.tui.modals.memo_edit import MemoEditResult

        result = MemoEditResult(memo="Test memo", changed=True)
        assert result.memo == "Test memo"
        assert result.changed is True

    def test_memo_edit_result_unchanged(self):
        """Test MemoEditResult with no change."""
        from ynab_tui.tui.modals.memo_edit import MemoEditResult

        result = MemoEditResult(memo="Same memo", changed=False)
        assert result.memo == "Same memo"
        assert result.changed is False


class TestTransactionInfo:
    """Tests for TransactionInfo dataclass."""

    def test_transaction_info_creation(self):
        """Test creating TransactionInfo."""
        from ynab_tui.tui.modals.memo_edit import TransactionInfo

        info = TransactionInfo(
            date="2024-01-15",
            payee="Test Store",
            amount="-$50.00",
        )
        assert info.date == "2024-01-15"
        assert info.payee == "Test Store"
        assert info.amount == "-$50.00"
        assert info.current_memo is None

    def test_transaction_info_with_memo(self):
        """Test TransactionInfo with memo."""
        from ynab_tui.tui.modals.memo_edit import TransactionInfo

        info = TransactionInfo(
            date="2024-01-15",
            payee="Test Store",
            amount="-$50.00",
            current_memo="Existing memo",
        )
        assert info.current_memo == "Existing memo"


class TestMemoEditModal:
    """Tests for MemoEditModal."""

    @pytest.fixture
    def sample_transaction_info(self):
        """Sample transaction info for testing."""
        from ynab_tui.tui.modals.memo_edit import TransactionInfo

        return TransactionInfo(
            date="2024-01-15",
            payee="Test Store",
            amount="-$50.00",
            current_memo="Original memo",
        )

    @pytest.fixture
    def transaction_info_no_memo(self):
        """Transaction info with no memo."""
        from ynab_tui.tui.modals.memo_edit import TransactionInfo

        return TransactionInfo(
            date="2024-01-15",
            payee="Test Store",
            amount="-$50.00",
        )

    async def test_modal_opens_without_crash(self, sample_transaction_info):
        """Test modal opens successfully."""
        from ynab_tui.tui.modals.memo_edit import MemoEditModal

        modal = MemoEditModal(transaction=sample_transaction_info)
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Modal should be visible
            assert len(app.screen_stack) >= 1
            await pilot.press("escape")
            await pilot.pause()

    async def test_modal_displays_transaction_info(self, sample_transaction_info):
        """Test modal shows transaction payee and amount."""
        from ynab_tui.tui.modals.memo_edit import MemoEditModal

        modal = MemoEditModal(transaction=sample_transaction_info)
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Check that transaction info is in the screen (modal is visible)
            assert modal._transaction.payee == "Test Store"
            assert modal._transaction.amount == "-$50.00"
            await pilot.press("escape")
            await pilot.pause()

    async def test_modal_displays_current_memo(self, sample_transaction_info):
        """Test modal shows current memo."""
        from ynab_tui.tui.modals.memo_edit import MemoEditModal

        modal = MemoEditModal(transaction=sample_transaction_info)
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Check original memo is stored
            assert modal._original_memo == "Original memo"
            await pilot.press("escape")
            await pilot.pause()

    async def test_modal_displays_no_memo_message(self, transaction_info_no_memo):
        """Test modal shows 'No memo set' when no memo exists."""
        from ynab_tui.tui.modals.memo_edit import MemoEditModal

        modal = MemoEditModal(transaction=transaction_info_no_memo)
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Original memo should be empty string
            assert modal._original_memo == ""
            await pilot.press("escape")
            await pilot.pause()

    async def test_cancel_returns_none(self, sample_transaction_info):
        """Test escape cancels and returns None."""
        from ynab_tui.tui.modals.memo_edit import MemoEditModal

        modal = MemoEditModal(transaction=sample_transaction_info)
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

        assert app._result is None

    async def test_save_returns_memo_result(self, sample_transaction_info):
        """Test enter saves and returns MemoEditResult."""
        from ynab_tui.tui.modals.memo_edit import MemoEditModal

        modal = MemoEditModal(transaction=sample_transaction_info)
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Press enter to save (without changing memo)
            await pilot.press("enter")
            await pilot.pause()

        # Should return result (not None)
        assert app._result is not None
        assert app._result.memo == "Original memo"
        assert app._result.changed is False

    async def test_save_detects_changed_memo(self, sample_transaction_info):
        """Test save detects when memo was changed."""
        from textual.widgets import Input

        from ynab_tui.tui.modals.memo_edit import MemoEditModal

        modal = MemoEditModal(transaction=sample_transaction_info)
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Directly set the input value (simulating user typing)
            input_widget = modal.query_one("#memo-input", Input)
            input_widget.value = "New memo text"
            await pilot.pause()
            # Save
            await pilot.press("enter")
            await pilot.pause()

        assert app._result is not None
        assert app._result.memo == "New memo text"
        assert app._result.changed is True

    async def test_save_unchanged_memo(self, transaction_info_no_memo):
        """Test save with unchanged empty memo."""
        from ynab_tui.tui.modals.memo_edit import MemoEditModal

        modal = MemoEditModal(transaction=transaction_info_no_memo)
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Just press enter without typing
            await pilot.press("enter")
            await pilot.pause()

        assert app._result is not None
        assert app._result.memo == ""
        assert app._result.changed is False

    async def test_input_focus_on_mount(self, sample_transaction_info):
        """Test input is focused when modal opens."""
        from textual.widgets import Input

        from ynab_tui.tui.modals.memo_edit import MemoEditModal

        modal = MemoEditModal(transaction=sample_transaction_info)
        app = ModalTestApp(modal)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Check that input has focus
            focused = modal.focused
            assert isinstance(focused, Input)
            await pilot.press("escape")
            await pilot.pause()


# =============================================================================
# CategoryFilterModal Extended Tests
# =============================================================================


class TestCategoryFilterModalExtended:
    """Extended tests for CategoryFilterModal static methods."""

    @pytest.fixture
    def filter_categories(self):
        """Sample categories for filter testing."""
        return [
            {"id": "cat-1", "name": "Groceries", "group_name": "Food"},
            {"id": "cat-2", "name": "Restaurants", "group_name": "Food"},
            {"id": "cat-3", "name": "Gas", "group_name": "Transport"},
            {"id": "cat-4", "name": "Electric", "group_name": "Bills"},
        ]

    def test_format_category_with_group(self, filter_categories):
        """Test _format_category includes group name."""
        from ynab_tui.tui.modals.category_filter import CategoryFilterModal

        result = CategoryFilterModal._format_category(filter_categories[0])
        assert "Groceries" in result
        assert "Food" in result

    def test_format_category_without_group(self):
        """Test _format_category without group name."""
        from ynab_tui.tui.modals.category_filter import CategoryFilterModal

        cat = {"id": "cat-1", "name": "Misc"}
        result = CategoryFilterModal._format_category(cat)
        assert result == "Misc"

    def test_search_text(self, filter_categories):
        """Test _search_text extracts searchable text."""
        from ynab_tui.tui.modals.category_filter import CategoryFilterModal

        result = CategoryFilterModal._search_text(filter_categories[0])
        assert "Food" in result
        assert "Groceries" in result

    def test_make_result(self, filter_categories):
        """Test _make_result creates CategoryFilterResult."""
        from ynab_tui.tui.modals.category_filter import (
            CategoryFilterModal,
            CategoryFilterResult,
        )

        result = CategoryFilterModal._make_result(filter_categories[0])
        assert isinstance(result, CategoryFilterResult)
        assert result.category_id == "cat-1"
        assert result.category_name == "Groceries"
