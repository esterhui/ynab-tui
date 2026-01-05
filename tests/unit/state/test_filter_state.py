"""Tests for FilterState and FilterStateMachine.

These tests verify the pure state machine logic without Textual UI.
"""

import pytest

from ynab_tui.tui.state import (
    FILTER_LABELS,
    CategoryFilter,
    FilterState,
    FilterStateMachine,
)


class TestFilterState:
    """Tests for FilterState dataclass."""

    def test_default_values(self) -> None:
        """Default state should have all defaults."""
        state = FilterState()
        assert state.mode == "all"
        assert state.category is None
        assert state.payee is None
        assert state.is_submenu_active is False

    def test_custom_mode(self) -> None:
        """Can create state with custom mode."""
        state = FilterState(mode="unapproved")
        assert state.mode == "unapproved"

    def test_invalid_mode_raises(self) -> None:
        """Invalid mode should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid filter mode"):
            FilterState(mode="invalid")

    def test_with_category(self) -> None:
        """Can create state with category filter."""
        cat = CategoryFilter(category_id="cat-1", category_name="Groceries")
        state = FilterState(category=cat)
        assert state.category is not None
        assert state.category.category_name == "Groceries"

    def test_with_payee(self) -> None:
        """Can create state with payee filter."""
        state = FilterState(payee="Amazon")
        assert state.payee == "Amazon"

    def test_is_frozen(self) -> None:
        """FilterState should be immutable (frozen)."""
        state = FilterState()
        with pytest.raises(Exception):  # FrozenInstanceError
            state.mode = "unapproved"  # type: ignore


class TestCategoryFilter:
    """Tests for CategoryFilter dataclass."""

    def test_create_category_filter(self) -> None:
        """Can create CategoryFilter."""
        cat = CategoryFilter(category_id="id-1", category_name="Groceries")
        assert cat.category_id == "id-1"
        assert cat.category_name == "Groceries"

    def test_is_frozen(self) -> None:
        """CategoryFilter should be immutable."""
        cat = CategoryFilter(category_id="id-1", category_name="Groceries")
        with pytest.raises(Exception):
            cat.category_name = "Other"  # type: ignore


class TestFilterStateMachine:
    """Tests for FilterStateMachine transitions."""

    def test_enter_submenu(self) -> None:
        """enter_submenu should activate submenu."""
        state = FilterState()
        new_state = FilterStateMachine.enter_submenu(state)

        assert new_state.is_submenu_active is True
        assert state.is_submenu_active is False  # Original unchanged

    def test_cancel_submenu(self) -> None:
        """cancel_submenu should deactivate submenu."""
        state = FilterState(is_submenu_active=True)
        new_state = FilterStateMachine.cancel_submenu(state)

        assert new_state.is_submenu_active is False

    def test_apply_mode_unapproved(self) -> None:
        """apply_mode should set mode and close submenu."""
        state = FilterState(is_submenu_active=True)
        new_state = FilterStateMachine.apply_mode(state, "unapproved")

        assert new_state.mode == "unapproved"
        assert new_state.is_submenu_active is False

    def test_apply_mode_all_resets(self) -> None:
        """apply_mode('all') should reset all filters."""
        state = FilterState(
            mode="unapproved",
            category=CategoryFilter("id", "Cat"),
            payee="Test",
            is_submenu_active=True,
        )
        new_state = FilterStateMachine.apply_mode(state, "all")

        assert new_state.mode == "all"
        assert new_state.category is None
        assert new_state.payee is None
        assert new_state.is_submenu_active is False

    def test_set_category(self) -> None:
        """set_category should set category and close submenu."""
        state = FilterState(is_submenu_active=True)
        cat = CategoryFilter("id-1", "Groceries")
        new_state = FilterStateMachine.set_category(state, cat)

        assert new_state.category == cat
        assert new_state.is_submenu_active is False

    def test_clear_category(self) -> None:
        """clear_category should remove category."""
        cat = CategoryFilter("id-1", "Groceries")
        state = FilterState(category=cat)
        new_state = FilterStateMachine.clear_category(state)

        assert new_state.category is None

    def test_set_payee(self) -> None:
        """set_payee should set payee and close submenu."""
        state = FilterState(is_submenu_active=True)
        new_state = FilterStateMachine.set_payee(state, "Amazon")

        assert new_state.payee == "Amazon"
        assert new_state.is_submenu_active is False

    def test_clear_payee(self) -> None:
        """clear_payee should remove payee."""
        state = FilterState(payee="Amazon")
        new_state = FilterStateMachine.clear_payee(state)

        assert new_state.payee is None

    def test_reset(self) -> None:
        """reset should return default state."""
        state = FilterState(
            mode="unapproved",
            category=CategoryFilter("id", "Cat"),
            payee="Test",
        )
        new_state = FilterStateMachine.reset(state)

        assert new_state == FilterState()

    def test_get_display_label_all(self) -> None:
        """Display label for 'all' should be 'All'."""
        state = FilterState()
        label = FilterStateMachine.get_display_label(state)

        assert label == "All"

    def test_get_display_label_unapproved(self) -> None:
        """Display label for 'unapproved' should be 'Unapproved'."""
        state = FilterState(mode="unapproved")
        label = FilterStateMachine.get_display_label(state)

        assert label == "Unapproved"

    def test_get_display_label_with_category(self) -> None:
        """Display label with category should include Cat:name."""
        state = FilterState(
            mode="unapproved",
            category=CategoryFilter("id", "Groceries"),
        )
        label = FilterStateMachine.get_display_label(state)

        assert "Unapproved" in label
        assert "Cat:Groceries" in label

    def test_get_display_label_with_payee(self) -> None:
        """Display label with payee should include Payee:name."""
        state = FilterState(payee="Amazon")
        label = FilterStateMachine.get_display_label(state)

        assert "Payee:Amazon" in label

    def test_get_display_label_truncates_long_names(self) -> None:
        """Long category/payee names should be truncated."""
        state = FilterState(
            category=CategoryFilter("id", "Very Long Category Name Here"),
        )
        label = FilterStateMachine.get_display_label(state, max_len=10)

        assert "..." in label
        assert len(label) < len("Cat:Very Long Category Name Here")

    def test_get_display_label_all_parts(self) -> None:
        """Display label with mode, category, and payee."""
        state = FilterState(
            mode="pending",
            category=CategoryFilter("id", "Groceries"),
            payee="Amazon",
        )
        label = FilterStateMachine.get_display_label(state)

        assert "Pending Push" in label
        assert "Cat:Groceries" in label
        assert "Payee:Amazon" in label
        assert " | " in label


class TestFilterLabels:
    """Tests for FILTER_LABELS constant."""

    def test_all_modes_have_labels(self) -> None:
        """All valid modes should have labels."""
        valid_modes = {"all", "unapproved", "uncategorized", "pending"}
        for mode in valid_modes:
            assert mode in FILTER_LABELS
            assert isinstance(FILTER_LABELS[mode], str)
