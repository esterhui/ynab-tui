"""Tests for pure TUI state classes.

These tests verify the FilterState, TagState, and TransactionSelector
classes without requiring any Textual infrastructure.
"""

from datetime import datetime

import pytest

from src.models import Transaction
from src.tui.state import (
    CategoryFilter,
    FilterState,
    FilterStateMachine,
    TagManager,
    TagState,
    TransactionSelector,
)


class TestFilterState:
    """Tests for FilterState dataclass."""

    def test_default_values(self):
        """Test FilterState has correct defaults."""
        state = FilterState()
        assert state.mode == "all"
        assert state.category is None
        assert state.payee is None
        assert state.is_submenu_active is False

    def test_immutability(self):
        """Test FilterState is immutable (frozen)."""
        state = FilterState()
        with pytest.raises(AttributeError):
            state.mode = "approved"

    def test_valid_modes(self):
        """Test all valid filter modes."""
        for mode in ["all", "approved", "new", "uncategorized", "pending"]:
            state = FilterState(mode=mode)
            assert state.mode == mode

    def test_invalid_mode_raises_error(self):
        """Test invalid filter mode raises ValueError."""
        with pytest.raises(ValueError, match="Invalid filter mode"):
            FilterState(mode="invalid")

    def test_with_category(self):
        """Test FilterState with category filter."""
        cat = CategoryFilter(category_id="cat-123", category_name="Groceries")
        state = FilterState(category=cat)
        assert state.category is not None
        assert state.category.category_id == "cat-123"
        assert state.category.category_name == "Groceries"

    def test_with_payee(self):
        """Test FilterState with payee filter."""
        state = FilterState(payee="Amazon")
        assert state.payee == "Amazon"


class TestCategoryFilter:
    """Tests for CategoryFilter dataclass."""

    def test_create(self):
        """Test creating CategoryFilter."""
        cat = CategoryFilter(category_id="cat-123", category_name="Groceries")
        assert cat.category_id == "cat-123"
        assert cat.category_name == "Groceries"

    def test_immutability(self):
        """Test CategoryFilter is immutable."""
        cat = CategoryFilter(category_id="cat-123", category_name="Groceries")
        with pytest.raises(AttributeError):
            cat.category_name = "Food"


class TestFilterStateMachine:
    """Tests for FilterStateMachine transitions."""

    def test_enter_submenu(self):
        """Test entering filter submenu."""
        state = FilterState()
        new_state = FilterStateMachine.enter_submenu(state)
        assert new_state.is_submenu_active is True
        assert state.is_submenu_active is False  # Original unchanged

    def test_cancel_submenu(self):
        """Test canceling filter submenu."""
        state = FilterState(is_submenu_active=True)
        new_state = FilterStateMachine.cancel_submenu(state)
        assert new_state.is_submenu_active is False

    def test_apply_mode_approved(self):
        """Test applying approved filter mode."""
        state = FilterState()
        new_state = FilterStateMachine.apply_mode(state, "approved")
        assert new_state.mode == "approved"
        assert new_state.is_submenu_active is False

    def test_apply_mode_all_resets(self):
        """Test applying 'all' mode resets everything."""
        cat = CategoryFilter(category_id="cat-123", category_name="Groceries")
        state = FilterState(mode="approved", category=cat, payee="Amazon")
        new_state = FilterStateMachine.apply_mode(state, "all")
        assert new_state.mode == "all"
        assert new_state.category is None
        assert new_state.payee is None

    def test_set_category(self):
        """Test setting category filter."""
        state = FilterState()
        cat = CategoryFilter(category_id="cat-123", category_name="Groceries")
        new_state = FilterStateMachine.set_category(state, cat)
        assert new_state.category is not None
        assert new_state.category.category_name == "Groceries"
        assert new_state.is_submenu_active is False

    def test_clear_category(self):
        """Test clearing category filter."""
        cat = CategoryFilter(category_id="cat-123", category_name="Groceries")
        state = FilterState(category=cat)
        new_state = FilterStateMachine.clear_category(state)
        assert new_state.category is None

    def test_set_payee(self):
        """Test setting payee filter."""
        state = FilterState()
        new_state = FilterStateMachine.set_payee(state, "Amazon")
        assert new_state.payee == "Amazon"
        assert new_state.is_submenu_active is False

    def test_clear_payee(self):
        """Test clearing payee filter."""
        state = FilterState(payee="Amazon")
        new_state = FilterStateMachine.clear_payee(state)
        assert new_state.payee is None

    def test_reset(self):
        """Test full reset."""
        cat = CategoryFilter(category_id="cat-123", category_name="Groceries")
        state = FilterState(mode="approved", category=cat, payee="Amazon", is_submenu_active=True)
        new_state = FilterStateMachine.reset(state)
        assert new_state.mode == "all"
        assert new_state.category is None
        assert new_state.payee is None
        assert new_state.is_submenu_active is False

    def test_get_display_label_all(self):
        """Test display label for 'all' mode."""
        state = FilterState()
        label = FilterStateMachine.get_display_label(state)
        assert label == "All"

    def test_get_display_label_approved(self):
        """Test display label for 'approved' mode."""
        state = FilterState(mode="approved")
        label = FilterStateMachine.get_display_label(state)
        assert label == "Approved"

    def test_get_display_label_with_category(self):
        """Test display label with category filter."""
        cat = CategoryFilter(category_id="cat-123", category_name="Groceries")
        state = FilterState(category=cat)
        label = FilterStateMachine.get_display_label(state)
        assert label == "All | Cat:Groceries"

    def test_get_display_label_with_payee(self):
        """Test display label with payee filter."""
        state = FilterState(payee="Amazon")
        label = FilterStateMachine.get_display_label(state)
        assert label == "All | Payee:Amazon"

    def test_get_display_label_truncates_long_category(self):
        """Test display label truncates long category names."""
        cat = CategoryFilter(category_id="cat-123", category_name="Very Long Category Name")
        state = FilterState(category=cat)
        label = FilterStateMachine.get_display_label(state, max_len=15)
        assert "Cat:Very Long Ca..." in label

    def test_get_display_label_truncates_long_payee(self):
        """Test display label truncates long payee names."""
        state = FilterState(payee="This Is A Very Long Payee Name")
        label = FilterStateMachine.get_display_label(state, max_len=15)
        assert "Payee:" in label
        assert "..." in label

    def test_get_display_label_combined(self):
        """Test display label with multiple filters."""
        cat = CategoryFilter(category_id="cat-123", category_name="Groceries")
        state = FilterState(mode="approved", category=cat, payee="Amazon")
        label = FilterStateMachine.get_display_label(state)
        assert "Approved" in label
        assert "Cat:Groceries" in label
        assert "Payee:Amazon" in label


