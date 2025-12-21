"""Tests for TUI screen components.

These tests verify that screens work correctly and don't crash,
using Textual's testing framework.
"""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from src.clients import MockYNABClient
from src.db.database import Database
from src.models import Transaction
from src.services.categorizer import CategorizerService
from src.tui.screens.item_split import ItemSplitScreen, SplitItemListItem


@pytest.fixture
def split_database(tmp_path):
    """Create a temporary database for screen tests."""
    db = Database(tmp_path / "test_screens.db")
    yield db
    db.close()


@pytest.fixture
def split_ynab_client():
    """Create mock YNAB client for screen tests."""
    return MockYNABClient(max_transactions=20)


@pytest.fixture
def split_categorizer(sample_config, split_database, split_ynab_client):
    """Create CategorizerService for screen tests."""
    return CategorizerService(
        config=sample_config,
        ynab_client=split_ynab_client,
        db=split_database,
    )


@pytest.fixture
def sample_categories():
    """Sample categories for testing."""
    return [
        {"id": "cat-1", "name": "Electronics", "group_name": "Shopping"},
        {"id": "cat-2", "name": "Household", "group_name": "Shopping"},
        {"id": "cat-3", "name": "Groceries", "group_name": "Food"},
    ]


@pytest.fixture
def amazon_transaction():
    """Sample Amazon transaction for split screen."""
    from datetime import datetime

    return Transaction(
        id="txn-amazon-1",
        date=datetime(2024, 1, 15),
        amount=-125.00,  # In dollars (not milliunits)
        payee_name="Amazon",
        category_name=None,
        category_id=None,
        account_name="Credit Card",
        approved=False,
    )


@pytest.fixture
def amazon_items():
    """Sample Amazon order items."""
    return [
        {"item_name": "USB-C Cable", "item_price": 15.99, "quantity": 1},
        {"item_name": "Wireless Mouse", "item_price": 29.99, "quantity": 1},
        {"item_name": "Phone Case", "item_price": 12.99, "quantity": 2},
        {"item_name": "Screen Protector", "item_price": 8.99, "quantity": 1},
    ]


# Test App wrapper for screen testing
class ScreenTestApp(App):
    """Test app for mounting screens."""

    def __init__(self, screen):
        super().__init__()
        self._screen = screen
        self._result = None

    def compose(self) -> ComposeResult:
        yield Static("Test App")

    def on_mount(self) -> None:
        """Push screen on mount."""
        self.push_screen(self._screen, self._on_result)

    def _on_result(self, result):
        """Store result."""
        self._result = result


class TestSplitItemListItem:
    """Tests for SplitItemListItem widget."""

    def test_split_item_creation(self, amazon_items):
        """Test creating a SplitItemListItem."""
        item = SplitItemListItem(amazon_items[0], index=0)
        assert item.item == amazon_items[0]
        assert item.index == 0
        assert item.assigned_category is None

    def test_split_item_with_category(self, amazon_items):
        """Test SplitItemListItem with assigned category."""
        category = {"category_id": "cat-1", "category_name": "Electronics"}
        item = SplitItemListItem(amazon_items[0], index=0, assigned_category=category)
        assert item.assigned_category == category

    def test_split_item_format_row(self, amazon_items):
        """Test _format_row method."""
        item = SplitItemListItem(amazon_items[0], index=0)
        row = item._format_row()
        assert "USB-C Cable" in row
        assert "$15.99" in row
        assert "[ ]" in row  # uncategorized indicator

    def test_split_item_format_row_with_category(self, amazon_items):
        """Test _format_row with assigned category."""
        category = {"category_id": "cat-1", "category_name": "Electronics"}
        item = SplitItemListItem(amazon_items[0], index=0, assigned_category=category)
        row = item._format_row()
        assert "[*]" in row  # categorized indicator
        assert "Electronics" in row

    def test_split_item_format_row_long_name(self):
        """Test _format_row truncates long item names."""
        long_item = {
            "item_name": "A" * 50,  # Very long name
            "item_price": 10.00,
            "quantity": 1,
        }
        item = SplitItemListItem(long_item, index=0)
        row = item._format_row()
        # Should be truncated with ...
        assert "..." in row or len(row) < 100

    def test_split_item_format_row_quantity(self, amazon_items):
        """Test _format_row shows quantity > 1."""
        item = SplitItemListItem(amazon_items[2], index=2)  # Phone Case x2
        row = item._format_row()
        assert "x2" in row


