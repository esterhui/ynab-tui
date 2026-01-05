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
class TransactionDetail:
    """Transaction info for dry-run display."""

    date: datetime
    payee_name: str
    amount: float  # In dollars, not milliunits
    is_conflict: bool = False  # True if YNAB uncategorized but local has category
    local_category: str = ""  # Local category name (for conflict display)


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
        result = PullResult(source="ynab")

        try:
            # Determine since_date for incremental sync
            since_date = None
            if since_days is not None:
                # Explicit day range - skip sync state check
                since_date = datetime.now() - timedelta(days=since_days)
            elif not full:
                sync_state = self._db.get_sync_state("ynab")
                if sync_state and sync_state.get("last_sync_date"):
                    # Go back sync_overlap_days to catch any delayed transactions
                    overlap_days = self._cat_config.sync_overlap_days
                    since_date = sync_state["last_sync_date"] - timedelta(days=overlap_days)

            # Fetch transactions from YNAB
            transactions = self._ynab.get_all_transactions(since_date=since_date)
            result.fetched = len(transactions)

            if transactions:
                # Find date range of fetched transactions
                result.oldest_date = min(t.date for t in transactions)
                result.newest_date = max(t.date for t in transactions)

                if not dry_run:
                    # Upsert into database with progress bar
                    with tqdm(
                        total=len(transactions), desc="Storing transactions", unit="txn"
                    ) as pbar:
                        inserted, updated = self._db.upsert_ynab_transactions(transactions)
                        pbar.update(len(transactions))
                    result.inserted = inserted
                    result.updated = updated

                    # Check for conflicts and optionally fix them
                    conflicts = self._db.get_conflict_transactions()
                    result.conflicts_found = len(conflicts)
                    if fix and conflicts:
                        for conflict in conflicts:
                            if self._db.fix_conflict_transaction(conflict["id"]):
                                result.conflicts_fixed += 1
                                result.fixed_conflicts.append(conflict)
                else:
                    # Dry run - compare fetched with database to get accurate counts
                    for txn in transactions:
                        existing = self._db.get_ynab_transaction(txn.id)
                        # Detect conflict: local has category but YNAB says uncategorized
                        is_conflict = bool(
                            existing and existing["category_id"] and not txn.category_id
                        )
                        local_category = (
                            existing["category_name"] if existing and is_conflict else ""
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
                            # Check if data would change (simplified comparison)
                            new_date = txn.date.strftime("%Y-%m-%d")
                            # Skip category_id comparison for split transactions
                            # (Split pseudo-category ID varies, but category_name="Split" is consistent)
                            is_split_match = (
                                existing["is_split"]
                                and txn.is_split
                                and existing["category_name"] == "Split"
                                and txn.category_name == "Split"
                            )
                            category_changed = (
                                not is_split_match and existing["category_id"] != txn.category_id
                            )
                            if (
                                existing["date"][:10] != new_date
                                or existing["amount"] != txn.amount
                                or existing["payee_name"] != txn.payee_name
                                or category_changed
                                or existing["memo"] != txn.memo
                                or existing["approved"] != txn.approved
                            ):
                                result.updated += 1
                                result.details_to_update.append(detail)
                            if is_conflict:
                                result.conflicts_found += 1
                        else:
                            result.inserted += 1
                            result.details_to_insert.append(detail)

            # Update sync state (skip in dry run)
            result.total = self._db.get_transaction_count()
            if not dry_run and (transactions or result.total > 0):
                self._db.update_sync_state("ynab", datetime.now(), result.total)

        except Exception as e:
            result.errors.append(str(e))

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
        result = PushResult()

        try:
            # Get pending changes from delta table
            pending_changes = self._db.get_all_pending_changes()
            result.pushed = len(pending_changes)

            if dry_run or result.pushed == 0:
                # Build summary for display
                result.summary = self._build_push_summary(pending_changes)
                return result

            # Push each change
            total_changes = len(pending_changes)
            for idx, change in enumerate(pending_changes):
                try:
                    txn_id = change["transaction_id"]
                    change_type = change.get("change_type")
                    updated_txn = None
                    verified = False

                    if change_type == "split":
                        # Handle split transaction
                        pending_splits = self._db.get_pending_splits(txn_id)
                        if pending_splits:
                            # Create split transaction in YNAB
                            updated_txn = self._ynab.create_split_transaction(
                                transaction_id=txn_id,
                                splits=pending_splits,
                                approve=True,
                            )
                            # Verify: split transactions have category_name "Split" and approved
                            verified = (
                                updated_txn.category_name == "Split"
                                or updated_txn.category_id is None
                            ) and updated_txn.approved is True
                            if verified:
                                # Clear pending splits after successful push
                                self._db.clear_pending_splits(txn_id)
                                # Save subtransactions to database (they're in updated_txn)
                                self._db.upsert_ynab_transaction(updated_txn)
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

                        # Use generic update method
                        updated_txn = self._ynab.update_transaction(
                            transaction_id=txn_id,
                            category_id=new_values.get("category_id"),
                            memo=new_values.get("memo"),
                            approved=new_values.get("approved", True),  # Default approve
                        )

                        # Verify: all pushed values match returned transaction
                        verified = True
                        if "category_id" in new_values and new_values["category_id"]:
                            verified = verified and (
                                updated_txn.category_id == new_values["category_id"]
                            )
                        if "memo" in new_values:
                            # memo="" is valid (clears memo)
                            verified = verified and (updated_txn.memo == new_values["memo"])
                        if "approved" in new_values:
                            verified = verified and (updated_txn.approved == new_values["approved"])

                        # Log push verification result for debugging
                        logger.info(
                            f"Push {txn_id}: sent category={new_values.get('category_id')}, "
                            f"received category={updated_txn.category_id}, verified={verified}"
                        )
                        if not verified:
                            logger.warning(
                                f"Push verification FAILED for {txn_id}: "
                                f"sent={new_values}, received category={updated_txn.category_id}, "
                                f"approved={updated_txn.approved}"
                            )

                    if verified:
                        # Apply change to ynab_transactions and cleanup pending_changes
                        self._db.apply_pending_change(txn_id)
                        result.succeeded += 1
                        result.pushed_ids.append(txn_id)
                    else:
                        # YNAB returned different data than expected - keep in pending
                        result.failed += 1
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

                # Report progress after each transaction
                if progress_callback:
                    progress_callback(idx + 1, total_changes)

            # If using MockYNABClient, persist updates to CSV
            if hasattr(self._ynab, "save_transactions"):
                self._ynab.save_transactions()

        except Exception as e:
            result.errors.append(str(e))

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