class TestTagState:
    """Tests for TagState dataclass."""

    def test_default_empty(self):
        """Test TagState starts empty."""
        state = TagState()
        assert state.count == 0
        assert state.is_empty is True

    def test_with_tagged_ids(self):
        """Test TagState with tagged IDs."""
        state = TagState(tagged_ids=frozenset({"txn-1", "txn-2"}))
        assert state.count == 2
        assert state.is_empty is False

    def test_contains(self):
        """Test contains method."""
        state = TagState(tagged_ids=frozenset({"txn-1", "txn-2"}))
        assert state.contains("txn-1") is True
        assert state.contains("txn-3") is False

    def test_immutability(self):
        """Test TagState is immutable."""
        state = TagState()
        with pytest.raises(AttributeError):
            state.tagged_ids = frozenset({"txn-1"})


class TestTagManager:
    """Tests for TagManager operations."""

    def test_toggle_adds_when_not_present(self):
        """Test toggle adds ID when not present."""
        state = TagState()
        new_state = TagManager.toggle(state, "txn-1")
        assert new_state.contains("txn-1") is True
        assert state.is_empty is True  # Original unchanged

    def test_toggle_removes_when_present(self):
        """Test toggle removes ID when present."""
        state = TagState(tagged_ids=frozenset({"txn-1"}))
        new_state = TagManager.toggle(state, "txn-1")
        assert new_state.contains("txn-1") is False

    def test_add(self):
        """Test adding a tag."""
        state = TagState()
        new_state = TagManager.add(state, "txn-1")
        assert new_state.contains("txn-1") is True

    def test_add_idempotent(self):
        """Test adding same ID twice is idempotent."""
        state = TagState(tagged_ids=frozenset({"txn-1"}))
        new_state = TagManager.add(state, "txn-1")
        assert new_state.count == 1

    def test_remove(self):
        """Test removing a tag."""
        state = TagState(tagged_ids=frozenset({"txn-1", "txn-2"}))
        new_state = TagManager.remove(state, "txn-1")
        assert new_state.contains("txn-1") is False
        assert new_state.contains("txn-2") is True

    def test_remove_nonexistent(self):
        """Test removing nonexistent ID is no-op."""
        state = TagState()
        new_state = TagManager.remove(state, "txn-1")
        assert new_state.is_empty is True

    def test_clear_all(self):
        """Test clearing all tags."""
        state = TagState(tagged_ids=frozenset({"txn-1", "txn-2", "txn-3"}))
        new_state = TagManager.clear_all(state)
        assert new_state.is_empty is True

    def test_get_tagged_transactions(self):
        """Test getting tagged transactions from list."""
        date = datetime(2025, 1, 1)
        txn1 = Transaction(id="txn-1", payee_name="Store 1", amount=-100, date=date)
        txn2 = Transaction(id="txn-2", payee_name="Store 2", amount=-200, date=date)
        txn3 = Transaction(id="txn-3", payee_name="Store 3", amount=-300, date=date)
        all_txns = [txn1, txn2, txn3]

        state = TagState(tagged_ids=frozenset({"txn-1", "txn-3"}))
        tagged = TagManager.get_tagged_transactions(state, all_txns)

        assert len(tagged) == 2
        assert txn1 in tagged
        assert txn3 in tagged
        assert txn2 not in tagged

    def test_get_tagged_transactions_empty(self):
        """Test getting tagged transactions when none tagged."""
        date = datetime(2025, 1, 1)
        txn1 = Transaction(id="txn-1", payee_name="Store 1", amount=-100, date=date)
        all_txns = [txn1]

        state = TagState()
        tagged = TagManager.get_tagged_transactions(state, all_txns)

        assert tagged == []


