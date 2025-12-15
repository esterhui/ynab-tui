"""Transaction matching service.

Matches YNAB transactions to Amazon orders based on:
- Amount (with small tolerance)
- Date (within configurable window)

Uses database cache for Amazon order lookups (data populated via 'pull' command).
"""

import logging
from datetime import datetime
from typing import Optional

from ..config import CategorizationConfig, PayeesConfig
from ..db.database import AmazonOrderCache, Database
from ..models import AmazonOrder, OrderItem, OrderMatch, Transaction
from ..utils import is_amazon_payee
from .amazon_matcher import AmazonOrderMatcher, TransactionInfo

logger = logging.getLogger(__name__)


class TransactionMatcher:
    """Service for matching transactions to Amazon orders."""

    def __init__(
        self,
        db: Database,
        categorization_config: CategorizationConfig,
        payees_config: PayeesConfig,
    ):
        """Initialize matcher.

        Args:
            db: Database for cached Amazon order lookups.
            categorization_config: Config for matching parameters.
            payees_config: Config for identifying Amazon payees.
        """
        self._db = db
        self._window_days = categorization_config.date_match_window_days
        self._amazon_patterns = [p.upper() for p in payees_config.amazon_patterns]
        # Delegate to AmazonOrderMatcher for actual matching logic
        self._amazon_matcher = AmazonOrderMatcher(db)

    def _cached_to_order(self, cached: AmazonOrderCache) -> AmazonOrder:
        """Convert database cache model to domain model.

        Args:
            cached: AmazonOrderCache from database.

        Returns:
            AmazonOrder domain model.
        """
        return AmazonOrder(
            order_id=cached.order_id,
            order_date=cached.order_date,
            total=cached.total,
            items=[OrderItem(name=name) for name in cached.items],
            from_cache=True,
            fetched_at=cached.fetched_at,
        )

    def _transaction_to_info(self, txn: Transaction) -> TransactionInfo:
        """Convert domain Transaction to TransactionInfo for matching.

        Args:
            txn: Transaction domain model.

        Returns:
            TransactionInfo for use with AmazonOrderMatcher.
        """
        amount = abs(txn.amount)
        return TransactionInfo(
            transaction_id=txn.id,
            amount=amount,
            date=txn.date,
            date_str=txn.date.strftime("%Y-%m-%d"),
            display_amount=f"-${amount:,.2f}" if txn.amount < 0 else f"${amount:,.2f}",
            is_split=txn.is_split,
            category_id=txn.category_id,
            category_name=txn.category_name,
            approved=txn.approved,
        )

    def is_amazon_transaction(self, transaction: Transaction) -> bool:
        """Check if a transaction is from Amazon.

        Args:
            transaction: Transaction to check.

        Returns:
            True if payee matches an Amazon pattern.
        """
        return is_amazon_payee(transaction.payee_name, self._amazon_patterns)

    def enrich_transaction(self, transaction: Transaction) -> Transaction:
        """Enrich a transaction with Amazon order data if applicable.

        Args:
            transaction: Transaction to enrich.

        Returns:
            Transaction with Amazon data populated if matched.
        """
        # Mark if this is an Amazon transaction
        transaction.is_amazon = self.is_amazon_transaction(transaction)

        if not transaction.is_amazon:
            return transaction

        # Try to find matching Amazon order
        match = self.find_order_match(transaction)

        if match:
            transaction.amazon_order_id = match.order.order_id
            transaction.amazon_items = match.order.item_names

        return transaction

    def enrich_transactions(self, transactions: list[Transaction]) -> list[Transaction]:
        """Enrich multiple transactions with Amazon order data.

        Uses batch matching via AmazonOrderMatcher for efficiency.
        Handles both regular matches and combo matches (multiple transactions
        summing to one order).

        Important: Queries ALL Amazon transactions from DB (including approved)
        to ensure proper duplicate detection. An order matched to an approved
        transaction won't be matched again to a new unapproved transaction.

        Args:
            transactions: List of transactions to enrich.

        Returns:
            List of enriched transactions.
        """
        if not transactions:
            return transactions

        # Mark Amazon status and collect Amazon transactions to enrich
        amazon_txns_to_enrich = []
        for t in transactions:
            t.is_amazon = self.is_amazon_transaction(t)
            if t.is_amazon:
                amazon_txns_to_enrich.append(t)

        if not amazon_txns_to_enrich:
            return transactions

        try:
            # Query ALL Amazon transactions from DB (including approved)
            # This ensures orders matched to approved transactions aren't re-matched
            all_amazon_rows = self._db.get_ynab_transactions(payee_filter="amazon")
            all_amazon_txn_infos = [
                self._db_row_to_txn_info(row)
                for row in all_amazon_rows
                if is_amazon_payee(row.get("payee_name", ""), self._amazon_patterns)
            ]

            if not all_amazon_txn_infos:
                # Fallback: just use the transactions we're enriching
                all_amazon_txn_infos = [self._transaction_to_info(t) for t in amazon_txns_to_enrich]

            # Get all orders for the date range of ALL Amazon transactions
            orders = self._amazon_matcher.get_orders_for_date_range(all_amazon_txn_infos)
            if not orders:
                return transactions

            # Batch match ALL Amazon transactions for proper duplicate detection
            result = self._amazon_matcher.match_transactions(
                all_amazon_txn_infos, orders, all_transactions=all_amazon_txn_infos
            )

            # Build lookup from all match types
            match_lookup: dict[str, AmazonOrderCache] = {
                txn_info.transaction_id: order for txn_info, order in result.all_matches
            }

            # Handle combo matches - distribute items across transactions by amount
            # Each transaction gets items that sum closest to its amount
            combo_items_lookup: dict[str, list[str]] = {}
            for order, combo_txn_infos in result.combo_matches:
                distributed = self._distribute_items_by_amount(order.order_id, combo_txn_infos)
                for txn_info in combo_txn_infos:
                    match_lookup[txn_info.transaction_id] = order
                    # Use distributed items if available and non-empty
                    txn_items = distributed.get(txn_info.transaction_id, [])
                    if txn_items:
                        combo_items_lookup[txn_info.transaction_id] = txn_items
                    # Fallback: don't set combo_items_lookup, will use order.items

            # Apply matches only to the transactions we're enriching
            for txn in amazon_txns_to_enrich:
                cached_order = match_lookup.get(txn.id)
                if cached_order:
                    txn.amazon_order_id = cached_order.order_id
                    # Use distributed items for combo matches, else all order items
                    if txn.id in combo_items_lookup:
                        txn.amazon_items = combo_items_lookup[txn.id]
                    else:
                        txn.amazon_items = cached_order.items
        except Exception as e:
            logger.debug("Failed to batch enrich transactions: %s", e)

        return transactions

    def _distribute_items_by_amount(
        self, order_id: str, combo_txn_infos: tuple
    ) -> dict[str, list[str]]:
        """Distribute order items across combo transactions by amount.

        Uses greedy bin-packing: assigns items to transactions whose
        remaining capacity best fits the item price.

        Args:
            order_id: Amazon order ID to get items from.
            combo_txn_infos: Tuple of TransactionInfo for the combo.

        Returns:
            Dict mapping transaction_id to list of item names.
        """
        # Get items with prices from database
        items_with_prices = self._db.get_amazon_order_items_with_prices(order_id)

        if not items_with_prices:
            # No price info, can't distribute intelligently
            return {}

        # Sort items by price descending (assign expensive items first)
        items_with_prices.sort(key=lambda x: x.get("item_price") or 0, reverse=True)

        # Initialize buckets for each transaction
        buckets: dict[str, dict] = {}
        for txn_info in combo_txn_infos:
            buckets[txn_info.transaction_id] = {
                "target": txn_info.amount,
                "current": 0.0,
                "items": [],
            }

        # Greedy assignment: for each item, assign to transaction with best fit
        for item in items_with_prices:
            item_name = item.get("item_name", "Unknown")
            item_price = item.get("item_price") or 0
            quantity = item.get("quantity") or 1

            # Assign each unit of the item
            for _ in range(quantity):
                # Find transaction with most remaining capacity that can fit this item
                best_txn_id = None
                best_remaining = float("inf")

                for txn_id, bucket in buckets.items():
                    remaining = bucket["target"] - bucket["current"]
                    # Prefer transactions that haven't exceeded their target
                    if remaining >= item_price and remaining < best_remaining:
                        best_txn_id = txn_id
                        best_remaining = remaining

                # If no transaction can fit without exceeding, pick one with most space
                if best_txn_id is None:
                    best_txn_id = max(
                        buckets.keys(),
                        key=lambda tid: buckets[tid]["target"] - buckets[tid]["current"],
                    )

                # Assign item to this transaction
                buckets[best_txn_id]["items"].append(item_name)
                buckets[best_txn_id]["current"] += item_price

        # Return just the item names per transaction
        return {txn_id: bucket["items"] for txn_id, bucket in buckets.items()}

    def _db_row_to_txn_info(self, row: dict) -> TransactionInfo:
        """Convert database row to TransactionInfo for matching."""
        amount = abs(row.get("amount", 0))
        date_val = row.get("date")
        if isinstance(date_val, str):
            txn_date = datetime.strptime(date_val[:10], "%Y-%m-%d")
        elif isinstance(date_val, datetime):
            txn_date = date_val
        else:
            txn_date = datetime.now()  # Fallback, should not happen

        return TransactionInfo(
            transaction_id=row.get("id", ""),
            amount=amount,
            date=txn_date,
            date_str=txn_date.strftime("%Y-%m-%d"),
            display_amount=f"-${amount:,.2f}" if row.get("amount", 0) < 0 else f"${amount:,.2f}",
            is_split=row.get("is_split", False),
            category_id=row.get("category_id"),
            category_name=row.get("category_name"),
            approved=row.get("approved", False),
        )

    def find_order_match(self, transaction: Transaction) -> Optional[OrderMatch]:
        """Find an Amazon order matching a transaction.

        Uses two-stage matching via AmazonOrderMatcher:
        - Stage 1: 7-day window with $0.10 tolerance
        - Stage 2: 24-day window for remaining unmatched

        Args:
            transaction: Transaction to match.

        Returns:
            OrderMatch if found, None otherwise.
        """
        if not self.is_amazon_transaction(transaction):
            return None

        try:
            # Convert to TransactionInfo for AmazonOrderMatcher
            txn_info = self._transaction_to_info(transaction)

            # Get orders for this transaction's date range
            orders = self._amazon_matcher.get_orders_for_date_range([txn_info])
            if not orders:
                return None

            # Use two-stage matching via AmazonOrderMatcher
            result = self._amazon_matcher.match_transactions([txn_info], orders)

            # Get the match (if any) from stage1 or stage2
            matched = result.all_matches
            if not matched:
                return None

            _, cached_order = matched[0]
            order = self._cached_to_order(cached_order)

            # Calculate match quality
            amount_diff = abs(order.total - abs(transaction.amount))
            days_diff = abs((order.order_date - transaction.date).days)

            return OrderMatch(
                transaction_id=transaction.id,
                order=order,
                amount_diff=amount_diff,
                days_diff=days_diff,
            )
        except Exception as e:
            logger.debug("Failed to match order for transaction %s: %s", transaction.id, e)

        return None

    def match_batch(
        self,
        transactions: list[Transaction],
    ) -> dict[str, OrderMatch]:
        """Match a batch of transactions to Amazon orders.

        Args:
            transactions: Transactions to match.

        Returns:
            Dict mapping transaction IDs to OrderMatches.
        """
        matches = {}

        # First, enrich all transactions
        enriched = self.enrich_transactions(transactions)

        # Find matches for Amazon transactions
        for txn in enriched:
            if txn.is_amazon and txn.amazon_order_id:
                match = self.find_order_match(txn)
                if match:
                    matches[txn.id] = match

        return matches
