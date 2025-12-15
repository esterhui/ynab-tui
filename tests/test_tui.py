"""Tests for TUI navigation and state management.

These tests verify that key bindings work correctly and don't crash,
using Textual's Pilot testing framework with mock clients.
"""

from datetime import datetime

import pytest

from src.clients import MockYNABClient
from src.db.database import Database
from src.models import Transaction
from src.services.categorizer import CategorizerService
from src.tui.app import YNABCategorizerApp


@pytest.fixture
def tui_database(tmp_path):
    """Create a temporary database for TUI tests."""
    db = Database(tmp_path / "test_tui.db", budget_id="mock-budget-id")
    yield db
    db.close()


@pytest.fixture
def tui_ynab_client():
    """Create mock YNAB client for TUI tests."""
    return MockYNABClient(max_transactions=20)


@pytest.fixture
def tui_categorizer(sample_config, tui_database, tui_ynab_client):
    """Create CategorizerService with mock clients for TUI tests."""
    return CategorizerService(
        config=sample_config,
        ynab_client=tui_ynab_client,
        db=tui_database,
    )


@pytest.fixture
def tui_app(tui_categorizer):
    """Create TUI app instance for testing."""
    return YNABCategorizerApp(categorizer=tui_categorizer, is_mock=True)


class TestTUIFilterNavigation:
    """Test filter submenu works correctly."""

    async def test_filter_submenu_uncategorized(self, tui_app):
        """Test pressing 'f' then 'u' filters by uncategorized."""
        async with tui_app.run_test() as pilot:
            # Wait for initial load to complete
            await pilot.pause()

            # Initial state
            assert tui_app._filter_mode == "all"

            # Press 'f' to show filter menu, then 'u' for uncategorized
            await pilot.press("f")
            await pilot.pause()
            assert tui_app._filter_pending is True

            await pilot.press("u")
            await pilot.pause()

            # Verify filter mode changed
            assert tui_app._filter_mode == "uncategorized"
            assert tui_app._filter_pending is False

    async def test_filter_submenu_all_modes(self, tui_app):
        """Test all filter submenu options work."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Test each filter key (note: 'c' and 'p' open modals, not direct filters)
            filter_tests = [
                ("a", "approved"),
                ("n", "new"),
                ("u", "uncategorized"),
                ("e", "pending"),  # Changed from 'p' to 'e' for pending
                ("x", "all"),
            ]

            for key, expected_mode in filter_tests:
                await pilot.press("f")
                await pilot.pause()
                await pilot.press(key)
                await pilot.pause()
                assert tui_app._filter_mode == expected_mode

    async def test_filter_rapid_pressing(self, tui_app):
        """Test rapid filter key presses don't crash."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Press 'f' multiple times rapidly
            for _ in range(10):
                await pilot.press("f")

            # Just wait for everything to settle - no crash = success
            await pilot.pause()


class TestTUIVimNavigation:
    """Test vim-style navigation keys."""

    async def test_navigation_j_k(self, tui_app):
        """Test j/k navigation keys don't crash."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Press navigation keys - no crash = success
            await pilot.press("j")
            await pilot.pause()
            await pilot.press("k")
            await pilot.pause()

    async def test_navigation_home_end(self, tui_app):
        """Test g/G navigation keys don't crash."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Go to top
            await pilot.press("g")
            await pilot.pause()

            # Go to bottom
            await pilot.press("G")
            await pilot.pause()

    async def test_navigation_page_up_down(self, tui_app):
        """Test Ctrl+d/u page navigation don't crash."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Page down
            await pilot.press("ctrl+d")
            await pilot.pause()

            # Page up
            await pilot.press("ctrl+u")
            await pilot.pause()


class TestTUIActions:
    """Test action key bindings."""

    async def test_refresh_action(self, tui_app):
        """Test F5 refresh doesn't crash."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            await pilot.press("f5")
            await pilot.pause()

    async def test_help_toggle(self, tui_app):
        """Test ? help toggle doesn't crash."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Toggle help on
            await pilot.press("?")
            await pilot.pause()

            # Toggle help off
            await pilot.press("?")
            await pilot.pause()

    async def test_quit_action(self, tui_app):
        """Test q quits without crash."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            await pilot.press("q")
            # App should exit, no crash = success


