"""Tests for TagState and TagManager.

These tests verify the pure state/selection logic without Textual UI.
"""

from datetime import datetime

import pytest

from ynab_tui.models import Transaction
from ynab_tui.tui.state import TagManager, TagState


def make_test_transaction(id: str = "txn-1") -> Transaction:
    """Create a test transaction."""
    return Transaction(
        id=id,
        date=datetime(2025, 11, 27),
        amount=-44.99,
        payee_name="Test Payee",
        account_name="Checking",
    )


class TestTagState:
    """Tests for TagState dataclass."""

    def test_default_empty(self) -> None:
        """Default TagState should be empty."""
        state = TagState()
        assert state.count == 0
        assert state.is_empty is True

    def test_with_tagged_ids(self) -> None:
        """Can create TagState with tagged IDs."""
        state = TagState(tagged_ids=frozenset({"id-1", "id-2"}))
        assert state.count == 2
        assert state.is_empty is False

    def test_contains(self) -> None:
        """contains should check if ID is tagged."""
        state = TagState(tagged_ids=frozenset({"id-1", "id-2"}))
        assert state.contains("id-1") is True
        assert state.contains("id-3") is False

    def test_is_frozen(self) -> None:
        """TagState should be immutable."""
        state = TagState()
        with pytest.raises(Exception):
            state.tagged_ids = frozenset({"new"})  # type: ignore


class TestTagManager:
    """Tests for TagManager operations."""

    def test_toggle_adds_untagged(self) -> None:
        """toggle on untagged ID should add it."""
        state = TagState()
        new_state = TagManager.toggle(state, "id-1")

        assert new_state.contains("id-1")
        assert new_state.count == 1

    def test_toggle_removes_tagged(self) -> None:
        """toggle on tagged ID should remove it."""
        state = TagState(tagged_ids=frozenset({"id-1", "id-2"}))
        new_state = TagManager.toggle(state, "id-1")

        assert not new_state.contains("id-1")
        assert new_state.contains("id-2")
        assert new_state.count == 1

    def test_add(self) -> None:
        """add should add ID to tags."""
        state = TagState()
        new_state = TagManager.add(state, "id-1")

        assert new_state.contains("id-1")

    def test_add_already_tagged(self) -> None:
        """add on already tagged ID should be idempotent."""
        state = TagState(tagged_ids=frozenset({"id-1"}))
        new_state = TagManager.add(state, "id-1")

        assert new_state.count == 1

    def test_remove(self) -> None:
        """remove should remove ID from tags."""
        state = TagState(tagged_ids=frozenset({"id-1", "id-2"}))
        new_state = TagManager.remove(state, "id-1")

        assert not new_state.contains("id-1")
        assert new_state.count == 1

    def test_remove_not_tagged(self) -> None:
        """remove on not-tagged ID should be no-op."""
        state = TagState(tagged_ids=frozenset({"id-1"}))
        new_state = TagManager.remove(state, "id-2")

        assert new_state.count == 1

    def test_clear_all(self) -> None:
        """clear_all should remove all tags."""
        state = TagState(tagged_ids=frozenset({"id-1", "id-2", "id-3"}))
        new_state = TagManager.clear_all(state)

        assert new_state.is_empty

    def test_get_tagged_transactions(self) -> None:
        """get_tagged_transactions should return tagged transactions."""
        txns = [
            make_test_transaction("t1"),
            make_test_transaction("t2"),
            make_test_transaction("t3"),
        ]
        state = TagState(tagged_ids=frozenset({"t1", "t3"}))

        tagged = TagManager.get_tagged_transactions(state, txns)

        assert len(tagged) == 2
        assert tagged[0].id == "t1"
        assert tagged[1].id == "t3"

    def test_get_tagged_transactions_empty(self) -> None:
        """get_tagged_transactions with no tags should return empty."""
        txns = [make_test_transaction("t1")]
        state = TagState()

        tagged = TagManager.get_tagged_transactions(state, txns)

        assert tagged == []
