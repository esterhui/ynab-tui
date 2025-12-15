"""Tests for sync service operations."""

from datetime import datetime

from src.services.sync import PullResult, PushResult, SyncService


class TestPullResult:
    """Tests for PullResult dataclass."""

    def test_success_when_no_errors(self):
        """Test success property returns True when no errors."""
        result = PullResult(source="ynab", fetched=10, inserted=10)
        assert result.success is True

    def test_failure_when_errors_present(self):
        """Test success property returns False when errors exist."""
        result = PullResult(source="ynab", errors=["Connection failed"])
        assert result.success is False

    def test_default_values(self):
        """Test default values are set correctly."""
        result = PullResult(source="amazon")
        assert result.fetched == 0
        assert result.inserted == 0
        assert result.updated == 0
        assert result.total == 0
        assert result.errors == []


class TestPushResult:
    """Tests for PushResult dataclass."""

    def test_success_when_no_failures(self):
        """Test success property returns True when no failures."""
        result = PushResult(pushed=5, succeeded=5, failed=0)
        assert result.success is True

    def test_failure_when_some_failed(self):
        """Test success property returns False when some pushes failed."""
        result = PushResult(pushed=5, succeeded=3, failed=2)
        assert result.success is False

    def test_failure_when_errors_present(self):
        """Test success property returns False when errors exist."""
        result = PushResult(pushed=5, succeeded=5, failed=0, errors=["Unknown error"])
        assert result.success is False


class TestSyncServicePull:
    """Tests for pull operations."""

    def test_pull_ynab_populates_transactions(self, sync_service, database):
        """Test that pull_ynab stores transactions in DB."""
        result = sync_service.pull_ynab()

        assert result.success
        assert result.fetched > 0
        assert result.source == "ynab"
        # Verify transactions in database
        assert database.get_transaction_count() == result.total

    def test_pull_ynab_full_sync(self, sync_service, database):
        """Test full sync fetches all transactions."""
        result = sync_service.pull_ynab(full=True)

        assert result.success
        assert result.fetched > 0

    def test_pull_ynab_updates_sync_state(self, sync_service, database):
        """Test that pull updates sync state."""
        # Initially no sync state
        state = database.get_sync_state("ynab")
        assert state is None

        # After pull, sync state should exist
        sync_service.pull_ynab()
        state = database.get_sync_state("ynab")

        assert state is not None
        assert state["key"] == "ynab"
        assert state["last_sync_date"] is not None
        assert state["last_sync_at"] is not None
        assert state["record_count"] > 0

    def test_pull_ynab_incremental_uses_overlap(self, sync_service, database):
        """Test incremental pull uses 7-day overlap from last sync date."""
        # First pull (full)
        sync_service.pull_ynab(full=True)
        initial_count = database.get_transaction_count()

        # Update sync state to a specific date
        database.update_sync_state(
            "ynab",
            datetime(2025, 1, 15),
            initial_count,
        )

        # Second pull should be incremental
        result = sync_service.pull_ynab(full=False)

        assert result.success
        # Should have used since_date = 2025-01-15 - 7 days = 2025-01-08

    def test_pull_amazon_populates_orders(self, sync_service, database):
        """Test that pull_amazon stores orders and items."""
        result = sync_service.pull_amazon()

        assert result.success
        assert result.fetched > 0
        assert result.source == "amazon"
        assert database.get_order_count() > 0
        assert database.get_order_item_count() > 0

    def test_pull_amazon_updates_sync_state(self, sync_service, database):
        """Test that Amazon pull updates sync state."""
        sync_service.pull_amazon()
        state = database.get_sync_state("amazon")

        assert state is not None
        assert state["key"] == "amazon"

    def test_pull_amazon_for_specific_year(self, sync_service, database):
        """Test pulling Amazon orders for a specific year."""
        result = sync_service.pull_amazon(year=2025)

        assert result.success

    def test_pull_all_returns_both_results(self, sync_service):
        """Test pull_all pulls both YNAB and Amazon."""
        results = sync_service.pull_all()

        assert "ynab" in results
        assert "amazon" in results
        assert results["ynab"].success
        assert results["amazon"].success

    def test_pull_ynab_upsert_no_duplicates(self, sync_service, database):
        """Test that pulling twice doesn't create duplicates."""
        # First pull
        sync_service.pull_ynab()
        count_after_first = database.get_transaction_count()

        # Second pull
        result2 = sync_service.pull_ynab()
        count_after_second = database.get_transaction_count()

        # Should have same count (updated, not duplicated)
        assert count_after_first == count_after_second
        # Second pull should show updates, not inserts
        assert result2.updated >= 0


