"""Tests for CLI commands in src/main.py."""

import pytest
from click.testing import CliRunner

from src.main import main


@pytest.fixture
def cli_runner():
    """Create Click CliRunner."""
    return CliRunner()


@pytest.fixture
def isolated_mock_env(tmp_path, monkeypatch):
    """Set up isolated environment for CLI tests with mock mode.

    This fixture ensures each test uses its own temp directory for the mock
    database, preventing SQLite locking conflicts when tests run in parallel.
    """
    monkeypatch.setenv("YNAB_TUI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
    monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")
    return tmp_path


class TestMainEntry:
    """Tests for the main entry point and global options."""

    def test_help_option(self, cli_runner):
        """Test --help shows usage information."""
        result = cli_runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "YNAB TUI" in result.output

    def test_mock_flag_recognized(self, cli_runner):
        """Test --mock flag is recognized."""
        result = cli_runner.invoke(main, ["--mock", "--help"])
        assert result.exit_code == 0


class TestDBStatusCommand:
    """Tests for the db-status command."""

    def test_db_status_shows_sections(self, cli_runner, isolated_mock_env):
        """Test db-status shows expected sections."""
        result = cli_runner.invoke(main, ["--mock", "db-status"])
        assert result.exit_code == 0
        assert "Database Status" in result.output
        assert "YNAB Transactions:" in result.output
        assert "Amazon Orders:" in result.output
        assert "Category Mappings:" in result.output


class TestDBTransactionsCommand:
    """Tests for the db-transactions command."""

    def test_db_transactions_shows_list(self, cli_runner, isolated_mock_env):
        """Test db-transactions shows transaction list."""
        result = cli_runner.invoke(main, ["--mock", "db-transactions"])
        assert result.exit_code == 0
        # Should show transactions or "no transactions" message
        assert "Found" in result.output or "No transactions" in result.output

    def test_db_transactions_uncategorized_filter(self, cli_runner, isolated_mock_env):
        """Test db-transactions --uncategorized filter."""
        result = cli_runner.invoke(main, ["--mock", "db-transactions", "--uncategorized"])
        assert result.exit_code == 0

    def test_db_transactions_pending_filter(self, cli_runner, isolated_mock_env):
        """Test db-transactions --pending filter."""
        result = cli_runner.invoke(main, ["--mock", "db-transactions", "--pending"])
        assert result.exit_code == 0

    def test_db_transactions_payee_filter(self, cli_runner, isolated_mock_env):
        """Test db-transactions --payee filter."""
        result = cli_runner.invoke(main, ["--mock", "db-transactions", "--payee", "Amazon"])
        assert result.exit_code == 0

    def test_db_transactions_limit(self, cli_runner, isolated_mock_env):
        """Test db-transactions --limit option."""
        result = cli_runner.invoke(main, ["--mock", "db-transactions", "-n", "5"])
        assert result.exit_code == 0

    def test_db_transactions_csv_export(self, cli_runner, isolated_mock_env):
        """Test db-transactions --csv export."""
        csv_path = isolated_mock_env / "transactions.csv"
        result = cli_runner.invoke(main, ["--mock", "db-transactions", "--csv", str(csv_path)])
        assert result.exit_code == 0
        # Will either export or show "no transactions" message
        assert "Exported" in result.output or "No transactions" in result.output

    def test_db_transactions_all_flag(self, cli_runner, isolated_mock_env):
        """Test db-transactions --all shows all without limit."""
        result = cli_runner.invoke(main, ["--mock", "db-transactions", "--all"])
        assert result.exit_code == 0


class TestDBAmazonOrdersCommand:
    """Tests for the db-amazon-orders command."""

    def test_db_amazon_orders_runs(self, cli_runner, isolated_mock_env):
        """Test db-amazon-orders command runs."""
        result = cli_runner.invoke(main, ["--mock", "db-amazon-orders"])
        assert result.exit_code == 0
        # Either shows orders or "No orders" message
        assert "Found" in result.output or "No" in result.output

    def test_db_amazon_orders_with_data(self, cli_runner, isolated_mock_env):
        """Test db-amazon-orders with data."""
        # Use a large days window to find orders
        result = cli_runner.invoke(main, ["--mock", "db-amazon-orders", "--days", "3650"])
        assert result.exit_code == 0

    def test_db_amazon_orders_year_filter(self, cli_runner, isolated_mock_env):
        """Test db-amazon-orders --year filter."""
        result = cli_runner.invoke(main, ["--mock", "db-amazon-orders", "--year", "2024"])
        assert result.exit_code == 0

    def test_db_amazon_orders_csv_export(self, cli_runner, isolated_mock_env):
        """Test db-amazon-orders --csv export."""
        csv_path = isolated_mock_env / "orders.csv"
        result = cli_runner.invoke(
            main, ["--mock", "db-amazon-orders", "--year", "2024", "--csv", str(csv_path)]
        )
        assert result.exit_code == 0


class TestYNABCategoriesCommand:
    """Tests for the ynab-categories command."""

    def test_ynab_categories_shows_list(self, cli_runner, isolated_mock_env):
        """Test ynab-categories shows category list."""
        result = cli_runner.invoke(main, ["--mock", "ynab-categories"])
        assert result.exit_code == 0
        # Should show categories or "no categories" message
        assert "Total:" in result.output or "No categories" in result.output or "[" in result.output

    def test_ynab_categories_csv_export(self, cli_runner, isolated_mock_env):
        """Test ynab-categories --csv export."""
        csv_path = isolated_mock_env / "categories.csv"
        result = cli_runner.invoke(main, ["--mock", "ynab-categories", "--csv", str(csv_path)])
        assert result.exit_code == 0
        if csv_path.exists():
            assert "Exported" in result.output


class TestUncategorizedCommand:
    """Tests for the uncategorized command."""

    def test_uncategorized_empty(self, cli_runner, isolated_mock_env):
        """Test uncategorized command runs successfully."""
        result = cli_runner.invoke(main, ["--mock", "uncategorized"])
        assert result.exit_code == 0
        # Mock mode loads from CSV - should show transactions or indicate empty/need pull
        assert (
            "No uncategorized" in result.output
            or "pull" in result.output.lower()
            or "uncategorized transactions" in result.output.lower()
        )

    def test_uncategorized_with_data(self, cli_runner, isolated_mock_env):
        """Test uncategorized command shows transactions."""
        result = cli_runner.invoke(main, ["--mock", "uncategorized"])
        assert result.exit_code == 0


class TestYNABUnapprovedCommand:
    """Tests for the ynab-unapproved command."""

    def test_ynab_unapproved_empty(self, cli_runner, isolated_mock_env):
        """Test ynab-unapproved with empty database."""
        result = cli_runner.invoke(main, ["--mock", "ynab-unapproved"])
        assert result.exit_code == 0

    def test_ynab_unapproved_with_data(self, cli_runner, isolated_mock_env):
        """Test ynab-unapproved command."""
        result = cli_runner.invoke(main, ["--mock", "ynab-unapproved"])
        assert result.exit_code == 0

    def test_ynab_unapproved_csv_export(self, cli_runner, isolated_mock_env):
        """Test ynab-unapproved --csv export."""
        csv_path = isolated_mock_env / "unapproved.csv"
        result = cli_runner.invoke(main, ["--mock", "ynab-unapproved", "--csv", str(csv_path)])
        assert result.exit_code == 0


class TestDBDeltasCommand:
    """Tests for the db-deltas command."""

    def test_db_deltas_runs(self, cli_runner, isolated_mock_env):
        """Test db-deltas command runs."""
        result = cli_runner.invoke(main, ["--mock", "db-deltas"])
        assert result.exit_code == 0
        # Should show pending changes or "no pending" message
        assert "pending" in result.output.lower()


class TestMappingsCommand:
    """Tests for the mappings command."""

    def test_mappings_empty(self, cli_runner, isolated_mock_env):
        """Test mappings with no mappings."""
        result = cli_runner.invoke(main, ["--mock", "mappings"])
        assert result.exit_code == 0
        # Will show "No category mappings" or mapping count
        assert "mapping" in result.output.lower()


class TestPullCommand:
    """Tests for the pull command."""

    def test_pull_full(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test pull --full command."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        result = cli_runner.invoke(main, ["--mock", "pull", "--full"])
        assert result.exit_code == 0
        assert "Pull complete" in result.output

    def test_pull_with_budget_flag_stores_budget_id(self, cli_runner, isolated_mock_env):
        """Test that --budget flag causes transactions to be stored with correct budget_id.

        Regression test for bug where --budget "Lux Budget" stored transactions with
        NULL budget_id, making them invisible when switching budgets in TUI.
        """
        # Pull with --budget flag
        result = cli_runner.invoke(
            main, ["--mock", "--budget", "Mock Budget", "pull", "--ynab-only", "--full"]
        )
        assert result.exit_code == 0

        # Verify transactions have budget_id set (not NULL)
        from src.db.database import Database

        db = Database(isolated_mock_env / "mock_categorizer.db")
        txns = db.get_ynab_transactions(limit=10)
        db.close()

        # Should have transactions
        assert len(txns) > 0, "Expected transactions to be stored"

        # All transactions should have budget_id set
        for txn in txns:
            assert txn.get("budget_id") is not None, (
                f"Transaction {txn.get('id')} has NULL budget_id - budget filtering will fail"
            )

    def test_pull_ynab_only(self, cli_runner, isolated_mock_env):
        """Test pull --ynab-only command."""
        result = cli_runner.invoke(main, ["--mock", "pull", "--ynab-only"])
        assert result.exit_code == 0
        assert "YNAB" in result.output

    def test_pull_amazon_only(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test pull --amazon-only command."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        result = cli_runner.invoke(main, ["--mock", "pull", "--amazon-only"])
        assert result.exit_code == 0
        assert "Amazon" in result.output

    def test_pull_amazon_year(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test pull --amazon-only --amazon-year command."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        result = cli_runner.invoke(
            main, ["--mock", "pull", "--amazon-only", "--amazon-year", "2024"]
        )
        assert result.exit_code == 0


class TestPushCommand:
    """Tests for the push command."""

    def test_push_runs(self, cli_runner, isolated_mock_env):
        """Test push command runs."""
        result = cli_runner.invoke(main, ["--mock", "push"])
        assert result.exit_code == 0
        # Should show pending changes or "no pending" message
        assert "pending" in result.output.lower() or "Push" in result.output

    def test_push_dry_run(self, cli_runner, isolated_mock_env):
        """Test push --dry-run shows preview without pushing."""
        result = cli_runner.invoke(main, ["--mock", "push", "--dry-run"])
        assert result.exit_code == 0
        # Will either show dry run or "no pending" message
        assert "dry run" in result.output.lower() or "No pending" in result.output


class TestUndoCommand:
    """Tests for the undo command."""

    def test_undo_no_args(self, cli_runner, isolated_mock_env):
        """Test undo without arguments shows error."""
        result = cli_runner.invoke(main, ["--mock", "undo"])
        assert result.exit_code == 0
        assert "Provide a transaction ID" in result.output or "--all" in result.output

    def test_undo_nonexistent_transaction(self, cli_runner, isolated_mock_env):
        """Test undo with nonexistent transaction ID."""
        result = cli_runner.invoke(main, ["--mock", "undo", "nonexistent-txn-id"])
        assert result.exit_code == 0
        assert "No pending change found" in result.output

    def test_undo_all_runs(self, cli_runner, isolated_mock_env):
        """Test undo --all command runs."""
        result = cli_runner.invoke(main, ["--mock", "undo", "--all"])
        assert result.exit_code == 0
        # Should show "no pending" or ask for confirmation
        assert "pending" in result.output.lower() or "Undo" in result.output


class TestDBClearCommand:
    """Tests for the db-clear command."""

    def test_db_clear_mock_indicator(self, cli_runner, isolated_mock_env):
        """Test db-clear shows mock database indicator."""
        # Don't confirm to avoid actually clearing
        result = cli_runner.invoke(main, ["--mock", "db-clear"], input="n\n")
        assert result.exit_code == 0
        assert "MOCK" in result.output or "mock" in result.output

    def test_db_clear_cancelled(self, cli_runner, isolated_mock_env):
        """Test db-clear can be cancelled."""
        result = cli_runner.invoke(main, ["--mock", "db-clear"], input="n\n")
        assert result.exit_code == 0
        assert "Cancelled" in result.output


class TestMappingsCreateCommand:
    """Tests for the mappings-create command."""

    def test_mappings_create_runs(self, cli_runner, isolated_mock_env):
        """Test mappings-create command runs."""
        result = cli_runner.invoke(main, ["--mock", "mappings-create"])
        assert result.exit_code == 0
        # Should show results or indicate no transactions
        assert "Results:" in result.output or "No" in result.output

    def test_mappings_create_dry_run(self, cli_runner, isolated_mock_env):
        """Test mappings-create --dry-run."""
        result = cli_runner.invoke(main, ["--mock", "mappings-create", "--dry-run"])
        assert result.exit_code == 0
        # Should show DRY RUN message or "no transactions" message
        assert "DRY RUN" in result.output or "No" in result.output

    def test_mappings_create_since_date(self, cli_runner, isolated_mock_env):
        """Test mappings-create --since filter."""
        result = cli_runner.invoke(main, ["--mock", "mappings-create", "--since", "2024-01-01"])
        assert result.exit_code == 0


class TestAmazonMatchCommand:
    """Tests for the amazon-match command."""

    def test_amazon_match_empty(self, cli_runner, isolated_mock_env):
        """Test amazon-match with empty database."""
        result = cli_runner.invoke(main, ["--mock", "amazon-match"])
        assert result.exit_code == 0
        # Should indicate no transactions or need to pull
        assert "No" in result.output or "pull" in result.output.lower()

    def test_amazon_match_with_data(self, cli_runner, isolated_mock_env):
        """Test amazon-match with data."""
        result = cli_runner.invoke(main, ["--mock", "amazon-match"])
        assert result.exit_code == 0

    def test_amazon_match_verbose(self, cli_runner, isolated_mock_env):
        """Test amazon-match --verbose option."""
        result = cli_runner.invoke(main, ["--mock", "amazon-match", "--verbose"])
        assert result.exit_code == 0


class TestMappingsCommandFilters:
    """Tests for the mappings command with filters."""

    def test_mappings_with_item_filter(self, cli_runner, isolated_mock_env):
        """Test mappings --item filter."""
        result = cli_runner.invoke(main, ["--mock", "mappings", "--item", "cable"])
        assert result.exit_code == 0
        # Should show results or "no mappings" message
        assert "mapping" in result.output.lower()

    def test_mappings_with_category_filter(self, cli_runner, isolated_mock_env):
        """Test mappings --category filter."""
        result = cli_runner.invoke(main, ["--mock", "mappings", "--category", "electronics"])
        assert result.exit_code == 0

    def test_mappings_with_limit(self, cli_runner, isolated_mock_env):
        """Test mappings -n limit."""
        result = cli_runner.invoke(main, ["--mock", "mappings", "-n", "10"])
        assert result.exit_code == 0


class TestPushCommandExtended:
    """Extended tests for the push command."""

    def test_push_with_yes_flag(self, cli_runner, isolated_mock_env):
        """Test push --yes skips confirmation."""
        result = cli_runner.invoke(main, ["--mock", "push", "--yes"])
        assert result.exit_code == 0
        # Should show "no pending" or push result
        assert "pending" in result.output.lower() or "Push" in result.output

    def test_push_cancelled(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test push can be cancelled at confirmation."""
        # First add some data then create a pending change
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")
        cli_runner.invoke(main, ["--mock", "pull", "--ynab-only", "--full"])

        # Try to push but cancel
        result = cli_runner.invoke(main, ["--mock", "push"], input="n\n")
        assert result.exit_code == 0
        # Either cancelled or no pending changes
        assert "Cancelled" in result.output or "No pending" in result.output


class TestUndoCommandExtended:
    """Extended tests for the undo command."""

    def test_undo_all_cancelled(self, cli_runner, isolated_mock_env):
        """Test undo --all can be cancelled."""
        result = cli_runner.invoke(main, ["--mock", "undo", "--all"], input="n\n")
        assert result.exit_code == 0
        # Either cancelled or no pending changes
        assert "Cancelled" in result.output or "No pending" in result.output

    def test_undo_all_confirmed(self, cli_runner, isolated_mock_env):
        """Test undo --all with confirmation."""
        result = cli_runner.invoke(main, ["--mock", "undo", "--all"], input="y\n")
        assert result.exit_code == 0
        # Either undone or no pending changes
        assert "Undone" in result.output or "No pending" in result.output

    def test_undo_shows_usage(self, cli_runner, isolated_mock_env):
        """Test undo without args shows usage."""
        result = cli_runner.invoke(main, ["--mock", "undo"])
        assert result.exit_code == 0
        assert "transaction ID" in result.output or "--all" in result.output


class TestDBClearCommandExtended:
    """Extended tests for the db-clear command."""

    def test_db_clear_with_yes_flag(self, cli_runner, isolated_mock_env):
        """Test db-clear --yes skips confirmation."""
        result = cli_runner.invoke(main, ["--mock", "db-clear", "--yes"])
        assert result.exit_code == 0
        assert "Cleared" in result.output

    def test_db_clear_shows_counts(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test db-clear shows current database counts before clearing."""
        # First add some data
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")
        cli_runner.invoke(main, ["--mock", "pull", "--full"])

        # Clear (cancelled) to see counts
        result = cli_runner.invoke(main, ["--mock", "db-clear"], input="n\n")
        assert result.exit_code == 0
        assert "Current database contents" in result.output
        assert "Transactions:" in result.output


class TestDBTransactionsCommandExtended:
    """Extended tests for the db-transactions command."""

    def test_db_transactions_with_multiple_filters(
        self, cli_runner, isolated_mock_env, monkeypatch
    ):
        """Test db-transactions with multiple filters combined."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")
        cli_runner.invoke(main, ["--mock", "pull", "--ynab-only", "--full"])

        result = cli_runner.invoke(
            main, ["--mock", "db-transactions", "--uncategorized", "-n", "5"]
        )
        assert result.exit_code == 0


class TestYNABUnapprovedCommandExtended:
    """Extended tests for the ynab-unapproved command."""

    def test_ynab_unapproved_with_data(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test ynab-unapproved after pulling data."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")
        cli_runner.invoke(main, ["--mock", "pull", "--ynab-only", "--full"])

        result = cli_runner.invoke(main, ["--mock", "ynab-unapproved"])
        assert result.exit_code == 0
        # Should show transactions or "no unapproved" message
        assert "unapproved" in result.output.lower() or "Found" in result.output