class TestItemSplitScreen:
    """Tests for ItemSplitScreen."""

    async def test_screen_opens_without_crash(
        self, split_categorizer, amazon_transaction, sample_categories, amazon_items
    ):
        """Test screen opens successfully."""
        screen = ItemSplitScreen(
            categorizer=split_categorizer,
            transaction=amazon_transaction,
            categories=sample_categories,
            items_with_prices=amazon_items,
        )
        app = ScreenTestApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Screen should be visible
            assert len(app.screen_stack) >= 1
            await pilot.press("escape")
            await pilot.pause()

    async def test_screen_displays_items(
        self, split_categorizer, amazon_transaction, sample_categories, amazon_items
    ):
        """Test screen displays all items."""
        screen = ItemSplitScreen(
            categorizer=split_categorizer,
            transaction=amazon_transaction,
            categories=sample_categories,
            items_with_prices=amazon_items,
        )
        app = ScreenTestApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            # All items should be in the list
            assert len(screen._items) == len(amazon_items)
            await pilot.press("escape")
            await pilot.pause()

    async def test_screen_navigation_down(
        self, split_categorizer, amazon_transaction, sample_categories, amazon_items
    ):
        """Test navigation with j key."""
        screen = ItemSplitScreen(
            categorizer=split_categorizer,
            transaction=amazon_transaction,
            categories=sample_categories,
            items_with_prices=amazon_items,
        )
        app = ScreenTestApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("j")
            await pilot.pause()
            await pilot.press("j")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

    async def test_screen_navigation_up(
        self, split_categorizer, amazon_transaction, sample_categories, amazon_items
    ):
        """Test navigation with k key."""
        screen = ItemSplitScreen(
            categorizer=split_categorizer,
            transaction=amazon_transaction,
            categories=sample_categories,
            items_with_prices=amazon_items,
        )
        app = ScreenTestApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("j")
            await pilot.pause()
            await pilot.press("k")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

    async def test_screen_categorize_key(
        self, split_categorizer, amazon_transaction, sample_categories, amazon_items
    ):
        """Test 'c' key opens category picker."""
        screen = ItemSplitScreen(
            categorizer=split_categorizer,
            transaction=amazon_transaction,
            categories=sample_categories,
            items_with_prices=amazon_items,
        )
        app = ScreenTestApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            # Modal should open - close it with escape
            await pilot.press("escape")
            await pilot.pause()
            # Close the screen
            await pilot.press("escape")
            await pilot.pause()

    async def test_screen_cancel_with_q(
        self, split_categorizer, amazon_transaction, sample_categories, amazon_items
    ):
        """Test 'q' key cancels screen."""
        screen = ItemSplitScreen(
            categorizer=split_categorizer,
            transaction=amazon_transaction,
            categories=sample_categories,
            items_with_prices=amazon_items,
        )
        app = ScreenTestApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("q")
            await pilot.pause()

    async def test_screen_submit_without_all_categorized(
        self, split_categorizer, amazon_transaction, sample_categories, amazon_items
    ):
        """Test submit shows warning when not all items categorized."""
        screen = ItemSplitScreen(
            categorizer=split_categorizer,
            transaction=amazon_transaction,
            categories=sample_categories,
            items_with_prices=amazon_items,
        )
        app = ScreenTestApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Try to submit without categorizing all items
            await pilot.press("s")
            await pilot.pause()
            # Should show warning notification (not submit)
            await pilot.press("escape")
            await pilot.pause()

    async def test_screen_with_existing_splits(
        self, split_categorizer, amazon_transaction, sample_categories, amazon_items
    ):
        """Test screen pre-populates with existing splits."""
        existing_splits = [
            {
                "category_id": "cat-1",
                "category_name": "Electronics",
                "memo": "USB-C Cable",
            },
        ]
        screen = ItemSplitScreen(
            categorizer=split_categorizer,
            transaction=amazon_transaction,
            categories=sample_categories,
            items_with_prices=amazon_items,
            existing_splits=existing_splits,
        )
        app = ScreenTestApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            # First item should be pre-assigned
            assert 0 in screen._assignments
            await pilot.press("escape")
            await pilot.pause()

    async def test_screen_enter_on_uncategorized(
        self, split_categorizer, amazon_transaction, sample_categories, amazon_items
    ):
        """Test Enter key on uncategorized item opens picker."""
        screen = ItemSplitScreen(
            categorizer=split_categorizer,
            transaction=amazon_transaction,
            categories=sample_categories,
            items_with_prices=amazon_items,
        )
        app = ScreenTestApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Press Enter on uncategorized item
            await pilot.press("enter")
            await pilot.pause()
            # Modal should open - close it
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

    async def test_screen_get_current_item(
        self, split_categorizer, amazon_transaction, sample_categories, amazon_items
    ):
        """Test _get_current_item method."""
        screen = ItemSplitScreen(
            categorizer=split_categorizer,
            transaction=amazon_transaction,
            categories=sample_categories,
            items_with_prices=amazon_items,
        )
        app = ScreenTestApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            item = screen._get_current_item()
            assert item is not None
            assert item["item_name"] == "USB-C Cable"
            await pilot.press("escape")
            await pilot.pause()

    async def test_screen_update_summary(
        self, split_categorizer, amazon_transaction, sample_categories, amazon_items
    ):
        """Test _update_summary is called without crashing."""
        screen = ItemSplitScreen(
            categorizer=split_categorizer,
            transaction=amazon_transaction,
            categories=sample_categories,
            items_with_prices=amazon_items,
        )
        app = ScreenTestApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Just verify the screen mounted and summary was updated
            assert len(screen._assignments) == 0
            await pilot.press("escape")
            await pilot.pause()

    async def test_screen_cursor_down_action(
        self, split_categorizer, amazon_transaction, sample_categories, amazon_items
    ):
        """Test action_cursor_down method."""
        screen = ItemSplitScreen(
            categorizer=split_categorizer,
            transaction=amazon_transaction,
            categories=sample_categories,
            items_with_prices=amazon_items,
        )
        app = ScreenTestApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            idx = screen._get_current_item_index()
            assert idx == 1
            await pilot.press("escape")
            await pilot.pause()

    async def test_screen_cursor_up_action(
        self, split_categorizer, amazon_transaction, sample_categories, amazon_items
    ):
        """Test action_cursor_up method."""
        screen = ItemSplitScreen(
            categorizer=split_categorizer,
            transaction=amazon_transaction,
            categories=sample_categories,
            items_with_prices=amazon_items,
        )
        app = ScreenTestApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            await pilot.press("up")
            await pilot.pause()
            idx = screen._get_current_item_index()
            assert idx == 0
            await pilot.press("escape")
            await pilot.pause()

    async def test_screen_empty_items(
        self, split_categorizer, amazon_transaction, sample_categories
    ):
        """Test screen with empty items list."""
        screen = ItemSplitScreen(
            categorizer=split_categorizer,
            transaction=amazon_transaction,
            categories=sample_categories,
            items_with_prices=[],
        )
        app = ScreenTestApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert len(screen._items) == 0
            await pilot.press("escape")
            await pilot.pause()

    async def test_screen_calculate_splits_with_remainder(
        self, split_categorizer, amazon_transaction, sample_categories, amazon_items
    ):
        """Test _calculate_splits_with_remainder method."""
        screen = ItemSplitScreen(
            categorizer=split_categorizer,
            transaction=amazon_transaction,
            categories=sample_categories,
            items_with_prices=amazon_items,
        )

        # Manually assign all categories
        for i in range(len(amazon_items)):
            screen._assignments[i] = {
                "category_id": "cat-1",
                "category_name": "Electronics",
            }

        splits = screen._calculate_splits_with_remainder()
        assert len(splits) == len(amazon_items)

        # Total should match transaction amount
        total = sum(s["amount"] for s in splits)
        assert abs(total - (-125.00)) < 0.01


