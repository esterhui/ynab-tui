"""Category mapping service for learning Amazon item categories.

Learns category mappings from historical approved Amazon transactions by:
1. Finding approved Amazon transactions
2. Matching them to Amazon orders
3. Recording which categories were assigned to which items
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..config import CategorizationConfig, PayeesConfig
from ..db.database import AmazonOrderCache, Database
from ..utils import is_amazon_payee
from .amazon_matcher import AmazonOrderMatcher, TransactionInfo


@dataclass
class LearningResult:
    """Results from category learning operation."""

    transactions_processed: int = 0
    transactions_matched: int = 0
    items_learned: int = 0
    items_skipped_no_category: int = 0
    items_skipped_duplicate: int = 0
    split_transactions_skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """True if learning completed without fatal errors."""
        return len(self.errors) == 0


@dataclass
class ItemCategoryPrediction:
    """Prediction result for a single item based on learned mappings."""

    item_name: str
    category_id: str | None
    category_name: str | None
    confidence: float  # 0.0-1.0 based on historical percentage
    occurrence_count: int  # How many times this mapping was seen


@dataclass
class OrderCategoryPrediction:
    """Category predictions for all items in an order."""

    order_id: str
    item_predictions: list[ItemCategoryPrediction]

    @property
    def has_any_predictions(self) -> bool:
        """True if any item has a predicted category."""
        return any(p.category_id for p in self.item_predictions)

    @property
    def dominant_category(self) -> tuple[str, str, float] | None:
        """Return (category_id, category_name, avg_confidence) of most common predicted category.

        Useful for suggesting a single category for the whole order.
        Returns None if no items have predictions.
        """
        # Count categories across all items
        category_counts: dict[str, dict] = {}
        for pred in self.item_predictions:
            if pred.category_id:
                if pred.category_id not in category_counts:
                    category_counts[pred.category_id] = {
                        "name": pred.category_name,
                        "count": 0,
                        "total_confidence": 0.0,
                    }
                category_counts[pred.category_id]["count"] += 1
                category_counts[pred.category_id]["total_confidence"] += pred.confidence

        if not category_counts:
            return None

        # Find the most common category
        best_cat_id = max(category_counts.keys(), key=lambda k: category_counts[k]["count"])
        best = category_counts[best_cat_id]
        avg_confidence = best["total_confidence"] / best["count"]

        return (best_cat_id, best["name"], avg_confidence)


class CategoryMappingService:
    """Service for learning Amazon item → YNAB category mappings.

    Uses historical approved Amazon transactions to build a database of
    which categories are typically assigned to which Amazon items.
    """

    def __init__(
        self,
        db: Database,
        categorization_config: Optional[CategorizationConfig] = None,
        payees_config: Optional[PayeesConfig] = None,
    ):
        """Initialize category mapping service.

        Args:
            db: Database instance.
            categorization_config: Categorization settings (min confidence, etc.).
            payees_config: Payee patterns configuration.
        """
        self._db = db
        self._matcher = AmazonOrderMatcher(db)
        self._cat_config = categorization_config or CategorizationConfig()
        self._payees_config = payees_config or PayeesConfig()
        self._amazon_patterns = self._payees_config.amazon_patterns

    def learn_from_approved_transactions(
        self,
        since_date: datetime | None = None,
        dry_run: bool = False,
    ) -> LearningResult:
        """Learn category mappings from approved Amazon transactions.

        Scans all approved Amazon transactions, matches them to orders,
        and records item → category mappings.

        Args:
            since_date: Only process transactions on or after this date.
            dry_run: If True, don't actually record mappings.

        Returns:
            LearningResult with statistics.
        """
        result = LearningResult()

        # Get approved Amazon transactions
        all_txns = self._db.get_ynab_transactions(approved_only=True)
        amazon_txns = [
            t
            for t in all_txns
            if is_amazon_payee(t.get("payee_name", ""), self._amazon_patterns)
            and t.get("category_id")  # Must have a category
            and t.get("parent_transaction_id") is None  # Not a subtransaction
        ]

        # Filter by date if specified
        if since_date:
            amazon_txns = [t for t in amazon_txns if self._parse_date(t.get("date")) >= since_date]

        if not amazon_txns:
            return result

        result.transactions_processed = len(amazon_txns)

        # Normalize transactions
        txn_infos = [self._matcher.normalize_transaction(t) for t in amazon_txns]

        # Get orders for matching
        orders = self._matcher.get_orders_for_date_range(txn_infos)
        if not orders:
            return result

        # Match transactions to orders
        match_result = self._matcher.match_transactions(txn_infos, orders)

        # Process matched transactions
        for txn_info, order in match_result.all_matches:
            result.transactions_matched += 1

            if txn_info.is_split:
                # Skip split transactions as per plan (user chose "Skip entirely")
                result.split_transactions_skipped += 1
                continue

            # Learn from non-split transaction
            learned = self._learn_from_non_split(txn_info, order, dry_run)
            result.items_learned += learned["new"]
            result.items_skipped_duplicate += learned["duplicate"]
            result.items_skipped_no_category += learned["no_category"]

        return result

    def _learn_from_non_split(
        self,
        txn_info: TransactionInfo,
        order: AmazonOrderCache,
        dry_run: bool = False,
    ) -> dict:
        """Learn from a non-split transaction (all items get same category).

        Args:
            txn_info: The matched transaction.
            order: The matched Amazon order.
            dry_run: If True, don't actually record mappings.

        Returns:
            Dict with counts: {"new": n, "duplicate": n, "no_category": n}
        """
        counts = {"new": 0, "duplicate": 0, "no_category": 0}

        # Must have a category
        if not txn_info.category_id or not txn_info.category_name:
            counts["no_category"] = len(order.items)
            return counts

        # Record each item with the transaction's category
        for item_name in order.items:
            if not item_name or not item_name.strip():
                continue

            if dry_run:
                counts["new"] += 1
            else:
                recorded = self._db.record_item_category_learning(
                    item_name=item_name,
                    category_id=txn_info.category_id,
                    category_name=txn_info.category_name,
                    source_transaction_id=txn_info.transaction_id,
                    source_order_id=order.order_id,
                )
                if recorded:
                    counts["new"] += 1
                else:
                    counts["duplicate"] += 1

        return counts

    def _parse_date(self, date_value) -> datetime:
        """Parse date from string or datetime."""
        if isinstance(date_value, datetime):
            return date_value
        if isinstance(date_value, str):
            return datetime.strptime(date_value[:10], "%Y-%m-%d")
        return datetime.min

    def get_suggested_category(
        self, item_name: str, min_confidence: Optional[float] = None
    ) -> Optional[dict]:
        """Get suggested category for an item based on historical data.

        Args:
            item_name: The item name to look up.
            min_confidence: Minimum confidence (percentage) required.
                           Uses config default if not specified.

        Returns:
            Dict with category_id, category_name, confidence, or None.
        """
        if min_confidence is None:
            min_confidence = self._cat_config.min_category_confidence

        dist = self._db.get_item_category_distribution(item_name)
        if not dist:
            return None

        # Get the most frequent category
        best_cat_id = max(dist.keys(), key=lambda k: dist[k]["count"])
        best = dist[best_cat_id]

        if best["percentage"] < min_confidence:
            return None

        return {
            "category_id": best_cat_id,
            "category_name": best["name"],
            "confidence": best["percentage"],
            "count": best["count"],
        }

    def get_statistics(self) -> dict:
        """Get statistics about learned mappings.

        Returns:
            Dict with total_mappings, unique_items, etc.
        """
        return {
            "total_mappings": self._db.get_item_category_history_count(),
            "unique_items": self._db.get_unique_item_count(),
        }

    def predict_item_category(self, item_name: str) -> ItemCategoryPrediction:
        """Predict category for a single item based on learned mappings.

        Args:
            item_name: The item name to look up.

        Returns:
            ItemCategoryPrediction with the best match (or empty prediction if none).
        """
        dist = self._db.get_item_category_distribution(item_name)
        if not dist:
            return ItemCategoryPrediction(
                item_name=item_name,
                category_id=None,
                category_name=None,
                confidence=0.0,
                occurrence_count=0,
            )

        # Get top category by count
        top_cat_id, top_cat_data = max(dist.items(), key=lambda x: x[1]["count"])
        return ItemCategoryPrediction(
            item_name=item_name,
            category_id=top_cat_id,
            category_name=top_cat_data["name"],
            confidence=top_cat_data["percentage"],
            occurrence_count=top_cat_data["count"],
        )

    def predict_order_categories(self, order: AmazonOrderCache) -> OrderCategoryPrediction:
        """Predict categories for all items in an order.

        Args:
            order: The Amazon order to predict categories for.

        Returns:
            OrderCategoryPrediction with predictions for each item.
        """
        predictions = [self.predict_item_category(item) for item in order.items]
        return OrderCategoryPrediction(order.order_id, predictions)
