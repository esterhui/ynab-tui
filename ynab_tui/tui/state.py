"""Pure state classes for TUI - testable without Textual.

This module contains immutable state classes and pure state machines
that can be tested without running the full Textual application.
"""

from dataclasses import dataclass, field, replace
from typing import Optional

from ynab_tui.models import Transaction

# Filter state labels matching app.py FILTER_LABELS
FILTER_LABELS = {
    "all": "All",
    "approved": "Approved",
    "new": "New (Unapproved)",
    "uncategorized": "Uncategorized",
    "pending": "Pending Push",
}


@dataclass(frozen=True)
class CategoryFilter:
    """Immutable category filter value."""

    category_id: str
    category_name: str


@dataclass(frozen=True)
class FilterState:
    """Immutable filter state.

    All filter-related state in one place, making transitions explicit
    and testable without running the full TUI.
    """

    mode: str = "all"  # all, approved, new, uncategorized, pending
    category: Optional[CategoryFilter] = None
    payee: Optional[str] = None
    is_submenu_active: bool = False

    def __post_init__(self) -> None:
        """Validate filter mode."""
        valid_modes = {"all", "approved", "new", "uncategorized", "pending"}
        if self.mode not in valid_modes:
            raise ValueError(f"Invalid filter mode: {self.mode}")


class FilterStateMachine:
    """Pure state transitions for filter - testable without UI.

    All methods are static and return new FilterState instances,
    making the state transitions explicit and easy to test.
    """

    @staticmethod
    def enter_submenu(state: FilterState) -> FilterState:
        """Enter the filter submenu (waiting for filter key)."""
        return replace(state, is_submenu_active=True)

    @staticmethod
    def cancel_submenu(state: FilterState) -> FilterState:
        """Cancel the filter submenu without changing filter."""
        return replace(state, is_submenu_active=False)

    @staticmethod
    def apply_mode(state: FilterState, mode: str) -> FilterState:
        """Apply a new filter mode.

        Args:
            state: Current filter state
            mode: New mode to apply ("all", "approved", etc.)

        Returns:
            New FilterState with mode applied
        """
        if mode == "all":
            # Reset everything when switching to "all"
            return FilterState()
        return replace(state, mode=mode, is_submenu_active=False)

    @staticmethod
    def set_category(state: FilterState, category: CategoryFilter) -> FilterState:
        """Set category filter.

        Args:
            state: Current filter state
            category: Category to filter by

        Returns:
            New FilterState with category filter set
        """
        return replace(state, category=category, is_submenu_active=False)

    @staticmethod
    def clear_category(state: FilterState) -> FilterState:
        """Clear category filter."""
        return replace(state, category=None, is_submenu_active=False)

    @staticmethod
    def set_payee(state: FilterState, payee: str) -> FilterState:
        """Set payee filter.

        Args:
            state: Current filter state
            payee: Payee name to filter by

        Returns:
            New FilterState with payee filter set
        """
        return replace(state, payee=payee, is_submenu_active=False)

    @staticmethod
    def clear_payee(state: FilterState) -> FilterState:
        """Clear payee filter."""
        return replace(state, payee=None, is_submenu_active=False)

    @staticmethod
    def reset(state: FilterState) -> FilterState:
        """Reset all filters to default.

        Returns:
            New FilterState with all defaults
        """
        return FilterState()

    @staticmethod
    def get_display_label(state: FilterState, max_len: int = 15) -> str:
        """Get human-readable filter label for status bar.

        Args:
            state: Current filter state
            max_len: Maximum length for category/payee names (truncates if longer)

        Returns:
            Display string like "All" or "Approved | Cat:Groceries"
        """
        parts = [FILTER_LABELS.get(state.mode, "All")]

        if state.category:
            cat_name = state.category.category_name
            if len(cat_name) > max_len:
                cat_name = cat_name[: max_len - 3] + "..."
            parts.append(f"Cat:{cat_name}")

        if state.payee:
            payee = state.payee
            if len(payee) > max_len:
                payee = payee[: max_len - 3] + "..."
            parts.append(f"Payee:{payee}")

        return " | ".join(parts)


@dataclass(frozen=True)
class TagState:
    """Immutable tag state.

    Uses frozenset for immutability - all modifications return new instances.
    """

    tagged_ids: frozenset[str] = field(default_factory=frozenset)

    @property
    def count(self) -> int:
        """Number of tagged transactions."""
        return len(self.tagged_ids)

    @property
    def is_empty(self) -> bool:
        """True if no transactions are tagged."""
        return len(self.tagged_ids) == 0

    def contains(self, transaction_id: str) -> bool:
        """Check if transaction is tagged."""
        return transaction_id in self.tagged_ids


class TagManager:
    """Pure tag operations - testable without UI.

    All methods are static and return new TagState instances.
    """

    @staticmethod
    def toggle(state: TagState, transaction_id: str) -> TagState:
        """Toggle tag on a transaction.

        Args:
            state: Current tag state
            transaction_id: ID of transaction to toggle

        Returns:
            New TagState with tag toggled
        """
        if transaction_id in state.tagged_ids:
            return TagState(state.tagged_ids - {transaction_id})
        return TagState(state.tagged_ids | {transaction_id})

    @staticmethod
    def add(state: TagState, transaction_id: str) -> TagState:
        """Add tag to a transaction."""
        return TagState(state.tagged_ids | {transaction_id})

    @staticmethod
    def remove(state: TagState, transaction_id: str) -> TagState:
        """Remove tag from a transaction."""
        return TagState(state.tagged_ids - {transaction_id})

    @staticmethod
    def clear_all(state: TagState) -> TagState:
        """Clear all tags."""
        return TagState()

    @staticmethod
    def get_tagged_transactions(
        state: TagState,
        all_transactions: list[Transaction],
    ) -> list[Transaction]:
        """Get list of tagged transactions.

        Args:
            state: Current tag state
            all_transactions: All available transactions

        Returns:
            List of transactions that are tagged
        """
        return [t for t in all_transactions if t.id in state.tagged_ids]
