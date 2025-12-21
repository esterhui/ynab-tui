"""Tests for TagState, TagManager, and TransactionSelector.

These tests verify the pure state/selection logic without Textual UI.
"""

from datetime import datetime

import pytest

from ynab_tui.models import Transaction
from ynab_tui.tui.state import TagManager, TagState, TransactionSelector


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


class TestTransactionSelector:
    """Tests for TransactionSelector operations."""

    @pytest.fixture
    def sample_transactions(self) -> list[Transaction]:
        """Create sample transactions for testing."""
        return [
            make_test_transaction("t1"),
            make_test_transaction("t2"),
            make_test_transaction("t3"),
        ]

    def test_get_at_index_valid(self, sample_transactions: list[Transaction]) -> None:
        """get_at_index should return transaction at index."""
        txn = TransactionSelector.get_at_index(sample_transactions, 1)

        assert txn is not None
        assert txn.id == "t2"

    def test_get_at_index_none(self, sample_transactions: list[Transaction]) -> None:
        """get_at_index with None should return None."""
        txn = TransactionSelector.get_at_index(sample_transactions, None)

        assert txn is None

    def test_get_at_index_negative(self, sample_transactions: list[Transaction]) -> None:
        """get_at_index with negative should return None."""
        txn = TransactionSelector.get_at_index(sample_transactions, -1)

        assert txn is None

    def test_get_at_index_out_of_bounds(self, sample_transactions: list[Transaction]) -> None:
        """get_at_index beyond end should return None."""
        txn = TransactionSelector.get_at_index(sample_transactions, 100)

        assert txn is None

    def test_get_at_index_empty_list(self) -> None:
        """get_at_index on empty list should return None."""
        txn = TransactionSelector.get_at_index([], 0)

        assert txn is None

    def test_find_index_found(self, sample_transactions: list[Transaction]) -> None:
        """find_index should return index of matching ID."""
        idx = TransactionSelector.find_index(sample_transactions, "t2")

        assert idx == 1

    def test_find_index_not_found(self, sample_transactions: list[Transaction]) -> None:
        """find_index should return None if not found."""
        idx = TransactionSelector.find_index(sample_transactions, "unknown")

        assert idx is None

    def test_find_index_empty_list(self) -> None:
        """find_index on empty list should return None."""
        idx = TransactionSelector.find_index([], "t1")

        assert idx is None

    def test_get_next_index_from_middle(self) -> None:
        """get_next_index should return next index."""
        idx = TransactionSelector.get_next_index(1, total_count=5)

        assert idx == 2

    def test_get_next_index_from_none(self) -> None:
        """get_next_index from None should return 0."""
        idx = TransactionSelector.get_next_index(None, total_count=5)

        assert idx == 0

    def test_get_next_index_at_end_no_wrap(self) -> None:
        """get_next_index at end without wrap should return None."""
        idx = TransactionSelector.get_next_index(4, total_count=5, wrap=False)

        assert idx is None

    def test_get_next_index_at_end_with_wrap(self) -> None:
        """get_next_index at end with wrap should return 0."""
        idx = TransactionSelector.get_next_index(4, total_count=5, wrap=True)

        assert idx == 0

    def test_get_next_index_empty(self) -> None:
        """get_next_index on empty should return None."""
        idx = TransactionSelector.get_next_index(0, total_count=0)

        assert idx is None

    def test_get_prev_index_from_middle(self) -> None:
        """get_prev_index should return previous index."""
        idx = TransactionSelector.get_prev_index(2, total_count=5)

        assert idx == 1

    def test_get_prev_index_from_none(self) -> None:
        """get_prev_index from None should return last index."""
        idx = TransactionSelector.get_prev_index(None, total_count=5)

        assert idx == 4

    def test_get_prev_index_at_start_no_wrap(self) -> None:
        """get_prev_index at start without wrap should return None."""
        idx = TransactionSelector.get_prev_index(0, total_count=5, wrap=False)

        assert idx is None

    def test_get_prev_index_at_start_with_wrap(self) -> None:
        """get_prev_index at start with wrap should return last."""
        idx = TransactionSelector.get_prev_index(0, total_count=5, wrap=True)

        assert idx == 4

    def test_get_prev_index_empty(self) -> None:
        """get_prev_index on empty should return None."""
        idx = TransactionSelector.get_prev_index(0, total_count=0)

        assert idx is None
