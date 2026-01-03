"""Tests for TUI app."""

import pytest

from ynab_tui.clients import MockYNABClient
from ynab_tui.db.database import Database
from ynab_tui.services.categorizer import CategorizerService
from ynab_tui.tui.app import YNABCategorizerApp


@pytest.fixture
def app_database(tmp_path):
    """Create a temporary database for app tests."""
    db = Database(tmp_path / "test_app.db")
    yield db
    db.close()


@pytest.fixture
def app_ynab_client():
    """Create mock YNAB client for app tests."""
    return MockYNABClient(max_transactions=10)


@pytest.fixture
def app_categorizer(sample_config, app_database, app_ynab_client):
    """Create CategorizerService for app tests."""
    return CategorizerService(
        config=sample_config,
        ynab_client=app_ynab_client,
        db=app_database,
    )


class TestYNABCategorizerApp:
    """Tests for the main TUI app."""

    async def test_refresh_does_not_crash(self, app_categorizer):
        """Pressing F5 to refresh should not crash the app."""
        app = YNABCategorizerApp(categorizer=app_categorizer, is_mock=True)

        async with app.run_test() as pilot:
            await pilot.pause()

            # Press F5 to refresh
            await pilot.press("f5")
            await pilot.pause()

            # App should still be running
            assert app.is_running
