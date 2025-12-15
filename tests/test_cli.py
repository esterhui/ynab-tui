"""Tests for CLI commands in src/main.py."""

import pytest
from click.testing import CliRunner

from src.main import main


@pytest.fixture
def cli_runner():
    """Create Click CliRunner."""
    return CliRunner()


@pytest.fixture
def populated_db(database, mock_ynab_client, mock_amazon_client):
    """Populate database with mock data for testing."""
    from src.services.sync import SyncService

    sync = SyncService(db=database, ynab=mock_ynab_client, amazon=mock_amazon_client)
    sync.pull_categories()
    sync.pull_ynab(full=True)
    sync.pull_amazon(full=True)
    return database


@pytest.fixture
def pending_changes_db(populated_db):
    """Database with pending changes ready for push/undo testing."""
    # Get a transaction from the database
    txns = populated_db.get_ynab_transactions(limit=1)
    if txns:
        txn = txns[0]
        populated_db.create_pending_change(
            transaction_id=txn["id"],
            original_category_id=txn.get("category_id"),
            original_category_name=txn.get("category_name") or "Uncategorized",
            new_category_id="cat-001",
            new_category_name="Electronics",
            original_approved=txn.get("approved", False),
            new_approved=True,
        )
    return populated_db


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

    def test_db_status_shows_sections(self, cli_runner, monkeypatch):
        """Test db-status shows expected sections."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "db-status"])
        assert result.exit_code == 0
        assert "Database Status" in result.output
        assert "YNAB Transactions:" in result.output
        assert "Amazon Orders:" in result.output
        assert "Category Mappings:" in result.output


class TestDBTransactionsCommand:
    """Tests for the db-transactions command."""

    def test_db_transactions_shows_list(self, cli_runner, monkeypatch):
        """Test db-transactions shows transaction list."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "db-transactions"])
        assert result.exit_code == 0
        # Should show transactions or "no transactions" message
        assert "Found" in result.output or "No transactions" in result.output

    def test_db_transactions_uncategorized_filter(self, cli_runner, populated_db, monkeypatch):
        """Test db-transactions --uncategorized filter."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "db-transactions", "--uncategorized"])
        assert result.exit_code == 0

    def test_db_transactions_pending_filter(self, cli_runner, pending_changes_db, monkeypatch):
        """Test db-transactions --pending filter."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "db-transactions", "--pending"])
        assert result.exit_code == 0

    def test_db_transactions_payee_filter(self, cli_runner, populated_db, monkeypatch):
        """Test db-transactions --payee filter."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "db-transactions", "--payee", "Amazon"])
        assert result.exit_code == 0

    def test_db_transactions_limit(self, cli_runner, populated_db, monkeypatch):
        """Test db-transactions --limit option."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "db-transactions", "-n", "5"])
        assert result.exit_code == 0

    def test_db_transactions_csv_export(self, cli_runner, tmp_path, monkeypatch):
        """Test db-transactions --csv export."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        # Isolate mock database to avoid race conditions in parallel tests
        from src.config import load_config

        original_load_config = load_config

        def isolated_load_config(config_path=None):
            cfg = original_load_config(config_path)
            cfg.data_dir = tmp_path
            return cfg

        monkeypatch.setattr("src.main.load_config", isolated_load_config)

        csv_path = tmp_path / "transactions.csv"
        result = cli_runner.invoke(main, ["--mock", "db-transactions", "--csv", str(csv_path)])
        assert result.exit_code == 0
        # Will either export or show "no transactions" message
        assert "Exported" in result.output or "No transactions" in result.output

    def test_db_transactions_all_flag(self, cli_runner, populated_db, monkeypatch):
        """Test db-transactions --all shows all without limit."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "db-transactions", "--all"])
        assert result.exit_code == 0


class TestDBAmazonOrdersCommand:
    """Tests for the db-amazon-orders command."""

    def test_db_amazon_orders_runs(self, cli_runner, tmp_path, monkeypatch):
        """Test db-amazon-orders command runs."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        # Isolate mock database to avoid race conditions in parallel tests
        from src.config import load_config

        original_load_config = load_config

        def isolated_load_config(config_path=None):
            cfg = original_load_config(config_path)
            cfg.data_dir = tmp_path
            return cfg

        monkeypatch.setattr("src.main.load_config", isolated_load_config)

        result = cli_runner.invoke(main, ["--mock", "db-amazon-orders"])
        assert result.exit_code == 0
        # Either shows orders or "No orders" message
        assert "Found" in result.output or "No" in result.output

    def test_db_amazon_orders_with_data(self, cli_runner, populated_db, monkeypatch):
        """Test db-amazon-orders with data."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        # Use a large days window to find orders
        result = cli_runner.invoke(main, ["--mock", "db-amazon-orders", "--days", "3650"])
        assert result.exit_code == 0

    def test_db_amazon_orders_year_filter(self, cli_runner, populated_db, monkeypatch):
        """Test db-amazon-orders --year filter."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "db-amazon-orders", "--year", "2024"])
        assert result.exit_code == 0

    def test_db_amazon_orders_csv_export(self, cli_runner, populated_db, tmp_path, monkeypatch):
        """Test db-amazon-orders --csv export."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        csv_path = tmp_path / "orders.csv"
        result = cli_runner.invoke(
            main, ["--mock", "db-amazon-orders", "--year", "2024", "--csv", str(csv_path)]
        )
        assert result.exit_code == 0