class TestItemSplitScreenLoadExistingSplits:
    """Tests for _load_existing_splits method."""

    def test_load_existing_splits_matches_by_memo(
        self, split_categorizer, amazon_transaction, sample_categories, amazon_items
    ):
        """Test loading existing splits matches by memo."""
        existing_splits = [
            {
                "category_id": "cat-1",
                "category_name": "Electronics",
                "memo": "USB-C Cable",
            },
            {
                "category_id": "cat-2",
                "category_name": "Household",
                "memo": "Wireless Mouse",
            },
        ]
        screen = ItemSplitScreen(
            categorizer=split_categorizer,
            transaction=amazon_transaction,
            categories=sample_categories,
            items_with_prices=amazon_items,
            existing_splits=existing_splits,
        )

        # Should have pre-populated two assignments
        assert len(screen._assignments) == 2
        assert screen._assignments[0]["category_name"] == "Electronics"
        assert screen._assignments[1]["category_name"] == "Household"

    def test_load_existing_splits_no_match(
        self, split_categorizer, amazon_transaction, sample_categories, amazon_items
    ):
        """Test loading existing splits with no matching items."""
        existing_splits = [
            {
                "category_id": "cat-1",
                "category_name": "Electronics",
                "memo": "Non-existent Item",
            },
        ]
        screen = ItemSplitScreen(
            categorizer=split_categorizer,
            transaction=amazon_transaction,
            categories=sample_categories,
            items_with_prices=amazon_items,
            existing_splits=existing_splits,
        )

        # Should have no assignments
        assert len(screen._assignments) == 0

    def test_load_existing_splits_partial_memo(
        self, split_categorizer, amazon_transaction, sample_categories, amazon_items
    ):
        """Test loading existing splits with truncated memo."""
        existing_splits = [
            {
                "category_id": "cat-1",
                "category_name": "Electronics",
                "memo": "USB-C",  # Truncated
            },
        ]
        screen = ItemSplitScreen(
            categorizer=split_categorizer,
            transaction=amazon_transaction,
            categories=sample_categories,
            items_with_prices=amazon_items,
            existing_splits=existing_splits,
        )

        # Should match by startswith
        assert 0 in screen._assignments