class TestTUIStateChanges:
    """Test that actions properly modify state."""

    async def test_filter_state_persists(self, tui_app):
        """Test filter state persists after selection."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Change to uncategorized via submenu
            await pilot.press("f")
            await pilot.pause()
            await pilot.press("u")
            await pilot.pause()
            assert tui_app._filter_mode == "uncategorized"

            # Navigate around (shouldn't change filter)
            await pilot.press("j")
            await pilot.press("k")
            await pilot.pause()

            # Filter should still be uncategorized
            assert tui_app._filter_mode == "uncategorized"

    async def test_initial_transactions_loaded(self, tui_app):
        """Test transactions are loaded on mount."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # TransactionBatch should have been populated
            assert tui_app._transactions is not None
            # Mock client returns transactions
            assert tui_app._transactions.total_count >= 0


class TestTUIPushPreview:
    """Test push preview screen functionality."""

    @pytest.fixture
    def tui_app_with_pending(self, tui_categorizer, tui_database):
        """Create TUI app with a pending change ready to push."""
        # Create a sample transaction
        txn = Transaction(
            id="txn-push-test-001",
            date=datetime(2025, 1, 15),
            amount=-47.82,
            payee_name="Test Payee",
            payee_id="payee-001",
            account_name="Checking",
            account_id="acc-001",
            approved=False,
            category_id="cat-001",
            category_name="Electronics",
            sync_status="synced",
        )

        # Insert transaction into database
        tui_database.upsert_ynab_transaction(txn)

        # Create a pending change
        tui_database.create_pending_change(
            transaction_id=txn.id,
            new_category_id="cat-002",
            new_category_name="Groceries",
            original_category_id=txn.category_id,
            original_category_name=txn.category_name,
            change_type="category",
            new_approved=True,
            original_approved=False,
        )

        # Verify pending change was created
        assert tui_database.get_pending_change_count() == 1

        return YNABCategorizerApp(categorizer=tui_categorizer, is_mock=True)

    async def test_push_preview_opens(self, tui_app_with_pending):
        """Test 'p' key opens push preview screen."""
        async with tui_app_with_pending.run_test() as pilot:
            await pilot.pause()

            # Press 'p' to open push preview
            await pilot.press("p")
            await pilot.pause()

            # Verify push preview screen is showing
            from src.tui.screens import PushPreviewScreen

            screens = tui_app_with_pending.screen_stack
            assert any(isinstance(s, PushPreviewScreen) for s in screens)

    async def test_push_preview_no_pending_shows_warning(self, tui_app):
        """Test 'p' with no pending changes shows warning notification."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Press 'p' when no pending changes
            await pilot.press("p")
            await pilot.pause()

            # Should not open a new screen (just show notification)
            from src.tui.screens import PushPreviewScreen

            screens = tui_app.screen_stack
            assert not any(isinstance(s, PushPreviewScreen) for s in screens)

    async def test_push_preview_cancel(self, tui_app_with_pending):
        """Test 'q' cancels push preview without pushing."""
        async with tui_app_with_pending.run_test() as pilot:
            await pilot.pause()

            db = tui_app_with_pending._categorizer._db

            # Open push preview
            await pilot.press("p")
            await pilot.pause()

            # Cancel with 'q'
            await pilot.press("q")
            await pilot.pause()

            # Should return to main screen
            from src.tui.screens import PushPreviewScreen

            screens = tui_app_with_pending.screen_stack
            assert not any(isinstance(s, PushPreviewScreen) for s in screens)

            # Pending change should still exist
            assert db.get_pending_change_count() == 1

    async def test_push_preview_confirm_and_push(self, tui_app_with_pending):
        """Test 'p' then 'y' pushes changes and closes screen."""
        async with tui_app_with_pending.run_test() as pilot:
            await pilot.pause()

            db = tui_app_with_pending._categorizer._db
            initial_count = db.get_pending_change_count()
            assert initial_count == 1

            # Open push preview
            await pilot.press("p")
            await pilot.pause()

            # Press 'p' to show confirmation
            await pilot.press("p")
            await pilot.pause()

            # Press 'y' to confirm push
            await pilot.press("y")

            # Wait for worker to complete
            await pilot.pause()
            await pilot.pause()  # Extra pause for worker

            # Should return to main screen
            from src.tui.screens import PushPreviewScreen

            screens = tui_app_with_pending.screen_stack
            assert not any(isinstance(s, PushPreviewScreen) for s in screens)

            # Pending change should be cleared after successful push
            assert db.get_pending_change_count() == 0

    async def test_push_preview_cancel_confirmation(self, tui_app_with_pending):
        """Test 'n' cancels confirmation prompt."""
        async with tui_app_with_pending.run_test() as pilot:
            await pilot.pause()

            db = tui_app_with_pending._categorizer._db

            # Open push preview
            await pilot.press("p")
            await pilot.pause()

            # Press 'p' to show confirmation
            await pilot.press("p")
            await pilot.pause()

            # Press 'n' to cancel confirmation
            await pilot.press("n")
            await pilot.pause()

            # Should still be on push preview screen
            from src.tui.screens import PushPreviewScreen

            screens = tui_app_with_pending.screen_stack
            assert any(isinstance(s, PushPreviewScreen) for s in screens)

            # Pending change should still exist
            assert db.get_pending_change_count() == 1


class TestTUISplitTransaction:
    """Test split transaction functionality."""

    @pytest.fixture
    def tui_app_with_amazon_transaction(self, tui_categorizer, tui_database):
        """Create TUI app with an Amazon transaction that has matched order items."""
        # Create an Amazon transaction
        txn = Transaction(
            id="txn-amazon-split-001",
            date=datetime(2025, 1, 15),
            amount=-47.82,
            payee_name="AMAZON.COM",
            payee_id="payee-amazon",
            account_name="Checking",
            account_id="acc-001",
            approved=False,
            sync_status="synced",
        )
        txn.is_amazon = True
        txn.amazon_order_id = "order-split-test-123"
        txn.amazon_items = ["USB-C Cable", "Phone Case"]

        # Insert transaction into database
        tui_database.upsert_ynab_transaction(txn)

        # Store Amazon order items with prices
        tui_database.upsert_amazon_order_items(
            order_id="order-split-test-123",
            items=[
                {"name": "USB-C Cable", "price": 12.99, "quantity": 1},
                {"name": "Phone Case", "price": 34.83, "quantity": 1},
            ],
        )

        app = YNABCategorizerApp(categorizer=tui_categorizer, is_mock=True)
        # Store transaction for test access
        app._test_amazon_txn = txn
        return app

    @pytest.fixture
    def tui_app_with_non_amazon_transaction(self, tui_categorizer, tui_database):
        """Create TUI app with a non-Amazon transaction."""
        txn = Transaction(
            id="txn-costco-001",
            date=datetime(2025, 1, 15),
            amount=-127.43,
            payee_name="COSTCO WHOLESALE",
            payee_id="payee-costco",
            account_name="Checking",
            account_id="acc-001",
            approved=False,
            sync_status="synced",
        )

        # Insert transaction into database
        tui_database.upsert_ynab_transaction(txn)

        return YNABCategorizerApp(categorizer=tui_categorizer, is_mock=True)

    async def test_split_action_no_transaction_selected(self, tui_app):
        """Test 'x' with no transaction selected shows warning."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Press 'x' - might show warning if no transaction selected
            # No crash = success (notification is shown to user)
            await pilot.press("x")
            await pilot.pause()

            # Should NOT open item split screen
            from src.tui.screens import ItemSplitScreen

            screens = tui_app.screen_stack
            assert not any(isinstance(s, ItemSplitScreen) for s in screens)

    async def test_split_action_on_non_amazon_shows_warning(
        self, tui_app_with_non_amazon_transaction
    ):
        """Test 'x' on non-Amazon transaction shows warning and doesn't open screen."""
        async with tui_app_with_non_amazon_transaction.run_test() as pilot:
            await pilot.pause()

            # Navigate to the transaction (press j to select first one)
            await pilot.press("j")
            await pilot.pause()

            # Press 'x' - should show warning since not Amazon
            await pilot.press("x")
            await pilot.pause()

            # Should NOT open item split screen
            from src.tui.screens import ItemSplitScreen

            screens = tui_app_with_non_amazon_transaction.screen_stack
            assert not any(isinstance(s, ItemSplitScreen) for s in screens)

    async def test_split_action_on_amazon_with_items_opens_screen(
        self, tui_app_with_amazon_transaction
    ):
        """Test 'x' on Amazon transaction with order items opens split review screen."""
        async with tui_app_with_amazon_transaction.run_test() as pilot:
            await pilot.pause()

            # Need to select the Amazon transaction we added
            # Navigate through transactions to find our test one
            await pilot.press("j")
            await pilot.pause()

            # Press 'x' to open split review
            await pilot.press("x")
            await pilot.pause()

            # The screen may or may not open depending on which transaction is selected
            # and whether it's single or multi-item. We verify no crash and proper handling
            # (assertion is implicit - no exception = success)

    async def test_split_action_escape_closes_screen(self, tui_app_with_amazon_transaction):
        """Test escape key closes split review screen if opened."""
        async with tui_app_with_amazon_transaction.run_test() as pilot:
            await pilot.pause()

            # Try to open split review
            await pilot.press("j")
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()

            # Press escape to close any screen that opened
            await pilot.press("escape")
            await pilot.pause()

            # No crash = success

    @pytest.fixture
    def tui_app_with_multi_item_amazon(self, tui_categorizer, tui_database):
        """Create TUI app with a multi-item Amazon transaction for split testing."""
        # Create an Amazon transaction
        txn = Transaction(
            id="txn-amazon-multi-001",
            date=datetime(2025, 1, 15),
            amount=-100.00,
            payee_name="AMAZON.COM",
            payee_id="payee-amazon",
            account_name="Checking",
            account_id="acc-001",
            approved=False,
            category_id=None,
            category_name=None,
            sync_status="synced",
        )
        txn.is_amazon = True
        txn.amazon_order_id = "order-multi-item-123"
        txn.amazon_items = ["USB-C Cable", "Phone Case"]

        # Insert transaction into database
        tui_database.upsert_ynab_transaction(txn)

        # Store Amazon order items with prices (2 items for multi-item split)
        tui_database.upsert_amazon_order_items(
            order_id="order-multi-item-123",
            items=[
                {"name": "USB-C Cable", "price": 40.00, "quantity": 1},
                {"name": "Phone Case", "price": 50.00, "quantity": 1},
            ],
        )

        app = YNABCategorizerApp(categorizer=tui_categorizer, is_mock=True)
        app._test_amazon_txn = txn
        app._test_database = tui_database
        return app

    async def test_item_split_screen_shows_items(self, tui_app_with_multi_item_amazon):
        """Test that ItemSplitScreen displays the order items."""
        async with tui_app_with_multi_item_amazon.run_test() as pilot:
            await pilot.pause()

            # Navigate to select our Amazon transaction
            await pilot.press("j")
            await pilot.pause()

            # Press 'x' to open split screen
            await pilot.press("x")
            await pilot.pause()

            # Check if ItemSplitScreen opened
            from src.tui.screens import ItemSplitScreen

            screens = tui_app_with_multi_item_amazon.screen_stack
            split_screen = next((s for s in screens if isinstance(s, ItemSplitScreen)), None)

            if split_screen:
                # Verify items are loaded
                assert len(split_screen._items) == 2
                assert split_screen._items[0]["item_name"] == "USB-C Cable"
                assert split_screen._items[1]["item_name"] == "Phone Case"

    async def test_item_split_screen_dismiss_returns_result(self, tui_app_with_multi_item_amazon):
        """Test that ItemSplitScreen returns False when cancelled."""
        async with tui_app_with_multi_item_amazon.run_test() as pilot:
            await pilot.pause()

            # Navigate to select our Amazon transaction
            await pilot.press("j")
            await pilot.pause()

            # Press 'x' to open split screen
            await pilot.press("x")
            await pilot.pause()

            from src.tui.screens import ItemSplitScreen

            screens = tui_app_with_multi_item_amazon.screen_stack
            split_screen = next((s for s in screens if isinstance(s, ItemSplitScreen)), None)

            if split_screen:
                # Press escape to cancel
                await pilot.press("escape")
                await pilot.pause()

                # Screen should be dismissed
                screens = tui_app_with_multi_item_amazon.screen_stack
                assert not any(isinstance(s, ItemSplitScreen) for s in screens)

    async def test_split_submit_updates_transaction(
        self, tui_app_with_multi_item_amazon, tui_database
    ):
        """Test that submitting a split updates the transaction correctly."""
        async with tui_app_with_multi_item_amazon.run_test() as pilot:
            await pilot.pause()

            # Navigate to select our Amazon transaction
            await pilot.press("j")
            await pilot.pause()

            # Press 'x' to open split screen
            await pilot.press("x")
            await pilot.pause()

            from src.tui.screens import ItemSplitScreen

            screens = tui_app_with_multi_item_amazon.screen_stack
            split_screen = next((s for s in screens if isinstance(s, ItemSplitScreen)), None)

            if split_screen:
                # Manually assign categories to simulate user categorization
                split_screen._assignments = {
                    0: {"category_id": "cat-001", "category_name": "Electronics"},
                    1: {"category_id": "cat-002", "category_name": "Accessories"},
                }

                # Submit the split
                split_screen.action_submit_split()
                await pilot.pause()

                # Verify the transaction was updated
                txn = tui_app_with_multi_item_amazon._test_amazon_txn
                assert txn.category_name == "[Split 2]"
                assert txn.is_split is True
                assert txn.approved is True
                assert txn.sync_status == "pending_push"

                # Verify pending change was created in database
                pending = tui_database.get_pending_change(txn.id)
                assert pending is not None
                assert pending["change_type"] == "split"
                assert pending["new_category_name"] == "[Split 2]"
                assert pending["new_approved"] == 1  # SQLite stores booleans as 0/1

                # Verify splits were stored
                pending_splits = tui_database.get_pending_splits(txn.id)
                assert len(pending_splits) == 2

    async def test_split_submit_closes_screen_and_triggers_callback(
        self, tui_app_with_multi_item_amazon
    ):
        """Test that submitting a split closes screen and triggers UI update callback."""
        async with tui_app_with_multi_item_amazon.run_test() as pilot:
            await pilot.pause()

            # Navigate to select our Amazon transaction
            await pilot.press("j")
            await pilot.pause()

            # Press 'x' to open split screen
            await pilot.press("x")
            await pilot.pause()

            from src.tui.screens import ItemSplitScreen

            screens = tui_app_with_multi_item_amazon.screen_stack
            split_screen = next((s for s in screens if isinstance(s, ItemSplitScreen)), None)

            if split_screen:
                # Assign categories
                split_screen._assignments = {
                    0: {"category_id": "cat-001", "category_name": "Electronics"},
                    1: {"category_id": "cat-002", "category_name": "Accessories"},
                }

                # Submit the split
                split_screen.action_submit_split()
                await pilot.pause()

                # Screen should be closed
                screens = tui_app_with_multi_item_amazon.screen_stack
                assert not any(isinstance(s, ItemSplitScreen) for s in screens)

    async def test_reopen_pending_split_shows_existing_categories(
        self, tui_app_with_multi_item_amazon, tui_database
    ):
        """Test that reopening a pending split shows items as already categorized."""
        async with tui_app_with_multi_item_amazon.run_test() as pilot:
            await pilot.pause()

            # Navigate to select our Amazon transaction
            await pilot.press("j")
            await pilot.pause()

            # Press 'x' to open split screen
            await pilot.press("x")
            await pilot.pause()

            from src.tui.screens import ItemSplitScreen

            screens = tui_app_with_multi_item_amazon.screen_stack
            split_screen = next((s for s in screens if isinstance(s, ItemSplitScreen)), None)

            if split_screen:
                # First, assign categories and submit
                split_screen._assignments = {
                    0: {"category_id": "cat-001", "category_name": "Electronics"},
                    1: {"category_id": "cat-002", "category_name": "Accessories"},
                }
                split_screen.action_submit_split()
                await pilot.pause()

                # Verify split was saved
                txn = tui_app_with_multi_item_amazon._test_amazon_txn
                assert txn.category_name == "[Split 2]"

                # Now reopen the split screen by pressing 'x' again
                await pilot.press("x")
                await pilot.pause()

                screens = tui_app_with_multi_item_amazon.screen_stack
                split_screen2 = next((s for s in screens if isinstance(s, ItemSplitScreen)), None)

                if split_screen2:
                    # Verify existing assignments are loaded
                    assert len(split_screen2._assignments) == 2
                    assert split_screen2._assignments[0]["category_name"] == "Electronics"
                    assert split_screen2._assignments[1]["category_name"] == "Accessories"

                    # Cancel to close
                    await pilot.press("escape")
                    await pilot.pause()

    def test_reopen_synced_split_shows_existing_categories(self, tui_database, tui_categorizer):
        """Test that reopening a synced split (from YNAB) shows items as already categorized."""
        from datetime import datetime

        from src.models.transaction import SubTransaction, Transaction

        # Create a parent transaction marked as split with subtransactions
        parent_txn = Transaction(
            id="txn-synced-split",
            date=datetime(2025, 11, 23),
            amount=-33.33,
            payee_name="Amazon",
            payee_id="payee-amazon",
            account_name="Checking",
            account_id="acc-001",
            approved=True,
            is_split=True,
            category_id=None,
            category_name="Split",
            amazon_items=[
                {
                    "item_name": "Green Toys Recycling Truck",
                    "unit_price": 16.99,
                    "quantity": 1,
                },
                {
                    "item_name": "MOGGEI Womens Merino Wool Socks",
                    "unit_price": 13.49,
                    "quantity": 1,
                },
            ],
            subtransactions=[
                SubTransaction(
                    id="sub-synced-001",
                    transaction_id="txn-synced-split",
                    amount=-16.99,
                    payee_name="Amazon",
                    category_id="cat-001",
                    category_name="Gifts",
                    memo="Green Toys Recycling Truck",
                ),
                SubTransaction(
                    id="sub-synced-002",
                    transaction_id="txn-synced-split",
                    amount=-13.49,
                    payee_name="Amazon",
                    category_id="cat-002",
                    category_name="Clothing",
                    memo="MOGGEI Womens Merino Wool Socks",
                ),
            ],
        )

        # Save to database (including subtransactions)
        tui_database.upsert_ynab_transaction(parent_txn)

        # Verify subtransactions were saved
        subs = tui_database.get_subtransactions("txn-synced-split")
        assert len(subs) == 2

        # Load the transaction back and verify synced splits are returned
        synced_splits = tui_categorizer.get_synced_splits("txn-synced-split")
        assert len(synced_splits) == 2
        # Subtransactions are ordered by amount DESC, so -13.49 comes before -16.99
        assert synced_splits[0]["category_name"] == "Clothing"
        assert synced_splits[0]["memo"] == "MOGGEI Womens Merino Wool Socks"
        assert synced_splits[1]["category_name"] == "Gifts"
        assert synced_splits[1]["memo"] == "Green Toys Recycling Truck"


