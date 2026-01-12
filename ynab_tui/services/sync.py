"""Sync service for pulling/pushing data between YNAB, Amazon, and local database.

Provides git-style pull/push operations:
- pull: Download data from YNAB/Amazon to local SQLite database
- push: Upload local changes (categorizations) to YNAB
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable, Optional, Union

from tqdm import tqdm

from ynab_tui.config import AmazonConfig, CategorizationConfig

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..clients import AmazonClient, MockAmazonClient, MockYNABClient, YNABClient
    from ..db.database import Database


@dataclass
class CategoryDetail:
    """Category info for dry-run display."""

    name: str
    group_name: str


@dataclass
class FieldChange:
    """Represents a single field that changed during sync."""

    field_name: str
    old_value: Any
    new_value: Any


@dataclass
class TransactionDetail:
    """Transaction info for dry-run display."""

    date: datetime
    payee_name: str
    amount: float  # In dollars, not milliunits
    is_conflict: bool = False  # True if YNAB uncategorized but local has category
    local_category: str = ""  # Local category name (for conflict display)
    changed_fields: list[FieldChange] = field(default_factory=list)

    @property
    def changed_field_summary(self) -> str:
        """Return comma-separated list of changed field names."""
        if not self.changed_fields:
            return ""
        return ", ".join(f.field_name for f in self.changed_fields)


@dataclass
class AmazonOrderDetail:
    """Amazon order info for dry-run display."""

    order_id: str
    order_date: datetime
    total: float


@dataclass
class PullResult:
    """Result of a pull operation."""

    source: str  # 'ynab', 'amazon', or 'categories'
    fetched: int = 0  # Records fetched from API
    inserted: int = 0
    updated: int = 0
    total: int = 0  # Total in DB after pull
    errors: list[str] = field(default_factory=list)
    # Date range of fetched records
    oldest_date: Optional[datetime] = None
    newest_date: Optional[datetime] = None
    # Detailed items for dry-run display
    details_to_insert: list[Any] = field(default_factory=list)
    details_to_update: list[Any] = field(default_factory=list)
    # Conflict tracking
    conflicts_found: int = 0  # Number of conflicts detected
    conflicts_fixed: int = 0  # Number of conflicts marked for push (--fix)
    fixed_conflicts: list[dict] = field(default_factory=list)  # Details of fixed conflicts
    # Category history backfill tracking
    history_backfill_needed: bool = False
    history_backfill_count: int = 0  # Number of entries to backfill (or backfilled)

    @property
    def success(self) -> bool:
        """Check if pull was successful (no errors)."""
        return len(self.errors) == 0


@dataclass
class PushResult:
    """Result of a push operation."""

    pushed: int = 0  # Records attempted to push
    succeeded: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    pushed_ids: list[str] = field(default_factory=list)  # Successfully pushed IDs
    summary: str = ""  # Human-readable summary of pending changes

    @property
    def success(self) -> bool:
        """Check if all pushes succeeded."""
        return self.failed == 0 and len(self.errors) == 0


class SyncService:
    """Service for syncing data between YNAB, Amazon, and local database.

    Git-style nomenclature:
    - pull: Download from remote (YNAB/Amazon) to local (SQLite)
    - push: Upload local changes to remote (YNAB)
    """

    def __init__(
        self,
        db: Database,
        ynab: Union["YNABClient", "MockYNABClient"],
        amazon: Optional[Union["AmazonClient", "MockAmazonClient"]] = None,
        categorization_config: Optional[CategorizationConfig] = None,
        amazon_config: Optional[AmazonConfig] = None,
    ):
        """Initialize sync service.

        Args:
            db: Database instance for local storage.
            ynab: YNAB client (real or mock).
            amazon: Amazon client (real or mock), optional.
            categorization_config: Categorization settings (sync overlap, etc.).
            amazon_config: Amazon settings (earliest year, etc.).
        """
        self._db = db
        self._ynab = ynab
        self._amazon = amazon
        self._cat_config = categorization_config or CategorizationConfig()
        self._amazon_config = amazon_config or AmazonConfig()

    def _fetch_all_amazon_orders(self, description: str) -> list:
        """Fetch Amazon orders for all years from current back to earliest_history_year.

        Args:
            description: Progress bar description (e.g., "Fetching Amazon orders")

        Returns:
            List of all fetched orders.
        """
        if not self._amazon:
            return []

        current_year = datetime.now().year
        earliest_year = self._amazon_config.earliest_history_year
        years = list(range(current_year, earliest_year - 1, -1))
        orders = []
        for year in tqdm(years, desc=description, unit="year"):
            try:
                year_orders = self._amazon.get_orders_for_year(year)
                if year_orders:
                    orders.extend(year_orders)
            except Exception as e:
                logger.debug("Failed to fetch Amazon orders for year %d: %s", year, e)
        return orders

    def _compute_expected_transaction(
        self,
        local_txn: dict,
        pending_change: dict,
    ) -> dict:
        """Compute expected transaction state after applying pending change.

        Merges the local transaction with the pending change to determine
        what the YNAB response should contain after a successful push.

        Args:
            local_txn: Current transaction from local database.
            pending_change: Pending change with new_values.

        Returns:
            Dict with expected values for key fields.
        """
        expected = dict(local_txn)  # Copy local state
        new_values = pending_change.get("new_values", {})

        # Fallback to legacy columns if new_values is empty
        if not new_values:
            new_values = {}
            if pending_change.get("new_category_id"):
                new_values["category_id"] = pending_change["new_category_id"]
                new_values["category_name"] = pending_change.get("new_category_name")
            if pending_change.get("new_approved") is not None:
                new_values["approved"] = pending_change["new_approved"]

        # Apply pending change values
        for key in ["category_id", "category_name", "memo", "approved"]:
            if key in new_values:
                expected[key] = new_values[key]

        return expected

    def pull_ynab(
        self,
        full: bool = False,
        since_days: Optional[int] = None,
        dry_run: bool = False,
        fix: bool = False,
    ) -> PullResult:
        """Pull YNAB transactions to local database.

        Args:
            full: If True, pull all transactions. If False, incremental from last sync.
            since_days: If provided, fetch transactions from the last N days (ignores sync state).
            dry_run: If True, fetch but don't write to database.
            fix: If True, mark conflicts as pending_push so next push will update YNAB.

        Returns:
            PullResult with statistics.
        """
        logger.debug(
            "pull_ynab started: full=%s, since_days=%s, dry_run=%s, fix=%s",
            full,
            since_days,
            dry_run,
            fix,
        )
        result = PullResult(source="ynab")

        try:
            # Determine since_date for incremental sync
            since_date = None
            if since_days is not None:
                # Explicit day range - skip sync state check
                since_date = datetime.now() - timedelta(days=since_days)
                logger.debug("Using explicit since_days=%d, since_date=%s", since_days, since_date)
            elif not full:
                sync_state = self._db.get_sync_state("ynab")
                if sync_state and sync_state.get("last_sync_date"):
                    # Go back sync_overlap_days to catch any delayed transactions
                    overlap_days = self._cat_config.sync_overlap_days
                    since_date = sync_state["last_sync_date"] - timedelta(days=overlap_days)
                    logger.debug(
                        "Incremental sync: last_sync=%s, overlap=%d days, since_date=%s",
                        sync_state["last_sync_date"],
                        overlap_days,
                        since_date,
                    )
                else:
                    logger.debug("No sync state found, will fetch all transactions")
            else:
                logger.debug("Full sync requested, fetching all transactions")

            # Fetch transactions from YNAB
            logger.debug("Fetching transactions from YNAB API (since_date=%s)", since_date)
            transactions = self._ynab.get_all_transactions(since_date=since_date)
            logger.debug("Fetched %d transactions from YNAB", len(transactions))
            result.fetched = len(transactions)

            if transactions:
                # Find date range of fetched transactions
                result.oldest_date = min(t.date for t in transactions)
                result.newest_date = max(t.date for t in transactions)

                # Compare fetched with database to get change details
                for txn in transactions:
                    existing = self._db.get_ynab_transaction(txn.id)
                    # Check for pending change - if exists, not a conflict
                    pending = self._db.get_pending_change(txn.id)
                    # Detect conflict: local has category but YNAB says uncategorized
                    # (but not if there's already a pending change for this transaction)
                    is_conflict = bool(
                        existing and existing["category_id"] and not txn.category_id and not pending
                    )
                    local_category = existing["category_name"] if existing and is_conflict else ""

                    # Log conflict detection details
                    if is_conflict and existing:
                        logger.info(
                            "CONFLICT detected for txn %s (%s, $%.2f): "
                            "local_category='%s' (id=%s), YNAB returned category_id=%s",
                            txn.id,
                            txn.payee_name,
                            txn.amount,
                            existing["category_name"],
                            existing["category_id"],
                            txn.category_id,
                        )
                    elif existing and existing["category_id"] and txn.category_id:
                        # Log when categories match (DEBUG level)
                        if existing["category_id"] != txn.category_id:
                            logger.debug(
                                "Category changed for txn %s: local='%s' -> YNAB='%s'",
                                txn.id,
                                existing["category_name"],
                                txn.category_name,
                            )
                    # txn.amount is already in dollars (converted in _convert_transaction)
                    detail = TransactionDetail(
                        date=txn.date,
                        payee_name=txn.payee_name or "",
                        amount=txn.amount,
                        is_conflict=is_conflict,
                        local_category=local_category or "",
                    )
                    if existing:
                        # Skip transactions with pending changes - pull won't update them
                        if pending:
                            continue

                        # Check if data would change and track which fields
                        new_date = txn.date.strftime("%Y-%m-%d")
                        changed_fields: list[FieldChange] = []

                        if existing["date"][:10] != new_date:
                            changed_fields.append(
                                FieldChange("date", existing["date"][:10], new_date)
                            )
                        if existing["amount"] != txn.amount:
                            changed_fields.append(
                                FieldChange("amount", existing["amount"], txn.amount)
                            )
                        if existing["payee_name"] != txn.payee_name:
                            changed_fields.append(
                                FieldChange("payee", existing["payee_name"], txn.payee_name)
                            )
                        # Skip category comparison for split transactions
                        # (Split pseudo-category ID varies, but category_name="Split" is consistent)
                        is_split_match = (
                            existing["is_split"]
                            and txn.is_split
                            and existing["category_name"] == "Split"
                            and txn.category_name == "Split"
                        )
                        if not is_split_match and existing["category_id"] != txn.category_id:
                            changed_fields.append(
                                FieldChange(
                                    "category",
                                    existing["category_name"] or "Uncategorized",
                                    txn.category_name or "Uncategorized",
                                )
                            )
                        if existing["memo"] != txn.memo:
                            changed_fields.append(
                                FieldChange("memo", existing["memo"] or "", txn.memo or "")
                            )
                        if existing["approved"] != txn.approved:
                            changed_fields.append(
                                FieldChange("approved", existing["approved"], txn.approved)
                            )

                        if changed_fields:
                            detail.changed_fields = changed_fields
                            result.updated += 1
                            result.details_to_update.append(detail)
                            # Log each transaction being updated
                            changes_summary = ", ".join(
                                f"{f.field_name}: {f.old_value!r} -> {f.new_value!r}"
                                for f in changed_fields
                            )
                            logger.debug(
                                "UPDATE txn %s (%s $%.2f): %s",
                                txn.id,
                                txn.payee_name,
                                txn.amount,
                                changes_summary,
                            )
                        if is_conflict:
                            result.conflicts_found += 1
                    else:
                        result.inserted += 1
                        result.details_to_insert.append(detail)
                        # Log new transactions being inserted
                        logger.debug(
                            "INSERT txn %s (%s $%.2f) category='%s'",
                            txn.id,
                            txn.payee_name,
                            txn.amount,
                            txn.category_name or "Uncategorized",
                        )

                if not dry_run:
                    # Upsert into database with progress bar
                    with tqdm(
                        total=len(transactions), desc="Storing transactions", unit="txn"
                    ) as pbar:
                        inserted, updated = self._db.upsert_ynab_transactions(transactions)
                        pbar.update(len(transactions))
                    # Use DB counts (more accurate than our comparison for edge cases)
                    result.inserted = inserted
                    result.updated = updated

                    # Backfill categorization history if needed (first run or sparse data)
                    if self._db.needs_history_backfill():
                        result.history_backfill_needed = True
                        logger.info("Backfilling categorization history from transactions...")
                        with tqdm(desc="Building category history", unit="txn") as pbar:

                            def update_progress(current: int, total: int) -> None:
                                pbar.total = total
                                pbar.n = current
                                pbar.refresh()

                            added = self._db.backfill_categorization_history(
                                progress_callback=update_progress
                            )
                            result.history_backfill_count = added
                            logger.info("Backfilled %d entries into categorization history", added)
                    else:
                        # Just add newly categorized transactions to history
                        for txn in transactions:
                            if txn.category_id and txn.payee_name:
                                self._db.add_categorization(
                                    payee_name=txn.payee_name,
                                    category_name=txn.category_name or "",
                                    category_id=txn.category_id,
                                    amount=txn.amount,
                                    transaction_id=txn.id,
                                    transaction_date=txn.date,
                                )

                    # Check for conflicts and optionally fix them
                    conflicts = self._db.get_conflict_transactions()
                    result.conflicts_found = len(conflicts)
                    if fix and conflicts:
                        for conflict in conflicts:
                            if self._db.fix_conflict_transaction(conflict["id"]):
                                result.conflicts_fixed += 1
                                result.fixed_conflicts.append(conflict)
                else:
                    # Dry run: check if backfill would be needed and estimate count
                    if self._db.needs_history_backfill():
                        result.history_backfill_needed = True
                        # Count categorized transactions that would be backfilled
                        with self._db._connection() as conn:
                            row = conn.execute(
                                """SELECT COUNT(*) as count FROM ynab_transactions
                                WHERE category_id IS NOT NULL AND category_id != ''
                                AND payee_name IS NOT NULL
                                AND NOT EXISTS (
                                    SELECT 1 FROM categorization_history h
                                    WHERE h.transaction_id = ynab_transactions.id
                                )"""
                            ).fetchone()
                            result.history_backfill_count = row["count"] if row else 0

            # Update sync state (skip in dry run)
            result.total = self._db.get_transaction_count()
            if not dry_run and (transactions or result.total > 0):
                self._db.update_sync_state("ynab", datetime.now(), result.total)

            # Log pull summary
            logger.info(
                "Pull complete (dry_run=%s): fetched=%d, inserted=%d, updated=%d, conflicts=%d",
                dry_run,
                result.fetched,
                result.inserted,
                result.updated,
                result.conflicts_found,
            )

        except Exception as e:
            result.errors.append(str(e))
            logger.exception("Exception during pull_ynab")

        return result

    def pull_amazon(
        self,
        full: bool = False,
        year: Optional[int] = None,
        since_days: Optional[int] = None,
        dry_run: bool = False,
    ) -> PullResult:
        """Pull Amazon orders to local database.

        Args:
            full: If True, pull all orders. If False, incremental.
            year: Specific year to pull (overrides incremental logic).
            since_days: Fetch orders from last N days (ignores sync state).
            dry_run: If True, fetch but don't write to database.

        Returns:
            PullResult with statistics.
        """
        result = PullResult(source="amazon")

        if not self._amazon:
            result.errors.append("Amazon client not configured")
            return result

        try:
            # Determine what to fetch
            if year:
                # Specific year requested
                orders = self._amazon.get_orders_for_year(year)
            elif full:
                # Full sync - fetch all available history
                orders = self._fetch_all_amazon_orders("Fetching Amazon orders")
            elif since_days is not None:
                # Explicit day range - skip sync state check
                orders = self._amazon.get_recent_orders(days=since_days)
            else:
                # Incremental - get recent orders
                sync_state = self._db.get_sync_state("amazon")
                if sync_state and sync_state.get("last_sync_date"):
                    overlap_days = self._cat_config.sync_overlap_days
                    days_since = (datetime.now() - sync_state["last_sync_date"]).days + overlap_days
                    orders = self._amazon.get_recent_orders(days=days_since)
                else:
                    # First sync - fetch all available history (same as --full)
                    orders = self._fetch_all_amazon_orders("First sync: fetching all Amazon orders")

            result.fetched = len(orders)

            if orders:
                result.oldest_date = min(o.order_date for o in orders)
                result.newest_date = max(o.order_date for o in orders)

            if not dry_run:
                # Cache orders and store items
                for order in tqdm(orders, desc="Storing orders", unit="order", leave=False):
                    # Cache the order header - returns (was_inserted, was_changed)
                    was_inserted, was_changed = self._db.cache_amazon_order(
                        order_id=order.order_id,
                        order_date=order.order_date,
                        total=order.total,
                    )

                    if was_inserted:
                        result.inserted += 1
                    elif was_changed:
                        result.updated += 1
                    # If not inserted and not changed, don't count it

                    # Store individual items (source of truth for item data)
                    items = [
                        {
                            "name": item.name,
                            "price": item.price if hasattr(item, "price") else None,
                            "quantity": item.quantity if hasattr(item, "quantity") else 1,
                        }
                        for item in order.items
                    ]
                    self._db.upsert_amazon_order_items(order.order_id, items)

                # Update sync state
                result.total = self._db.get_order_count()
                if orders or result.total > 0:
                    self._db.update_sync_state("amazon", datetime.now(), result.total)
            else:
                # Dry run - compare fetched with database to get accurate counts
                for order in orders:
                    existing = self._db.get_cached_order(order.order_id)
                    detail = AmazonOrderDetail(
                        order_id=order.order_id,
                        order_date=order.order_date,
                        total=order.total,
                    )
                    if existing:
                        # Check if data would change
                        new_date = order.order_date.strftime("%Y-%m-%d")
                        if existing["order_date"] != new_date or existing["total"] != order.total:
                            result.updated += 1
                            result.details_to_update.append(detail)
                    else:
                        result.inserted += 1
                        result.details_to_insert.append(detail)
                result.total = self._db.get_order_count()

        except Exception as e:
            result.errors.append(str(e))

        return result

    def pull_categories(self, dry_run: bool = False) -> PullResult:
        """Pull YNAB categories to local database.

        Categories are always fully synced (no incremental).

        Args:
            dry_run: If True, fetch but don't write to database.

        Returns:
            PullResult with statistics.
        """
        result = PullResult(source="categories")

        try:
            # Fetch categories from YNAB
            category_list = self._ynab.get_categories()

            # Count total categories
            total_fetched = sum(len(g.categories) for g in category_list.groups)
            result.fetched = total_fetched

            if not dry_run:
                # Upsert into database
                inserted, updated = self._db.upsert_categories(category_list)
                result.inserted = inserted
                result.updated = updated

                # Update sync state and total
                result.total = self._db.get_category_count()
                self._db.update_sync_state("categories", datetime.now(), result.total)
            else:
                # Dry run - compare fetched with database to get accurate counts
                for group in category_list.groups:
                    for cat in group.categories:
                        existing = self._db.get_category_by_id(cat.id)
                        detail = CategoryDetail(name=cat.name, group_name=group.name)
                        if existing:
                            # Check if data would change
                            if (
                                existing["name"] != cat.name
                                or existing["group_name"] != group.name
                                or existing["hidden"] != cat.hidden
                                or existing["deleted"] != cat.deleted
                            ):
                                result.updated += 1
                                result.details_to_update.append(detail)
                        else:
                            result.inserted += 1
                            result.details_to_insert.append(detail)
                result.total = self._db.get_category_count()

        except Exception as e:
            result.errors.append(str(e))

        return result

    def pull_all(self, full: bool = False) -> dict[str, PullResult]:
        """Pull YNAB categories, transactions, and Amazon data.

        Args:
            full: If True, full sync. If False, incremental.

        Returns:
            Dict with 'categories', 'ynab', and 'amazon' PullResults.
        """
        return {
            "categories": self.pull_categories(),
            "ynab": self.pull_ynab(full=full),
            "amazon": self.pull_amazon(full=full),
        }

    def push_ynab(
        self,
        dry_run: bool = False,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> PushResult:
        """Push pending local changes to YNAB.

        IMPORTANT: This only runs when explicitly called. Never automatic.

        Uses the pending_changes delta table to track what needs pushing.
        After successful push, updates ynab_transactions with the changes.

        Args:
            dry_run: If True, show what would be pushed without making changes.
            progress_callback: Optional callback(current, total) for progress updates.

        Returns:
            PushResult with statistics.
        """
        logger.debug("push_ynab started: dry_run=%s", dry_run)
        result = PushResult()

        try:
            # Get pending changes from delta table
            pending_changes = self._db.get_all_pending_changes()
            result.pushed = len(pending_changes)
            logger.debug("Found %d pending changes to push", len(pending_changes))

            if dry_run or result.pushed == 0:
                # Build summary for display
                result.summary = self._build_push_summary(pending_changes)
                logger.info(
                    "Push complete (dry_run=%s): %d pending changes, no changes made",
                    dry_run,
                    result.pushed,
                )
                return result

            # Push each change
            total_changes = len(pending_changes)
            logger.info("Starting push of %d changes to YNAB", total_changes)
            for idx, change in enumerate(pending_changes):
                try:
                    txn_id = change["transaction_id"]
                    change_type = change.get("change_type")
                    updated_txn = None
                    verified = False

                    if change_type == "split":
                        # Handle split transaction
                        logger.debug(
                            "Processing SPLIT for txn %s (%d/%d)", txn_id, idx + 1, total_changes
                        )
                        pending_splits = self._db.get_pending_splits(txn_id)
                        if pending_splits:
                            logger.debug(
                                "Sending split to YNAB: txn=%s, splits=%d",
                                txn_id,
                                len(pending_splits),
                            )
                            # Create split transaction in YNAB
                            updated_txn = self._ynab.create_split_transaction(
                                transaction_id=txn_id,
                                splits=pending_splits,
                                approve=True,
                            )
                            # Verify: YNAB returns category_name="Split" and approved
                            # (YNAB also assigns a budget-specific Split category_id)
                            verified = (
                                updated_txn.category_name == "Split"
                                and updated_txn.approved is True
                            )
                            logger.info(
                                "Split push %s: YNAB returned category_name='%s', "
                                "approved=%s, verified=%s",
                                txn_id,
                                updated_txn.category_name,
                                updated_txn.approved,
                                verified,
                            )
                            if verified:
                                # Clear pending splits after successful push
                                self._db.clear_pending_splits(txn_id)
                                # Save subtransactions to database (they're in updated_txn)
                                self._db.upsert_ynab_transaction(updated_txn)
                                logger.debug(
                                    "Split %s: cleared pending, saved subtransactions", txn_id
                                )
                    else:
                        # Generic update - handles category, memo, approval
                        new_values = change.get("new_values", {})

                        # Fallback to legacy columns if new_values is empty
                        if not new_values:
                            new_values = {}
                            if change.get("new_category_id"):
                                new_values["category_id"] = change["new_category_id"]
                            if change.get("new_approved") is not None:
                                new_values["approved"] = change["new_approved"]

                        # Log what we're about to send
                        logger.debug(
                            "Processing UPDATE for txn %s (%d/%d): payee='%s', amount=%.2f",
                            txn_id,
                            idx + 1,
                            total_changes,
                            change.get("payee_name", "?"),
                            change.get("amount", 0),
                        )
                        logger.debug(
                            "Sending to YNAB: txn=%s, category_id=%s, memo=%s, approved=%s",
                            txn_id,
                            new_values.get("category_id"),
                            repr(new_values.get("memo")) if "memo" in new_values else "(unchanged)",
                            new_values.get("approved", True),
                        )

                        # Use generic update method
                        updated_txn = self._ynab.update_transaction(
                            transaction_id=txn_id,
                            category_id=new_values.get("category_id"),
                            memo=new_values.get("memo"),
                            approved=new_values.get("approved", True),  # Default approve
                        )

                        # Log what YNAB returned
                        logger.debug(
                            "YNAB response for %s: category_id=%s, category_name='%s', "
                            "memo=%s, approved=%s",
                            txn_id,
                            updated_txn.category_id,
                            updated_txn.category_name,
                            repr(updated_txn.memo),
                            updated_txn.approved,
                        )

                        # Comprehensive verification: compare YNAB response to expected state
                        # This catches unexpected changes to fields we didn't intend to modify
                        local_txn = self._db.get_ynab_transaction(txn_id)
                        if local_txn is None:
                            logger.warning(
                                "Cannot verify push for %s: transaction not found in local DB",
                                txn_id,
                            )
                            local_txn = {}  # Fall back to empty dict for verification
                        expected = self._compute_expected_transaction(local_txn, change)

                        verified = True
                        verify_details = []

                        # Check important fields - detect unexpected clearing
                        # category_name is derived from category_id, so skip it if category_id changed
                        category_id_changed = "category_id" in new_values
                        fields_to_verify = ["category_id", "memo", "approved"]
                        if not category_id_changed:
                            # Only verify category_name if we didn't change category_id
                            # (YNAB will return new category_name when category_id changes)
                            fields_to_verify.append("category_name")

                        for field in fields_to_verify:
                            expected_val = expected.get(field)
                            actual_val = getattr(updated_txn, field, None)
                            field_match = expected_val == actual_val
                            if not field_match:
                                verified = False
                                verify_details.append(
                                    f"{field}: expected={repr(expected_val)}, "
                                    f"got={repr(actual_val)}"
                                )

                        # Log detailed verification results
                        if verify_details:
                            logger.info(
                                "Push verification for %s: verified=%s | %s",
                                txn_id,
                                verified,
                                " | ".join(verify_details),
                            )
                        else:
                            logger.debug(
                                "Push verification for %s: verified=%s (all fields match)",
                                txn_id,
                                verified,
                            )
                        if not verified:
                            logger.warning(
                                "Push verification FAILED for %s: unexpected changes detected. "
                                "Mismatches: %s",
                                txn_id,
                                "; ".join(verify_details),
                            )

                    if verified:
                        if change_type == "split":
                            # Split already saved via upsert_ynab_transaction with YNAB's
                            # category_id, just cleanup pending_changes
                            self._db.delete_pending_change(txn_id)
                        else:
                            # Apply change to ynab_transactions and cleanup pending_changes
                            self._db.apply_pending_change(txn_id)
                        result.succeeded += 1
                        result.pushed_ids.append(txn_id)
                        logger.debug(
                            "Push SUCCESS for %s: applied change, deleted pending_change", txn_id
                        )
                    else:
                        # YNAB returned different data than expected - keep in pending
                        result.failed += 1
                        logger.warning(
                            "Push FAILED for %s: keeping in pending_changes for retry", txn_id
                        )
                        if updated_txn:
                            result.errors.append(
                                f"Verification failed for {txn_id}: "
                                f"category={updated_txn.category_id}, approved={updated_txn.approved}"
                            )
                        else:
                            result.errors.append(
                                f"Verification failed for {txn_id}: no transaction returned"
                            )

                except Exception as e:
                    result.failed += 1
                    result.errors.append(f"Failed to push {change['transaction_id']}: {e}")
                    logger.exception("Exception during push for %s", change["transaction_id"])

                # Report progress after each transaction
                if progress_callback:
                    progress_callback(idx + 1, total_changes)

            # If using MockYNABClient, persist updates to CSV
            if hasattr(self._ynab, "save_transactions"):
                self._ynab.save_transactions()

            # Log push summary
            logger.info(
                "Push complete: %d succeeded, %d failed out of %d total",
                result.succeeded,
                result.failed,
                total_changes,
            )

        except Exception as e:
            result.errors.append(str(e))
            logger.exception("Exception during push_ynab")

        return result

    def _build_push_summary(self, pending_changes: list[dict]) -> str:
        """Build human-readable summary of pending changes.

        Args:
            pending_changes: List of pending change dicts with transaction info.

        Returns:
            Formatted string summary.
        """
        if not pending_changes:
            return "No pending changes."

        lines = []
        for change in pending_changes:
            new_values = change.get("new_values", {})
            original_values = change.get("original_values", {})

            # Category change info (fallback to legacy columns)
            old_cat = (
                original_values.get("category_name")
                or change.get("original_category_name")
                or "Uncategorized"
            )
            new_cat = new_values.get("category_name") or change.get("new_category_name") or "Split"
            date_str = str(change.get("date", ""))[:10]
            payee = (change.get("payee_name") or "")[:30]
            amount = change.get("amount", 0)

            # Build change description
            changes_desc = []
            if new_values.get("category_id") or change.get("new_category_id"):
                changes_desc.append(f"{old_cat} -> {new_cat}")
            if "memo" in new_values:
                memo_preview = (new_values["memo"] or "(cleared)")[:20]
                changes_desc.append(f"memo: {memo_preview}")
            if not changes_desc and new_values.get("approved"):
                changes_desc.append("approved")

            change_str = ", ".join(changes_desc) if changes_desc else "update"
            lines.append(f"{date_str}  {payee:<30}  {amount:>10.2f}  {change_str}")

        return "\n".join(lines)

    def get_status(self) -> dict:
        """Get current sync status.

        Returns:
            Dict with database statistics and sync state.
        """
        ynab_state = self._db.get_sync_state("ynab")
        amazon_state = self._db.get_sync_state("amazon")
        categories_state = self._db.get_sync_state("categories")

        txn_earliest, txn_latest = self._db.get_transaction_date_range()
        order_earliest, order_latest = self._db.get_order_date_range()

        return {
            "categories": {
                "count": self._db.get_category_count(),
                "last_sync_at": categories_state["last_sync_at"] if categories_state else None,
            },
            "ynab": {
                "transaction_count": self._db.get_transaction_count(),
                "uncategorized_count": self._db.get_uncategorized_count(),
                "pending_push_count": self._db.get_pending_change_count(),
                "earliest_date": txn_earliest,
                "latest_date": txn_latest,
                "last_sync_date": ynab_state["last_sync_date"] if ynab_state else None,
                "last_sync_at": ynab_state["last_sync_at"] if ynab_state else None,
            },
            "amazon": {
                "order_count": self._db.get_order_count(),
                "item_count": self._db.get_order_item_count(),
                "earliest_date": order_earliest,
                "latest_date": order_latest,
                "last_sync_date": amazon_state["last_sync_date"] if amazon_state else None,
                "last_sync_at": amazon_state["last_sync_at"] if amazon_state else None,
            },
        }