class TestYNABCategoriesCommand:
    """Tests for the ynab-categories command."""

    def test_ynab_categories_shows_list(self, cli_runner, monkeypatch):
        """Test ynab-categories shows category list."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "ynab-categories"])
        assert result.exit_code == 0
        # Should show categories or "no categories" message
        assert "Total:" in result.output or "No categories" in result.output or "[" in result.output

    def test_ynab_categories_csv_export(self, cli_runner, tmp_path, monkeypatch):
        """Test ynab-categories --csv export."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        csv_path = tmp_path / "categories.csv"
        result = cli_runner.invoke(main, ["--mock", "ynab-categories", "--csv", str(csv_path)])
        assert result.exit_code == 0
        if csv_path.exists():
            assert "Exported" in result.output


class TestUncategorizedCommand:
    """Tests for the uncategorized command."""

    def test_uncategorized_empty(self, cli_runner, temp_db_path, monkeypatch):
        """Test uncategorized command runs successfully."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "uncategorized"])
        assert result.exit_code == 0
        # Mock mode loads from CSV - should show transactions or indicate empty/need pull
        assert (
            "No uncategorized" in result.output
            or "pull" in result.output.lower()
            or "uncategorized transactions" in result.output.lower()
        )

    def test_uncategorized_with_data(self, cli_runner, populated_db, monkeypatch):
        """Test uncategorized command shows transactions."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "uncategorized"])
        assert result.exit_code == 0


class TestYNABUnapprovedCommand:
    """Tests for the ynab-unapproved command."""

    def test_ynab_unapproved_empty(self, cli_runner, temp_db_path, monkeypatch):
        """Test ynab-unapproved with empty database."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "ynab-unapproved"])
        assert result.exit_code == 0

    def test_ynab_unapproved_with_data(self, cli_runner, populated_db, monkeypatch):
        """Test ynab-unapproved command."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "ynab-unapproved"])
        assert result.exit_code == 0

    def test_ynab_unapproved_csv_export(self, cli_runner, populated_db, tmp_path, monkeypatch):
        """Test ynab-unapproved --csv export."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        csv_path = tmp_path / "unapproved.csv"
        result = cli_runner.invoke(main, ["--mock", "ynab-unapproved", "--csv", str(csv_path)])
        assert result.exit_code == 0


class TestDBDeltasCommand:
    """Tests for the db-deltas command."""

    def test_db_deltas_runs(self, cli_runner, monkeypatch):
        """Test db-deltas command runs."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "db-deltas"])
        assert result.exit_code == 0
        # Should show pending changes or "no pending" message
        assert "pending" in result.output.lower()


