"""Tests for HistoryService.

Tests the historical pattern analysis service.
"""

from pathlib import Path

import pytest

from ynab_tui.db.database import Database
from ynab_tui.services.history import HistoryService, PayeePattern


@pytest.fixture
def temp_db(tmp_path: Path) -> Database:
    """Create temporary database."""
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))
    yield db
    db.close()


@pytest.fixture
def history_service(temp_db: Database) -> HistoryService:
    """Create history service."""
    return HistoryService(temp_db)


class TestPayeePattern:
    """Tests for PayeePattern dataclass."""

    def test_create_pattern(self) -> None:
        """Can create a PayeePattern."""
        pattern = PayeePattern(
            payee_name="Amazon.com",
            total_transactions=10,
            categories={"Groceries": {"count": 8, "percentage": 0.8}},
            dominant_category="Groceries",
            dominant_percentage=0.8,
            is_consistent=True,
        )
        assert pattern.payee_name == "Amazon.com"
        assert pattern.is_consistent is True


class TestGetPayeePattern:
    """Tests for get_payee_pattern method."""

    def test_returns_none_for_unknown_payee(self, history_service: HistoryService) -> None:
        """Returns None for payee with no history."""
        result = history_service.get_payee_pattern("Unknown Payee")
        assert result is None

    def test_returns_pattern_for_known_payee(
        self, temp_db: Database, history_service: HistoryService
    ) -> None:
        """Returns pattern for payee with history."""
        # Add categorization history
        temp_db.add_categorization("Amazon.com", "Shopping", "cat-1", 50.0)
        temp_db.add_categorization("Amazon.com", "Shopping", "cat-1", 60.0)
        temp_db.add_categorization("Amazon.com", "Electronics", "cat-2", 100.0)

        result = history_service.get_payee_pattern("Amazon.com")

        assert result is not None
        assert result.payee_name == "Amazon.com"
        assert result.total_transactions == 3
        assert "Shopping" in result.categories
        assert "Electronics" in result.categories

    def test_identifies_consistent_pattern(
        self, temp_db: Database, history_service: HistoryService
    ) -> None:
        """Identifies consistent (>80%) patterns."""
        # 9 out of 10 to same category
        for _ in range(9):
            temp_db.add_categorization("Walmart", "Groceries", "cat-1", 50.0)
        temp_db.add_categorization("Walmart", "Household", "cat-2", 30.0)

        result = history_service.get_payee_pattern("Walmart")

        assert result is not None
        assert result.dominant_category == "Groceries"
        assert result.dominant_percentage == pytest.approx(0.9)
        assert result.is_consistent is True

    def test_identifies_inconsistent_pattern(
        self, temp_db: Database, history_service: HistoryService
    ) -> None:
        """Identifies inconsistent (<80%) patterns."""
        # Split 50/50
        for _ in range(5):
            temp_db.add_categorization("Target", "Groceries", "cat-1", 50.0)
        for _ in range(5):
            temp_db.add_categorization("Target", "Household", "cat-2", 50.0)

        result = history_service.get_payee_pattern("Target")

        assert result is not None
        assert result.is_consistent is False


class TestGetRecentCategorizations:
    """Tests for get_recent_categorizations method."""

    def test_returns_empty_for_unknown(self, history_service: HistoryService) -> None:
        """Returns empty list for unknown payee."""
        result = history_service.get_recent_categorizations("Unknown")
        assert result == []

    def test_returns_recent_records(
        self, temp_db: Database, history_service: HistoryService
    ) -> None:
        """Returns recent categorization records."""
        temp_db.add_categorization("Store", "Cat1", "cat-1", 10.0)
        temp_db.add_categorization("Store", "Cat2", "cat-2", 20.0)

        result = history_service.get_recent_categorizations("Store")

        assert len(result) == 2

    def test_respects_limit(self, temp_db: Database, history_service: HistoryService) -> None:
        """Respects limit parameter."""
        for i in range(10):
            temp_db.add_categorization("Store", f"Cat{i}", f"cat-{i}", 10.0)

        result = history_service.get_recent_categorizations("Store", limit=3)

        assert len(result) == 3


class TestFormatHistoryForPrompt:
    """Tests for format_history_for_prompt method."""

    def test_returns_no_data_message(self, history_service: HistoryService) -> None:
        """Returns no data message for unknown payee."""
        result = history_service.format_history_for_prompt("Unknown")
        assert "No historical data" in result

    def test_formats_history_correctly(
        self, temp_db: Database, history_service: HistoryService
    ) -> None:
        """Formats history as readable string."""
        payee = "Amazon.com"
        temp_db.add_categorization(payee, "Shopping", "cat-1", 50.0)
        temp_db.add_categorization(payee, "Shopping", "cat-1", 60.0)

        result = history_service.format_history_for_prompt(payee)

        assert payee in result
        assert "Shopping" in result
        assert "2 txns" in result or "2 transactions" in result

    def test_includes_strong_pattern_note(
        self, temp_db: Database, history_service: HistoryService
    ) -> None:
        """Includes strong pattern note when consistent."""
        for _ in range(10):
            temp_db.add_categorization("Costco", "Groceries", "cat-1", 100.0)

        result = history_service.format_history_for_prompt("Costco")

        assert "Strong pattern" in result
        assert "Groceries" in result


class TestRecordCategorization:
    """Tests for record_categorization method."""

    def test_records_categorization(
        self, temp_db: Database, history_service: HistoryService
    ) -> None:
        """Records categorization in database."""
        record_id = history_service.record_categorization(
            payee_name="Store",
            category_name="Groceries",
            category_id="cat-1",
            amount=50.0,
        )

        assert record_id > 0

        # Verify it was stored
        history = temp_db.get_payee_history("Store")
        assert len(history) == 1

    def test_records_with_amazon_items(
        self, temp_db: Database, history_service: HistoryService
    ) -> None:
        """Records categorization with Amazon items."""
        record_id = history_service.record_categorization(
            payee_name="Amazon.com",
            category_name="Electronics",
            category_id="cat-1",
            amount=99.99,
            amazon_items=["USB Cable", "Mouse"],
        )

        assert record_id > 0