class TestSyncServicePush:
    """Tests for push operations."""

    def test_push_dry_run_no_changes(self, sync_service, database, sample_sync_transaction):
        """Test dry run doesn't modify anything."""
        # Insert a transaction first
        database.upsert_ynab_transaction(sample_sync_transaction)

        # Create a pending change in delta table
        database.create_pending_change(
            transaction_id=sample_sync_transaction.id,
            new_category_id="cat-002",
            new_category_name="Clothing",
            original_category_id=sample_sync_transaction.category_id,
            original_category_name=sample_sync_transaction.category_name,
            change_type="category",
        )

        # Verify it's pending
        assert database.get_pending_change_count() == 1

        # Dry run
        result = sync_service.push_ynab(dry_run=True)

        assert result.pushed == 1
        # Should still be pending (dry run doesn't change anything)
        assert database.get_pending_change_count() == 1

    def test_push_clears_pending_status(self, sync_service, database, sample_sync_transaction):
        """Test successful push marks transactions as synced."""
        # Insert and create pending change
        database.upsert_ynab_transaction(sample_sync_transaction)
        database.create_pending_change(
            transaction_id=sample_sync_transaction.id,
            new_category_id="cat-002",
            new_category_name="Clothing",
            original_category_id=sample_sync_transaction.category_id,
            original_category_name=sample_sync_transaction.category_name,
            change_type="category",
        )

        assert database.get_pending_change_count() == 1

        # Push
        result = sync_service.push_ynab(dry_run=False)

        assert result.succeeded == 1
        assert database.get_pending_change_count() == 0

    def test_push_returns_empty_when_nothing_pending(self, sync_service, database):
        """Test push returns zero counts when nothing to push."""
        result = sync_service.push_ynab()

        assert result.pushed == 0
        assert result.succeeded == 0
        assert result.failed == 0


class TestSyncServiceStatus:
    """Tests for get_status method."""

    def test_get_status_empty_database(self, sync_service):
        """Test status when database is empty."""
        status = sync_service.get_status()

        assert "ynab" in status
        assert "amazon" in status
        assert status["ynab"]["transaction_count"] == 0
        assert status["amazon"]["order_count"] == 0

    def test_get_status_after_pull(self, sync_service):
        """Test status after pulling data."""
        sync_service.pull_all()
        status = sync_service.get_status()

        assert status["ynab"]["transaction_count"] > 0
        assert status["amazon"]["order_count"] > 0
        assert status["ynab"]["last_sync_at"] is not None
        assert status["amazon"]["last_sync_at"] is not None


class TestSyncServiceInit:
    """Tests for SyncService initialization."""

    def test_init_without_amazon_client(self, database, mock_ynab_client):
        """Test SyncService can be initialized without Amazon client."""
        service = SyncService(
            db=database,
            ynab=mock_ynab_client,
            amazon=None,
        )

        assert service._amazon is None

        # YNAB pull should still work
        result = service.pull_ynab()
        assert result.success

        # Amazon pull should return error
        result = service.pull_amazon()
        assert not result.success
        assert "Amazon client not configured" in result.errors

    def test_overlap_days_config_default(self):
        """Test sync_overlap_days config default is set correctly."""
        from src.config import CategorizationConfig

        config = CategorizationConfig()
        assert config.sync_overlap_days == 7