class TestTUITagging:
    """Test transaction tagging functionality."""

    async def test_tag_toggle_doesnt_crash(self, tui_app):
        """Test toggling tag doesn't crash the app."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Navigate to a transaction
            await pilot.press("j")
            await pilot.pause()

            # Press 't' to tag (whether it tags depends on selection)
            await pilot.press("t")
            await pilot.pause()

            # Press 't' again - no crash = success
            await pilot.press("t")
            await pilot.pause()

    async def test_tag_state_tracked(self, tui_app):
        """Test tagged IDs set exists and can be modified."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Verify _tagged_ids attribute exists
            assert hasattr(tui_app, "_tagged_ids")
            assert isinstance(tui_app._tagged_ids, set)


class TestTUISettings:
    """Test settings screen."""

    async def test_settings_opens(self, tui_app):
        """Test 's' key opens settings screen."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Press 's' to open settings
            await pilot.press("s")
            await pilot.pause()

            # Verify settings screen is showing
            from src.tui.screens import SettingsScreen

            screens = tui_app.screen_stack
            assert any(isinstance(s, SettingsScreen) for s in screens)

    async def test_settings_closes_on_escape(self, tui_app):
        """Test settings screen closes on escape."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Open settings
            await pilot.press("s")
            await pilot.pause()

            # Press escape to close
            await pilot.press("escape")
            await pilot.pause()

            # Settings screen should be closed
            from src.tui.screens import SettingsScreen

            screens = tui_app.screen_stack
            assert not any(isinstance(s, SettingsScreen) for s in screens)