class TestTransactionSelector:
    """Tests for TransactionSelector operations."""

    @pytest.fixture
    def sample_transactions(self) -> list[Transaction]:
        """Create sample transactions for testing."""
        date = datetime(2025, 1, 1)
        return [
            Transaction(id="txn-1", payee_name="Store 1", amount=-100, date=date),
            Transaction(id="txn-2", payee_name="Store 2", amount=-200, date=date),
            Transaction(id="txn-3", payee_name="Store 3", amount=-300, date=date),
        ]

    def test_get_at_index_valid(self, sample_transactions):
        """Test getting transaction at valid index."""
        txn = TransactionSelector.get_at_index(sample_transactions, 1)
        assert txn is not None
        assert txn.id == "txn-2"

    def test_get_at_index_first(self, sample_transactions):
        """Test getting first transaction."""
        txn = TransactionSelector.get_at_index(sample_transactions, 0)
        assert txn is not None
        assert txn.id == "txn-1"

    def test_get_at_index_last(self, sample_transactions):
        """Test getting last transaction."""
        txn = TransactionSelector.get_at_index(sample_transactions, 2)
        assert txn is not None
        assert txn.id == "txn-3"

    def test_get_at_index_none(self, sample_transactions):
        """Test getting at None index returns None."""
        txn = TransactionSelector.get_at_index(sample_transactions, None)
        assert txn is None

    def test_get_at_index_negative(self, sample_transactions):
        """Test getting at negative index returns None."""
        txn = TransactionSelector.get_at_index(sample_transactions, -1)
        assert txn is None

    def test_get_at_index_out_of_bounds(self, sample_transactions):
        """Test getting at out-of-bounds index returns None."""
        txn = TransactionSelector.get_at_index(sample_transactions, 100)
        assert txn is None

    def test_get_at_index_empty_list(self):
        """Test getting from empty list returns None."""
        txn = TransactionSelector.get_at_index([], 0)
        assert txn is None

    def test_find_index_found(self, sample_transactions):
        """Test finding index of existing transaction."""
        idx = TransactionSelector.find_index(sample_transactions, "txn-2")
        assert idx == 1

    def test_find_index_first(self, sample_transactions):
        """Test finding index of first transaction."""
        idx = TransactionSelector.find_index(sample_transactions, "txn-1")
        assert idx == 0

    def test_find_index_not_found(self, sample_transactions):
        """Test finding index of nonexistent transaction."""
        idx = TransactionSelector.find_index(sample_transactions, "txn-999")
        assert idx is None

    def test_find_index_empty_list(self):
        """Test finding in empty list returns None."""
        idx = TransactionSelector.find_index([], "txn-1")
        assert idx is None

    def test_get_next_index(self):
        """Test getting next index."""
        idx = TransactionSelector.get_next_index(1, 3)
        assert idx == 2

    def test_get_next_index_at_end_no_wrap(self):
        """Test next index at end without wrap returns None."""
        idx = TransactionSelector.get_next_index(2, 3, wrap=False)
        assert idx is None

    def test_get_next_index_at_end_with_wrap(self):
        """Test next index at end with wrap returns 0."""
        idx = TransactionSelector.get_next_index(2, 3, wrap=True)
        assert idx == 0

    def test_get_next_index_from_none(self):
        """Test next index from None starts at 0."""
        idx = TransactionSelector.get_next_index(None, 3)
        assert idx == 0

    def test_get_next_index_empty_list(self):
        """Test next index with empty list returns None."""
        idx = TransactionSelector.get_next_index(0, 0)
        assert idx is None

    def test_get_prev_index(self):
        """Test getting previous index."""
        idx = TransactionSelector.get_prev_index(2, 3)
        assert idx == 1

    def test_get_prev_index_at_start_no_wrap(self):
        """Test prev index at start without wrap returns None."""
        idx = TransactionSelector.get_prev_index(0, 3, wrap=False)
        assert idx is None

    def test_get_prev_index_at_start_with_wrap(self):
        """Test prev index at start with wrap returns last."""
        idx = TransactionSelector.get_prev_index(0, 3, wrap=True)
        assert idx == 2

    def test_get_prev_index_from_none(self):
        """Test prev index from None starts at end."""
        idx = TransactionSelector.get_prev_index(None, 3)
        assert idx == 2

    def test_get_prev_index_empty_list(self):
        """Test prev index with empty list returns None."""
        idx = TransactionSelector.get_prev_index(0, 0)
        assert idx is None