class TestMappingsCommand:
    """Tests for the mappings command."""

    def test_mappings_empty(self, cli_runner, populated_db, monkeypatch):
        """Test mappings with no mappings."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "mappings"])
        assert result.exit_code == 0
        # Will show "No category mappings" or mapping count
        assert "mapping" in result.output.lower()


class TestPullCommand:
    """Tests for the pull command."""

    def test_pull_full(self, cli_runner, monkeypatch):
        """Test pull --full command."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        result = cli_runner.invoke(main, ["--mock", "pull", "--full"])
        assert result.exit_code == 0
        assert "Pull complete" in result.output

    def test_pull_with_budget_flag_stores_budget_id(self, cli_runner, tmp_path, monkeypatch):
        """Test that --budget flag causes transactions to be stored with correct budget_id.

        Regression test for bug where --budget "Lux Budget" stored transactions with
        NULL budget_id, making them invisible when switching budgets in TUI.
        """
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        # Isolate database to tmp_path
        from src.config import load_config

        original_load_config = load_config

        def isolated_load_config(config_path=None):
            cfg = original_load_config(config_path)
            cfg.data_dir = tmp_path
            return cfg

        monkeypatch.setattr("src.main.load_config", isolated_load_config)

        # Pull with --budget flag
        result = cli_runner.invoke(
            main, ["--mock", "--budget", "Mock Budget", "pull", "--ynab-only", "--full"]
        )
        assert result.exit_code == 0

        # Verify transactions have budget_id set (not NULL)
        from src.db.database import Database

        db = Database(tmp_path / "mock_categorizer.db")
        txns = db.get_ynab_transactions(limit=10)

        # Should have transactions
        assert len(txns) > 0, "Expected transactions to be stored"

        # All transactions should have budget_id set
        for txn in txns:
            assert txn.get("budget_id") is not None, (
                f"Transaction {txn.get('id')} has NULL budget_id - budget filtering will fail"
            )

    def test_pull_ynab_only(self, cli_runner, monkeypatch):
        """Test pull --ynab-only command."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "pull", "--ynab-only"])
        assert result.exit_code == 0
        assert "YNAB" in result.output

    def test_pull_amazon_only(self, cli_runner, monkeypatch):
        """Test pull --amazon-only command."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        result = cli_runner.invoke(main, ["--mock", "pull", "--amazon-only"])
        assert result.exit_code == 0
        assert "Amazon" in result.output

    def test_pull_amazon_year(self, cli_runner, monkeypatch):
        """Test pull --amazon-only --amazon-year command."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")
        monkeypatch.setenv("AMAZON_USERNAME", "test@example.com")
        monkeypatch.setenv("AMAZON_PASSWORD", "test-password")

        result = cli_runner.invoke(
            main, ["--mock", "pull", "--amazon-only", "--amazon-year", "2024"]
        )
        assert result.exit_code == 0


class TestPushCommand:
    """Tests for the push command."""

    def test_push_runs(self, cli_runner, monkeypatch):
        """Test push command runs."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "push"])
        assert result.exit_code == 0
        # Should show pending changes or "no pending" message
        assert "pending" in result.output.lower() or "Push" in result.output

    def test_push_dry_run(self, cli_runner, monkeypatch):
        """Test push --dry-run shows preview without pushing."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "push", "--dry-run"])
        assert result.exit_code == 0
        # Will either show dry run or "no pending" message
        assert "dry run" in result.output.lower() or "No pending" in result.output


class TestUndoCommand:
    """Tests for the undo command."""

    def test_undo_no_args(self, cli_runner, monkeypatch):
        """Test undo without arguments shows error."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "undo"])
        assert result.exit_code == 0
        assert "Provide a transaction ID" in result.output or "--all" in result.output

    def test_undo_nonexistent_transaction(self, cli_runner, monkeypatch):
        """Test undo with nonexistent transaction ID."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "undo", "nonexistent-txn-id"])
        assert result.exit_code == 0
        assert "No pending change found" in result.output

    def test_undo_all_runs(self, cli_runner, monkeypatch):
        """Test undo --all command runs."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "undo", "--all"])
        assert result.exit_code == 0
        # Should show "no pending" or ask for confirmation
        assert "pending" in result.output.lower() or "Undo" in result.output


class TestDBClearCommand:
    """Tests for the db-clear command."""

    def test_db_clear_mock_indicator(self, cli_runner, monkeypatch):
        """Test db-clear shows mock database indicator."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        # Don't confirm to avoid actually clearing
        result = cli_runner.invoke(main, ["--mock", "db-clear"], input="n\n")
        assert result.exit_code == 0
        assert "MOCK" in result.output or "mock" in result.output

    def test_db_clear_cancelled(self, cli_runner, monkeypatch):
        """Test db-clear can be cancelled."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "db-clear"], input="n\n")
        assert result.exit_code == 0
        assert "Cancelled" in result.output


class TestMappingsCreateCommand:
    """Tests for the mappings-create command."""

    def test_mappings_create_runs(self, cli_runner, monkeypatch):
        """Test mappings-create command runs."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "mappings-create"])
        assert result.exit_code == 0
        # Should show results or indicate no transactions
        assert "Results:" in result.output or "No" in result.output

    def test_mappings_create_dry_run(self, cli_runner, monkeypatch):
        """Test mappings-create --dry-run."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "mappings-create", "--dry-run"])
        assert result.exit_code == 0
        # Should show DRY RUN message or "no transactions" message
        assert "DRY RUN" in result.output or "No" in result.output

    def test_mappings_create_since_date(self, cli_runner, monkeypatch):
        """Test mappings-create --since filter."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "mappings-create", "--since", "2024-01-01"])
        assert result.exit_code == 0


class TestAmazonMatchCommand:
    """Tests for the amazon-match command."""

    def test_amazon_match_empty(self, cli_runner, temp_db_path, monkeypatch):
        """Test amazon-match with empty database."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "amazon-match"])
        assert result.exit_code == 0
        # Should indicate no transactions or need to pull
        assert "No" in result.output or "pull" in result.output.lower()

    def test_amazon_match_with_data(self, cli_runner, populated_db, monkeypatch):
        """Test amazon-match with data."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "amazon-match"])
        assert result.exit_code == 0

    def test_amazon_match_verbose(self, cli_runner, populated_db, monkeypatch):
        """Test amazon-match --verbose option."""
        monkeypatch.setenv("YNAB_API_TOKEN", "test-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget")

        result = cli_runner.invoke(main, ["--mock", "amazon-match", "--verbose"])
        assert result.exit_code == 0