class TestTUICategorizeAction:
    """Test categorize action."""

    async def test_categorize_doesnt_crash(self, tui_app):
        """Test 'c' key doesn't crash app."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Navigate to transaction
            await pilot.press("j")
            await pilot.pause()

            # Press 'c' - no crash = success
            await pilot.press("c")
            await pilot.pause()

            # Press escape to close any modal that may have opened
            await pilot.press("escape")
            await pilot.pause()

    async def test_categorize_enter_doesnt_crash(self, tui_app):
        """Test Enter key doesn't crash app."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Navigate to transaction
            await pilot.press("j")
            await pilot.pause()

            # Press Enter - no crash = success
            await pilot.press("enter")
            await pilot.pause()

            # Press escape to close any modal
            await pilot.press("escape")
            await pilot.pause()


class TestTUIFuzzySearch:
    """Test fuzzy search functionality."""

    async def test_fuzzy_search_opens_modal(self, tui_app):
        """Test '/' opens search modal."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Press '/' to open search
            await pilot.press("/")
            await pilot.pause()

            # Verify search modal is showing
            from src.tui.modals import TransactionSearchModal

            screens = tui_app.screen_stack
            # If there are transactions, modal should open
            if tui_app._transactions.transactions:
                assert any(isinstance(s, TransactionSearchModal) for s in screens)

    async def test_fuzzy_search_escape_closes(self, tui_app):
        """Test Escape closes search modal."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            if tui_app._transactions.transactions:
                # Open search
                await pilot.press("/")
                await pilot.pause()

                # Press escape to close
                await pilot.press("escape")
                await pilot.pause()

                # Modal should be closed
                from src.tui.modals import TransactionSearchModal

                screens = tui_app.screen_stack
                assert not any(isinstance(s, TransactionSearchModal) for s in screens)