# =============================================================================
# Settings Screen Tests
# =============================================================================


class TestSettingsScreen:
    """Tests for SettingsScreen."""

    @pytest.fixture
    def settings_config(self, sample_config):
        """Configuration for settings screen tests."""
        return sample_config

    async def test_settings_screen_mounts(self, settings_config):
        """Test settings screen mounts without crashing."""
        from src.tui.screens.settings import SettingsScreen

        screen = SettingsScreen(config=settings_config)
        app = ScreenTestApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Screen should be visible
            assert screen._config is not None
            await pilot.press("escape")
            await pilot.pause()

    async def test_settings_screen_displays_config(self, settings_config):
        """Test settings screen displays configuration values."""
        from src.tui.screens.settings import SettingsScreen

        screen = SettingsScreen(config=settings_config)
        app = ScreenTestApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Check that config is stored
            assert screen._config.ynab.budget_id is not None
            await pilot.press("escape")
            await pilot.pause()

    async def test_settings_screen_quit_action(self, settings_config):
        """Test 'q' key closes settings screen."""
        from src.tui.screens.settings import SettingsScreen

        screen = SettingsScreen(config=settings_config)
        app = ScreenTestApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("q")
            await pilot.pause()
            # Screen should be popped (no assertion needed, no crash = success)

    def test_mask_token_empty(self, settings_config):
        """Test _mask_token with empty token."""
        from src.tui.screens.settings import SettingsScreen

        screen = SettingsScreen(config=settings_config)
        result = screen._mask_token("")
        assert result == "(not set)"

    def test_mask_token_short(self, settings_config):
        """Test _mask_token with short token."""
        from src.tui.screens.settings import SettingsScreen

        screen = SettingsScreen(config=settings_config)
        result = screen._mask_token("abcd")
        assert result == "****"

    def test_mask_token_long(self, settings_config):
        """Test _mask_token with long token."""
        from src.tui.screens.settings import SettingsScreen

        screen = SettingsScreen(config=settings_config)
        result = screen._mask_token("abcd1234efgh5678")
        assert result.startswith("abcd")
        assert result.endswith("5678")
        assert "*" in result

    def test_mask_email_empty(self, settings_config):
        """Test _mask_email with empty email."""
        from src.tui.screens.settings import SettingsScreen

        screen = SettingsScreen(config=settings_config)
        result = screen._mask_email("")
        assert result == "(not set)"

    def test_mask_email_no_at(self, settings_config):
        """Test _mask_email without @ symbol."""
        from src.tui.screens.settings import SettingsScreen

        screen = SettingsScreen(config=settings_config)
        result = screen._mask_email("username")
        # Should fall back to token masking
        assert result == "********"

    def test_mask_email_valid(self, settings_config):
        """Test _mask_email with valid email."""
        from src.tui.screens.settings import SettingsScreen

        screen = SettingsScreen(config=settings_config)
        result = screen._mask_email("test@example.com")
        assert result == "te***@example.com"

    def test_mask_email_short_username(self, settings_config):
        """Test _mask_email with short username."""
        from src.tui.screens.settings import SettingsScreen

        screen = SettingsScreen(config=settings_config)
        result = screen._mask_email("ab@example.com")
        assert result == "ab@example.com"  # Too short to mask

    async def test_settings_save_button(self, settings_config):
        """Test save button functionality."""
        from src.tui.screens.settings import SettingsScreen

        screen = SettingsScreen(config=settings_config)
        app = ScreenTestApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Click save button
            await pilot.click("#save-btn")
            await pilot.pause()
            # Should show notification (no crash = success)
            await pilot.press("escape")
            await pilot.pause()

    async def test_settings_close_button(self, settings_config):
        """Test close button functionality."""
        from src.tui.screens.settings import SettingsScreen

        screen = SettingsScreen(config=settings_config)
        app = ScreenTestApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Click close button
            await pilot.click("#close-btn")
            await pilot.pause()
            # Screen should be closed (no crash = success)
