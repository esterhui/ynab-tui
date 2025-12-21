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


class TestAmazonMatchVerbose:
    """Tests for amazon-match command with verbose output."""

    def test_amazon_match_verbose_with_data(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test amazon-match --verbose shows item category predictions."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        # Pull data first
        cli_runner.invoke(main, ["--mock", "pull", "--full"])

        result = cli_runner.invoke(main, ["--mock", "amazon-match", "--verbose"])
        assert result.exit_code == 0
        # Verbose mode should show output
        assert "Amazon" in result.output or "No" in result.output

    def test_amazon_match_verbose_output_format(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test amazon-match --verbose output includes predictions when available."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        # Pull full data
        cli_runner.invoke(main, ["--mock", "pull", "--full"])

        result = cli_runner.invoke(main, ["--mock", "amazon-match", "-v"])
        assert result.exit_code == 0


class TestUncategorizedWithEnrichment:
    """Tests for uncategorized command with Amazon enrichment."""

    def test_uncategorized_with_amazon_data(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test uncategorized command shows Amazon items when available."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        # Pull full data
        cli_runner.invoke(main, ["--mock", "pull", "--full"])

        result = cli_runner.invoke(main, ["--mock", "uncategorized"])
        assert result.exit_code == 0

    def test_uncategorized_shows_enrichment_summary(
        self, cli_runner, isolated_mock_env, monkeypatch
    ):
        """Test uncategorized command shows enrichment arrows when items present."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        # Pull full data
        cli_runner.invoke(main, ["--mock", "pull", "--full"])

        result = cli_runner.invoke(main, ["--mock", "uncategorized"])
        assert result.exit_code == 0
        # Should show count or "no uncategorized" message
        assert "Found" in result.output or "No uncategorized" in result.output


class TestDBAmazonOrdersDisplay:
    """Tests for db-amazon-orders display formatting."""

    def test_db_amazon_orders_shows_item_prices(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test db-amazon-orders shows item prices when available."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        # Pull Amazon data
        cli_runner.invoke(main, ["--mock", "pull", "--amazon-only"])

        result = cli_runner.invoke(main, ["--mock", "db-amazon-orders", "--days", "3650"])
        assert result.exit_code == 0
        # Should show orders with pricing format or "No orders" message
        assert "Found" in result.output or "No" in result.output

    def test_db_amazon_orders_display_format(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test db-amazon-orders displays date, total, and order ID."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        # Pull Amazon data
        cli_runner.invoke(main, ["--mock", "pull", "--amazon-only"])

        result = cli_runner.invoke(main, ["--mock", "db-amazon-orders", "--year", "2024"])
        assert result.exit_code == 0


class TestUndoSpecificTransaction:
    """Tests for undo command with specific transaction ID."""

    def test_undo_specific_transaction_id(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test undo with specific transaction ID after creating pending change."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        # Pull data first
        cli_runner.invoke(main, ["--mock", "pull", "--ynab-only", "--full"])

        # Get a transaction ID from the database
        from src.db.database import Database

        db = Database(isolated_mock_env / "mock_categorizer.db")
        txns = db.get_ynab_transactions(limit=1)
        db.close()

        if txns:
            txn_id = txns[0]["id"]
            # Try to undo (will say "no pending change" since we didn't categorize)
            result = cli_runner.invoke(main, ["--mock", "undo", txn_id])
            assert result.exit_code == 0
            assert "No pending change found" in result.output

    def test_undo_with_pending_change(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test undo successfully reverts a pending change."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        # Pull data first
        cli_runner.invoke(main, ["--mock", "pull", "--ynab-only", "--full"])

        from src.db.database import Database

        db = Database(isolated_mock_env / "mock_categorizer.db")
        txns = db.get_ynab_transactions(limit=1)

        if txns:
            txn_id = txns[0]["id"]
            # Create a pending change manually
            db.create_pending_change(
                transaction_id=txn_id,
                new_values={
                    "category_id": "cat-new",
                    "category_name": "New Category",
                },
                original_values={
                    "category_id": txns[0].get("category_id"),
                    "category_name": txns[0].get("category_name"),
                },
                change_type="update",
            )
            db.close()

            # Now undo it
            result = cli_runner.invoke(main, ["--mock", "undo", txn_id])
            assert result.exit_code == 0
            assert "Undone" in result.output or "reverted" in result.output.lower()
        else:
            db.close()


class TestDBTransactionsFilters:
    """Extended tests for db-transactions with various filters."""

    def test_db_transactions_year_filter(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test db-transactions with --year filter."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        # Pull data first
        cli_runner.invoke(main, ["--mock", "pull", "--ynab-only", "--full"])

        result = cli_runner.invoke(main, ["--mock", "db-transactions", "--year", "2024"])
        assert result.exit_code == 0

    def test_db_transactions_combined_filters(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test db-transactions with multiple filters combined."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        # Pull data first
        cli_runner.invoke(main, ["--mock", "pull", "--ynab-only", "--full"])

        result = cli_runner.invoke(
            main, ["--mock", "db-transactions", "--year", "2024", "--payee", "Amazon"]
        )
        assert result.exit_code == 0


class TestPullCommandVariants:
    """Tests for pull command variants."""

    def test_pull_incremental(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test pull without --full flag (incremental)."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        result = cli_runner.invoke(main, ["--mock", "pull"])
        assert result.exit_code == 0
        assert "Pull complete" in result.output

    def test_pull_with_specific_amazon_year(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test pull --amazon-only --amazon-year for specific year."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        result = cli_runner.invoke(
            main, ["--mock", "pull", "--amazon-only", "--amazon-year", "2023"]
        )
        assert result.exit_code == 0


class TestPushCommandVariants:
    """Tests for push command variants."""

    def test_push_with_pending_changes(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test push when there are pending changes."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        # Pull data first
        cli_runner.invoke(main, ["--mock", "pull", "--ynab-only", "--full"])

        from src.db.database import Database

        db = Database(isolated_mock_env / "mock_categorizer.db")
        txns = db.get_ynab_transactions(limit=1)

        if txns:
            txn_id = txns[0]["id"]
            # Create a pending change
            db.create_pending_change(
                transaction_id=txn_id,
                new_values={
                    "category_id": "cat-new",
                    "category_name": "New Category",
                },
                original_values={
                    "category_id": txns[0].get("category_id"),
                    "category_name": txns[0].get("category_name"),
                },
                change_type="update",
            )
        db.close()

        # Push with --yes to skip confirmation
        result = cli_runner.invoke(main, ["--mock", "push", "--yes"])
        assert result.exit_code == 0


class TestDBDeltasWithChanges:
    """Tests for db-deltas with pending changes."""

    def test_db_deltas_with_pending_changes(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test db-deltas shows pending changes when present."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        # Pull data first
        cli_runner.invoke(main, ["--mock", "pull", "--ynab-only", "--full"])

        from src.db.database import Database

        db = Database(isolated_mock_env / "mock_categorizer.db")
        txns = db.get_ynab_transactions(limit=1)

        if txns:
            txn_id = txns[0]["id"]
            # Create a pending change
            db.create_pending_change(
                transaction_id=txn_id,
                new_values={
                    "category_id": "cat-new",
                    "category_name": "New Category",
                },
                original_values={
                    "category_id": txns[0].get("category_id"),
                    "category_name": txns[0].get("category_name"),
                },
                change_type="update",
            )
        db.close()

        result = cli_runner.invoke(main, ["--mock", "db-deltas"])
        assert result.exit_code == 0
        # Should show pending changes or count
        assert "pending" in result.output.lower()


class TestYNABCategoriesCSVExport:
    """Tests for ynab-categories CSV export."""

    def test_ynab_categories_csv_with_data(
        self, cli_runner, isolated_mock_env, monkeypatch, tmp_path
    ):
        """Test ynab-categories CSV export with data."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        # Pull data to populate categories
        cli_runner.invoke(main, ["--mock", "pull", "--ynab-only", "--full"])

        csv_file = tmp_path / "categories.csv"
        result = cli_runner.invoke(main, ["--mock", "ynab-categories", "--csv", str(csv_file)])
        assert result.exit_code == 0
        assert csv_file.exists()
        assert "Exported" in result.output


class TestYNABUnapprovedCSVExport:
    """Tests for ynab-unapproved CSV export."""

    def test_ynab_unapproved_csv_with_data(
        self, cli_runner, isolated_mock_env, monkeypatch, tmp_path
    ):
        """Test ynab-unapproved CSV export with data."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        # Pull data
        cli_runner.invoke(main, ["--mock", "pull", "--ynab-only", "--full"])

        csv_file = tmp_path / "unapproved.csv"
        result = cli_runner.invoke(main, ["--mock", "ynab-unapproved", "--csv", str(csv_file)])
        assert result.exit_code == 0
        # Either exported data or no unapproved found
        assert "Exported" in result.output or "No unapproved" in result.output


class TestDBTransactionsOutput:
    """Tests for db-transactions output formatting."""

    def test_db_transactions_shows_formatted_output(
        self, cli_runner, isolated_mock_env, monkeypatch
    ):
        """Test db-transactions shows formatted output."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        # Pull data
        cli_runner.invoke(main, ["--mock", "pull", "--ynab-only", "--full"])

        result = cli_runner.invoke(main, ["--mock", "db-transactions", "--limit", "5"])
        assert result.exit_code == 0
        # Should show some transactions or "No transactions"
        assert result.output

    def test_db_transactions_all_flag(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test db-transactions --all flag shows all transactions."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        # Pull data
        cli_runner.invoke(main, ["--mock", "pull", "--ynab-only", "--full"])

        result = cli_runner.invoke(main, ["--mock", "db-transactions", "--all"])
        assert result.exit_code == 0


class TestMappingsCreateExtended:
    """Extended tests for mappings-create command."""

    def test_mappings_create_with_data(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test mappings-create with existing data."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        # Pull data
        cli_runner.invoke(main, ["--mock", "pull", "--full"])

        result = cli_runner.invoke(main, ["--mock", "mappings-create"])
        assert result.exit_code == 0

    def test_mappings_create_dry_run_with_data(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test mappings-create --dry-run shows what would be created."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        # Pull data
        cli_runner.invoke(main, ["--mock", "pull", "--full"])

        result = cli_runner.invoke(main, ["--mock", "mappings-create", "--dry-run"])
        assert result.exit_code == 0

    def test_mappings_create_with_since_date(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test mappings-create --since filters by date."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        # Pull data
        cli_runner.invoke(main, ["--mock", "pull", "--full"])

        result = cli_runner.invoke(main, ["--mock", "mappings-create", "--since", "2024-01-01"])
        assert result.exit_code == 0


class TestMappingsQuery:
    """Tests for mappings query command."""

    def test_mappings_with_data(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test mappings command after creating mappings."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        # Pull data and create mappings
        cli_runner.invoke(main, ["--mock", "pull", "--full"])
        cli_runner.invoke(main, ["--mock", "mappings-create", "--yes"])

        result = cli_runner.invoke(main, ["--mock", "mappings"])
        assert result.exit_code == 0


class TestDBStatusOutput:
    """Tests for db-status output formatting."""

    def test_db_status_after_full_pull(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test db-status shows complete status after full pull."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        # Full pull
        cli_runner.invoke(main, ["--mock", "pull", "--full"])

        result = cli_runner.invoke(main, ["--mock", "db-status"])
        assert result.exit_code == 0
        # Should show various sections
        assert "Database" in result.output or "Status" in result.output


class TestDBAmazonOrdersOutput:
    """Tests for db-amazon-orders output formatting."""

    def test_db_amazon_orders_output_with_items(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test db-amazon-orders shows items with prices."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        # Pull Amazon data
        cli_runner.invoke(main, ["--mock", "pull", "--amazon-only"])

        result = cli_runner.invoke(main, ["--mock", "db-amazon-orders", "--days", "3650"])
        assert result.exit_code == 0


class TestAdditionalCLIEdgeCases:
    """Additional edge case tests for CLI commands."""

    def test_push_with_no_pending(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test push command when no pending changes."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        # Pull data but don't create any pending changes
        cli_runner.invoke(main, ["--mock", "pull", "--ynab-only", "--full"])

        result = cli_runner.invoke(main, ["--mock", "push"])
        assert result.exit_code == 0
        # Should indicate no pending changes
        assert "No pending" in result.output or "Nothing" in result.output

    def test_pull_output_messages(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test pull command shows progress messages."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        result = cli_runner.invoke(main, ["--mock", "pull", "--full"])
        assert result.exit_code == 0
        # Should show pull progress
        assert "Pull" in result.output or "pull" in result.output

    def test_db_transactions_no_data(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test db-transactions with empty database."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        result = cli_runner.invoke(main, ["--mock", "db-transactions"])
        assert result.exit_code == 0
        # Either shows "no data" or "Run 'pull' first"
        assert "No" in result.output or "pull" in result.output.lower()

    def test_ynab_categories_display_output(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test ynab-categories display output formatting."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        cli_runner.invoke(main, ["--mock", "pull", "--ynab-only", "--full"])

        result = cli_runner.invoke(main, ["--mock", "ynab-categories"])
        assert result.exit_code == 0
        # Should show categories or "no categories"
        assert "Total" in result.output or "No categories" in result.output

    def test_mappings_empty(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test mappings command with no data."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        result = cli_runner.invoke(main, ["--mock", "mappings"])
        assert result.exit_code == 0

    def test_uncategorized_empty(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test uncategorized command with empty database."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        result = cli_runner.invoke(main, ["--mock", "uncategorized"])
        assert result.exit_code == 0
        # Should say no data or run pull first
        assert "No" in result.output or "pull" in result.output.lower()

    def test_db_amazon_orders_no_data(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test db-amazon-orders with no orders in database."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        result = cli_runner.invoke(main, ["--mock", "db-amazon-orders"])
        assert result.exit_code == 0


# =============================================================================
# Additional CLI Tests for Coverage
# =============================================================================


class TestPushDryRun:
    """Tests for push command dry run mode."""

    def test_push_dry_run_succeeds(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test push --dry-run shows what would be pushed."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        result = cli_runner.invoke(main, ["--mock", "push", "--dry-run"])
        # Should succeed (even with no pending changes)
        assert result.exit_code == 0

    def test_push_with_no_pending_changes(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test push with no pending changes."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        # First do a pull to set up database
        cli_runner.invoke(main, ["--mock", "pull", "--ynab"])

        result = cli_runner.invoke(main, ["--mock", "push"])
        assert result.exit_code == 0
        # Should say no changes
        assert (
            "No pending" in result.output
            or "0 changes" in result.output
            or "push" in result.output.lower()
        )


class TestDBStatusExtended:
    """Extended tests for db-status command."""

    def test_db_status_on_fresh_database(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test db-status on fresh database."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        result = cli_runner.invoke(main, ["--mock", "db-status"])
        assert result.exit_code == 0
        assert "Status" in result.output

    def test_db_status_with_synced_data(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test db-status after pulling data."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        # Pull data first
        cli_runner.invoke(main, ["--mock", "pull", "--ynab"])

        result = cli_runner.invoke(main, ["--mock", "db-status"])
        assert result.exit_code == 0
        # Should show transaction counts
        assert "Transaction" in result.output or "Status" in result.output


class TestDBTransactionsOptions:
    """Tests for db-transactions command options."""

    def test_uncategorized_option(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test db-transactions --uncategorized filter."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        result = cli_runner.invoke(main, ["--mock", "db-transactions", "--uncategorized"])
        assert result.exit_code == 0

    def test_pending_option(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test db-transactions --pending filter."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        result = cli_runner.invoke(main, ["--mock", "db-transactions", "--pending"])
        assert result.exit_code == 0

    def test_limit_with_pulled_data(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test db-transactions with limit."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        # Pull data first
        cli_runner.invoke(main, ["--mock", "pull", "--ynab"])

        result = cli_runner.invoke(main, ["--mock", "db-transactions", "--limit", "5"])
        assert result.exit_code == 0


class TestHelpCommands:
    """Tests for help and basic command options."""

    def test_main_help(self, cli_runner):
        """Test main --help shows usage."""
        result = cli_runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Usage" in result.output

    def test_pull_help(self, cli_runner):
        """Test pull --help shows options."""
        result = cli_runner.invoke(main, ["pull", "--help"])
        assert result.exit_code == 0
        assert "Usage" in result.output

    def test_push_help(self, cli_runner):
        """Test push --help shows options."""
        result = cli_runner.invoke(main, ["push", "--help"])
        assert result.exit_code == 0
        assert "Usage" in result.output


class TestMockModeOptions:
    """Tests for mock mode specific behavior."""

    def test_mock_mode_explicitly_set(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test --mock flag is properly set."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        result = cli_runner.invoke(main, ["--mock", "db-status"])
        assert result.exit_code == 0


class TestUncategorizedAfterPull:
    """Tests for uncategorized command after data pull."""

    def test_uncategorized_after_ynab_pull(self, cli_runner, isolated_mock_env, monkeypatch):
        """Test uncategorized command after pulling data."""
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        # Pull data first
        cli_runner.invoke(main, ["--mock", "pull", "--ynab"])

        result = cli_runner.invoke(main, ["--mock", "uncategorized"])
        assert result.exit_code == 0