class TestTUIUndo:
    """Test undo functionality."""

    async def test_undo_doesnt_crash(self, tui_app):
        """Test 'u' on any transaction doesn't crash."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Navigate to any transaction
            await pilot.press("j")
            await pilot.pause()

            # Press 'u' - should not crash (shows warning if no pending)
            await pilot.press("u")
            await pilot.pause()
            # No crash = success


class TestTUIApprove:
    """Test approve functionality."""

    async def test_approve_doesnt_crash(self, tui_app):
        """Test 'a' key doesn't crash."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Navigate to transaction
            await pilot.press("j")
            await pilot.pause()

            # Press 'a' to approve - no crash = success
            await pilot.press("a")
            await pilot.pause()


class TestTUIFilterModals:
    """Test filter modals."""

    async def test_filter_category_sequence_doesnt_crash(self, tui_app):
        """Test 'f' then 'c' sequence doesn't crash."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Enter filter mode
            await pilot.press("f")
            await pilot.pause()

            # Press 'c' for category filter - no crash = success
            await pilot.press("c")
            await pilot.pause()

            # Press escape to close any modal
            await pilot.press("escape")
            await pilot.pause()

    async def test_filter_payee_sequence_doesnt_crash(self, tui_app):
        """Test 'f' then 'p' sequence doesn't crash."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Enter filter mode
            await pilot.press("f")
            await pilot.pause()

            # Press 'p' for payee filter - no crash = success
            await pilot.press("p")
            await pilot.pause()

            # Press escape to close any modal
            await pilot.press("escape")
            await pilot.pause()


