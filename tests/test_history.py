"""Tests for HistoryService."""

import pytest

from src.services.history import HistoryService, PayeePattern


@pytest.fixture
def history_service(database):
    """Create HistoryService instance."""
    return HistoryService(database)


class TestPayeePattern:
    """Tests for PayeePattern dataclass."""

    def test_payee_pattern_creation(self):
        """Test creating PayeePattern."""
        pattern = PayeePattern(
            payee_name="Test Store",
            total_transactions=10,
            categories={"Groceries": {"count": 8, "percentage": 0.8}},
            dominant_category="Groceries",
            dominant_percentage=0.8,
            is_consistent=True,
        )
        assert pattern.payee_name == "Test Store"
        assert pattern.total_transactions == 10
        assert pattern.is_consistent is True


class TestHistoryServiceGetPayeePattern:
    """Tests for get_payee_pattern method."""

    def test_get_payee_pattern_no_history(self, history_service):
        """Test get_payee_pattern returns None when no history."""
        result = history_service.get_payee_pattern("Unknown Payee")
        assert result is None

    def test_get_payee_pattern_with_history(self, history_service, database):
        """Test get_payee_pattern returns pattern when history exists."""
        # Add some categorization history
        database.add_categorization(
            payee_name="Trader Joe's",
            category_name="Groceries",
            category_id="cat-001",
            amount=-50.0,
        )
        database.add_categorization(
            payee_name="Trader Joe's",
            category_name="Groceries",
            category_id="cat-001",
            amount=-75.0,
        )

        result = history_service.get_payee_pattern("Trader Joe's")
        assert result is not None
        assert result.payee_name == "Trader Joe's"
        assert result.total_transactions == 2
        assert result.dominant_category == "Groceries"

    def test_get_payee_pattern_is_consistent(self, history_service, database):
        """Test is_consistent flag when >80% goes to one category."""
        # Add 5 categorizations - 4 to Groceries, 1 to other
        for _ in range(4):
            database.add_categorization(
                payee_name="Consistent Store",
                category_name="Groceries",
                category_id="cat-001",
                amount=-50.0,
            )
        database.add_categorization(
            payee_name="Consistent Store",
            category_name="Dining",
            category_id="cat-002",
            amount=-25.0,
        )

        result = history_service.get_payee_pattern("Consistent Store")
        assert result is not None
        assert result.is_consistent is True
        assert result.dominant_percentage >= 0.80

    def test_get_payee_pattern_not_consistent(self, history_service, database):
        """Test is_consistent is False when less than 80% to one category."""
        # Add 2 to Groceries, 2 to Dining
        database.add_categorization("Split Store", "Groceries", "cat-001", -50.0)
        database.add_categorization("Split Store", "Groceries", "cat-001", -50.0)
        database.add_categorization("Split Store", "Dining", "cat-002", -25.0)
        database.add_categorization("Split Store", "Dining", "cat-002", -25.0)

        result = history_service.get_payee_pattern("Split Store")
        assert result is not None
        assert result.is_consistent is False
        assert result.dominant_percentage == 0.5


class TestHistoryServiceGetRecentCategorizations:
    """Tests for get_recent_categorizations method."""

    def test_get_recent_categorizations_empty(self, history_service):
        """Test get_recent_categorizations returns empty list when no history."""
        result = history_service.get_recent_categorizations("Unknown Payee")
        assert result == []

    def test_get_recent_categorizations_with_history(self, history_service, database):
        """Test get_recent_categorizations returns records."""
        database.add_categorization(
            payee_name="Coffee Shop",
            category_name="Dining",
            category_id="cat-001",
            amount=-5.0,
        )
        database.add_categorization(
            payee_name="Coffee Shop",
            category_name="Dining",
            category_id="cat-001",
            amount=-6.0,
        )

        result = history_service.get_recent_categorizations("Coffee Shop")
        assert len(result) == 2

    def test_get_recent_categorizations_limit(self, history_service, database):
        """Test get_recent_categorizations respects limit."""
        for i in range(10):
            database.add_categorization(
                payee_name="Frequent Store",
                category_name="Shopping",
                category_id="cat-001",
                amount=-i * 10.0,
            )

        result = history_service.get_recent_categorizations("Frequent Store", limit=5)
        assert len(result) == 5


class TestHistoryServiceFormatHistory:
    """Tests for format_history_for_prompt method."""

    def test_format_history_no_data(self, history_service):
        """Test format_history_for_prompt with no history."""
        result = history_service.format_history_for_prompt("Unknown Payee")
        assert "No historical data" in result

    def test_format_history_with_data(self, history_service, database):
        """Test format_history_for_prompt formats correctly."""
        database.add_categorization(
            payee_name="Format Test",
            category_name="Groceries",
            category_id="cat-001",
            amount=-50.0,
        )
        database.add_categorization(
            payee_name="Format Test",
            category_name="Groceries",
            category_id="cat-001",
            amount=-75.0,
        )

        result = history_service.format_history_for_prompt("Format Test")
        assert "Format Test" in result
        assert "2 txns" in result
        assert "Groceries" in result

    def test_format_history_consistent_pattern(self, history_service, database):
        """Test format_history_for_prompt shows consistent pattern."""
        for _ in range(5):
            database.add_categorization(
                payee_name="Consistent Pattern",
                category_name="Utilities",
                category_id="cat-001",
                amount=-100.0,
            )

        result = history_service.format_history_for_prompt("Consistent Pattern")
        assert "Strong pattern" in result
        assert "Utilities" in result


class TestHistoryServiceRecordCategorization:
    """Tests for record_categorization method."""

    def test_record_categorization_basic(self, history_service, database):
        """Test recording a categorization."""
        record_id = history_service.record_categorization(
            payee_name="New Store",
            category_name="Shopping",
            category_id="cat-001",
            amount=-99.99,
        )
        assert record_id > 0

        # Verify it was recorded
        pattern = history_service.get_payee_pattern("New Store")
        assert pattern is not None
        assert pattern.total_transactions == 1

    def test_record_categorization_with_amazon_items(self, history_service, database):
        """Test recording categorization with Amazon items."""
        record_id = history_service.record_categorization(
            payee_name="Amazon",
            category_name="Electronics",
            category_id="cat-001",
            amount=-49.99,
            amazon_items=["USB Cable", "Phone Case"],
        )
        assert record_id > 0

    def test_record_categorization_without_amount(self, history_service, database):
        """Test recording categorization without amount."""
        record_id = history_service.record_categorization(
            payee_name="No Amount Store",
            category_name="Misc",
            category_id="cat-001",
            amount=None,
        )
        assert record_id > 0
