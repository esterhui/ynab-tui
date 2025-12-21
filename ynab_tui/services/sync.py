"""Sync service for pulling/pushing data between YNAB, Amazon, and local database.

Provides git-style pull/push operations:
- pull: Download data from YNAB/Amazon to local SQLite database
- push: Upload local changes (categorizations) to YNAB
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Callable, Optional

from tqdm import tqdm

from ynab_tui.config import AmazonConfig, CategorizationConfig

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..clients import AmazonClientProtocol, YNABClientProtocol
    from ..db.database import Database


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
        ynab: YNABClientProtocol,
        amazon: Optional[AmazonClientProtocol] = None,
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

    def pull_ynab(self, full: bool = False) -> PullResult:
        """Pull YNAB transactions to local database.

        Args:
            full: If True, pull all transactions. If False, incremental from last sync.

        Returns:
            PullResult with statistics.
        """
        result = PullResult(source="ynab")

        try:
            # Determine since_date for incremental sync
            since_date = None
            if not full:
                sync_state = self._db.get_sync_state("ynab")
                if sync_state and sync_state.get("last_sync_date"):
                    # Go back sync_overlap_days to catch any delayed transactions
                    overlap_days = self._cat_config.sync_overlap_days
                    since_date = sync_state["last_sync_date"] - timedelta(days=overlap_days)

            # Fetch transactions from YNAB
            transactions = self._ynab.get_all_transactions(since_date=since_date)
            result.fetched = len(transactions)

            # Upsert into database with progress bar
            if transactions:
                with tqdm(total=len(transactions), desc="Storing transactions", unit="txn") as pbar:
                    inserted, updated = self._db.upsert_ynab_transactions(transactions)
                    pbar.update(len(transactions))
                result.inserted = inserted
                result.updated = updated

                # Find date range of fetched transactions
                result.oldest_date = min(t.date for t in transactions)
                result.newest_date = max(t.date for t in transactions)

            # Update sync state
            result.total = self._db.get_transaction_count()
            # Always update sync state with current time (when sync actually ran)
            if transactions or result.total > 0:
                self._db.update_sync_state("ynab", datetime.now(), result.total)

        except Exception as e:
            result.errors.append(str(e))

        return result

    def pull_amazon(
        self,
        full: bool = False,
        year: Optional[int] = None,
        since_days: Optional[int] = None,
    ) -> PullResult:
        """Pull Amazon orders to local database.

        Args:
            full: If True, pull all orders. If False, incremental.
            year: Specific year to pull (overrides incremental logic).
            since_days: Fetch orders from last N days (ignores sync state).

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

            # Update sync state and date range
            result.total = self._db.get_order_count()
            if orders:
                result.oldest_date = min(o.order_date for o in orders)
                result.newest_date = max(o.order_date for o in orders)
            # Always update sync state with current time (when sync actually ran)
            if orders or result.total > 0:
                self._db.update_sync_state("amazon", datetime.now(), result.total)

        except Exception as e:
            result.errors.append(str(e))

        return result

    def pull_categories(self) -> PullResult:
        """Pull YNAB categories to local database.

        Categories are always fully synced (no incremental).

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

            # Upsert into database
            inserted, updated = self._db.upsert_categories(category_list)
            result.inserted = inserted
            result.updated = updated

            # Update sync state and total
            result.total = self._db.get_category_count()
            self._db.update_sync_state("categories", datetime.now(), result.total)

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

                    if verified:
                        # Apply change to ynab_transactions and cleanup pending_changes
                        self._db.apply_pending_change(txn_id)
                        result.succeeded += 1
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