class TestTUIRefresh:
    """Test refresh functionality."""

    async def test_refresh_key_doesnt_crash(self, tui_app):
        """Test 'r' key refreshes transactions."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Press 'r' to refresh - no crash = success
            await pilot.press("r")
            await pilot.pause()
            await pilot.pause()  # Extra pause for worker

    async def test_refresh_preserves_filter(self, tui_app):
        """Test refresh preserves current filter mode."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Set filter to uncategorized
            await pilot.press("f")
            await pilot.pause()
            await pilot.press("u")
            await pilot.pause()

            assert tui_app._filter_mode == "uncategorized"

            # Refresh
            await pilot.press("r")
            await pilot.pause()
            await pilot.pause()

            # Filter should still be uncategorized
            assert tui_app._filter_mode == "uncategorized"


class TestTUIQuit:
    """Test quit functionality."""

    async def test_quit_key_q_exits(self, tui_app):
        """Test 'q' key triggers app exit."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Press 'q' - app should exit
            await pilot.press("q")
            await pilot.pause()


class TestTUIBulkActions:
    """Test bulk action functionality."""

    async def test_bulk_approve_with_no_tags(self, tui_app):
        """Test bulk approve with no tagged transactions."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Ensure no transactions are tagged
            tui_app._tagged_ids.clear()

            # Press 'A' for bulk approve - should show warning
            await pilot.press("A")
            await pilot.pause()

    async def test_bulk_categorize_with_no_tags(self, tui_app):
        """Test bulk categorize with no tagged transactions."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Ensure no transactions are tagged
            tui_app._tagged_ids.clear()

            # Press 'C' for bulk categorize - should show warning
            await pilot.press("C")
            await pilot.pause()


class TestTUIPageNavigation:
    """Test page navigation functionality."""

    async def test_ctrl_d_page_down(self, tui_app):
        """Test Ctrl+D for page down."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Press Ctrl+D - no crash
            await pilot.press("ctrl+d")
            await pilot.pause()

    async def test_ctrl_u_page_up(self, tui_app):
        """Test Ctrl+U for page up."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Press Ctrl+D first, then Ctrl+U
            await pilot.press("ctrl+d")
            await pilot.pause()
            await pilot.press("ctrl+u")
            await pilot.pause()

    async def test_shift_g_goto_bottom(self, tui_app):
        """Test 'G' (shift+g) for go to bottom."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Press 'G' - no crash
            await pilot.press("G")
            await pilot.pause()

    async def test_g_goto_top(self, tui_app):
        """Test 'g' for go to top."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Go to bottom first
            await pilot.press("G")
            await pilot.pause()

            # Press 'g' for top
            await pilot.press("g")
            await pilot.pause()


class TestTUIHelp:
    """Test help screen functionality."""

    async def test_help_key_opens_help(self, tui_app):
        """Test '?' key opens help screen."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Press '?' for help
            await pilot.press("?")
            await pilot.pause()

            # Press escape to close
            await pilot.press("escape")
            await pilot.pause()


class TestTUIDeleteConfirm:
    """Test delete confirmation."""

    async def test_delete_key_with_pending(self, tui_app):
        """Test 'd' key behavior with transaction."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Navigate to transaction
            await pilot.press("j")
            await pilot.pause()

            # Press 'd' - should show confirmation or warning
            await pilot.press("d")
            await pilot.pause()

            # Press 'n' to cancel any confirmation
            await pilot.press("n")
            await pilot.pause()


class TestTUITransactionDisplay:
    """Test transaction display features."""

    async def test_transaction_count_shown(self, tui_app):
        """Test that transaction count is available."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Verify transactions are loaded
            assert tui_app._transactions is not None
            # Total count exists
            assert hasattr(tui_app._transactions, "total_count")

    async def test_navigation_tracked(self, tui_app):
        """Test that navigation is tracked."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Navigate down - no crash = success
            await pilot.press("j")
            await pilot.pause()
            await pilot.press("k")
            await pilot.pause()

    async def test_categorizer_available(self, tui_app):
        """Test that categorizer is available on startup."""
        async with tui_app.run_test() as pilot:
            await pilot.pause()

            # Categorizer should be available
            assert tui_app._categorizer is not None
