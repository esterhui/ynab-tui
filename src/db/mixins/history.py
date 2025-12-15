"""Categorization history and item learning database operations."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any, Optional

from src.utils.string_utils import normalize_string

from ..models import CategorizationRecord
from .base import CountMixin


class HistoryMixin(CountMixin):
    """Mixin for categorization history and item learning operations."""

    @staticmethod
    def normalize_payee(payee: str) -> str:
        """Normalize payee name for consistent matching."""
        return normalize_string(payee)

    @staticmethod
    def normalize_item(item_name: str) -> str:
        """Normalize item name for consistent matching."""
        return normalize_string(item_name)

    def add_categorization(
        self,
        payee_name: str,
        category_name: str,
        category_id: str,
        amount: Optional[float] = None,
        amazon_items: Optional[list[str]] = None,
    ) -> int:
        """Record a categorization decision for learning.

        Args:
            payee_name: Original payee name from YNAB.
            category_name: Chosen category name.
            category_id: YNAB category ID.
            amount: Transaction amount (optional).
            amazon_items: List of Amazon item names if applicable.

        Returns:
            ID of the inserted record.
        """
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO categorization_history
                (payee_name, payee_normalized, amount, category_name, category_id, amazon_items)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    payee_name,
                    self.normalize_payee(payee_name),
                    amount,
                    category_name,
                    category_id,
                    json.dumps(amazon_items) if amazon_items else None,
                ),
            )
            return cursor.lastrowid or 0

    def get_payee_history(self, payee_name: str, limit: int = 100) -> list[CategorizationRecord]:
        """Get categorization history for a payee.

        Args:
            payee_name: Payee name to look up.
            limit: Maximum records to return.

        Returns:
            List of past categorizations for this payee.
        """
        normalized = self.normalize_payee(payee_name)
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT id, payee_name, payee_normalized, amount,
                       category_name, category_id, amazon_items, created_at
                FROM categorization_history
                WHERE payee_normalized = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (normalized, limit),
            ).fetchall()

            return [
                CategorizationRecord(
                    id=row["id"],
                    payee_name=row["payee_name"],
                    payee_normalized=row["payee_normalized"],
                    amount=row["amount"],
                    category_name=row["category_name"],
                    category_id=row["category_id"],
                    amazon_items=json.loads(row["amazon_items"]) if row["amazon_items"] else None,
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
                for row in rows
            ]

    def get_payee_category_distribution(
        self, payee_name: str
    ) -> dict[str, dict[str, float | int | str]]:
        """Get category distribution for a payee.

        Args:
            payee_name: Payee name to analyze.

        Returns:
            Dict mapping category_name to stats:
            {
                "Groceries": {"count": 10, "percentage": 0.85, "avg_amount": 95.50, "category_id": "..."},
            }
        """
        normalized = self.normalize_payee(payee_name)
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT category_name, category_id,
                       COUNT(*) as count,
                       AVG(amount) as avg_amount
                FROM categorization_history
                WHERE payee_normalized = ?
                GROUP BY category_name, category_id
                ORDER BY count DESC
                """,
                (normalized,),
            ).fetchall()

            if not rows:
                return {}

            total = sum(row["count"] for row in rows)
            return {
                row["category_name"]: {
                    "count": row["count"],
                    "percentage": row["count"] / total,
                    "avg_amount": row["avg_amount"],
                    "category_id": row["category_id"],
                }
                for row in rows
            }

    def get_payee_category_distributions_batch(
        self, payee_names: list[str]
    ) -> dict[str, dict[str, dict[str, float | int | str]]]:
        """Get category distributions for multiple payees in one query.

        Args:
            payee_names: List of payee names to analyze.

        Returns:
            Dict mapping payee_name to category distribution.
        """
        if not payee_names:
            return {}

        normalized_map = {self.normalize_payee(p): p for p in payee_names}
        normalized_names = list(normalized_map.keys())

        with self._connection() as conn:
            placeholders = ",".join("?" * len(normalized_names))
            rows = conn.execute(
                f"""
                SELECT payee_normalized, category_name, category_id,
                       COUNT(*) as count,
                       AVG(amount) as avg_amount
                FROM categorization_history
                WHERE payee_normalized IN ({placeholders})
                GROUP BY payee_normalized, category_name, category_id
                ORDER BY payee_normalized, count DESC
                """,
                normalized_names,
            ).fetchall()

            if not rows:
                return {}

            result: dict[str, dict[str, dict[str, float | int | str]]] = {}
            payee_totals: dict[str, int] = {}

            for row in rows:
                payee_norm = row["payee_normalized"]
                payee_totals[payee_norm] = payee_totals.get(payee_norm, 0) + row["count"]

            for row in rows:
                payee_norm = row["payee_normalized"]
                original_payee = normalized_map.get(payee_norm, payee_norm)

                if original_payee not in result:
                    result[original_payee] = {}

                total = payee_totals[payee_norm]
                result[original_payee][row["category_name"]] = {
                    "count": row["count"],
                    "percentage": row["count"] / total,
                    "avg_amount": row["avg_amount"],
                    "category_id": row["category_id"],
                }

            return result

    # =========================================================================
    # Amazon Item Category History Methods
    # =========================================================================

    def record_item_category_learning(
        self,
        item_name: str,
        category_id: str,
        category_name: str,
        source_transaction_id: str | None = None,
        source_order_id: str | None = None,
    ) -> bool:
        """Record a learned item→category mapping.

        Args:
            item_name: The Amazon item name.
            category_id: YNAB category ID.
            category_name: YNAB category name.
            source_transaction_id: YNAB transaction that taught us this mapping.
            source_order_id: Amazon order ID the item came from.

        Returns:
            True if a new mapping was recorded, False if it already existed.
        """
        item_name_normalized = self.normalize_item(item_name)

        with self._connection() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO amazon_item_category_history
                    (item_name, item_name_normalized, category_id, category_name,
                     source_transaction_id, source_order_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item_name,
                        item_name_normalized,
                        category_id,
                        category_name,
                        source_transaction_id,
                        source_order_id,
                    ),
                )
                return True
            except sqlite3.IntegrityError:
                # UNIQUE constraint violation - mapping already exists
                return False

    def get_item_category_distribution(self, item_name: str) -> dict[str, dict[str, Any]]:
        """Get category distribution for an item.

        Shows how often an item has been categorized into different categories.

        Args:
            item_name: The item name to look up.

        Returns:
            Dict mapping category_id to {name, count, percentage}.
        """
        item_name_normalized = self.normalize_item(item_name)

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT category_id, category_name, COUNT(*) as count
                FROM amazon_item_category_history
                WHERE item_name_normalized = ?
                GROUP BY category_id, category_name
                ORDER BY count DESC
                """,
                (item_name_normalized,),
            ).fetchall()

            if not rows:
                return {}

            total = sum(row["count"] for row in rows)
            return {
                row["category_id"]: {
                    "name": row["category_name"],
                    "count": row["count"],
                    "percentage": row["count"] / total if total > 0 else 0,
                }
                for row in rows
            }

    def get_all_item_category_mappings(
        self, search_term: str | None = None, category_filter: str | None = None
    ) -> list[dict[str, Any]]:
        """Get all learned item→category mappings with statistics.

        Args:
            search_term: Optional search term to filter item names.
            category_filter: Optional category name filter.

        Returns:
            List of dicts with item_name, categories (list of {name, count, percentage}).
        """
        with self._connection() as conn:
            params: list[str] = []
            where_clauses: list[str] = []

            if search_term:
                where_clauses.append("item_name_normalized LIKE ?")
                params.append(f"%{self.normalize_item(search_term)}%")

            if category_filter:
                where_clauses.append("category_name LIKE ?")
                params.append(f"%{category_filter}%")

            where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

            rows = conn.execute(
                f"""
                SELECT DISTINCT item_name_normalized, item_name
                FROM amazon_item_category_history
                {where_sql}
                ORDER BY item_name_normalized
                """,
                params,
            ).fetchall()

            results = []
            for row in rows:
                normalized_name = row["item_name_normalized"]
                display_name = row["item_name"]

                category_rows = conn.execute(
                    """
                    SELECT category_id, category_name, COUNT(*) as count
                    FROM amazon_item_category_history
                    WHERE item_name_normalized = ?
                    GROUP BY category_id, category_name
                    ORDER BY count DESC
                    """,
                    (normalized_name,),
                ).fetchall()

                total = sum(cr["count"] for cr in category_rows)
                categories = [
                    {
                        "id": cr["category_id"],
                        "name": cr["category_name"],
                        "count": cr["count"],
                        "percentage": cr["count"] / total if total > 0 else 0,
                    }
                    for cr in category_rows
                ]

                results.append(
                    {
                        "item_name": display_name,
                        "item_name_normalized": normalized_name,
                        "total_count": total,
                        "categories": categories,
                    }
                )

            return results

    def get_item_category_history_count(self) -> int:
        """Get count of learned item→category mappings.

        Returns:
            Count of entries in amazon_item_category_history.
        """
        return self._count("amazon_item_category_history")

    def get_unique_item_count(self) -> int:
        """Get count of unique items with learned categories.

        Returns:
            Count of unique item names in history.
        """
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(DISTINCT item_name_normalized) as count
                FROM amazon_item_category_history
                """
            ).fetchone()
            return row["count"] if row else 0
