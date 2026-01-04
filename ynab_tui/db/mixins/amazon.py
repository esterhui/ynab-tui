"""Amazon orders and items database operations."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from ..models import AmazonOrderCache
from .base import CountMixin, _date_str, _now_iso


class AmazonMixin(CountMixin):
    """Mixin for Amazon orders and items database operations."""

    def cache_amazon_order(
        self,
        order_id: str,
        order_date: datetime,
        total: float,
    ) -> tuple[bool, bool]:
        """Cache an Amazon order to avoid re-scraping.

        Note: Items are stored separately via upsert_amazon_order_items().

        Args:
            order_id: Amazon order ID.
            order_date: Order date.
            total: Order total.

        Returns:
            Tuple of (was_inserted, was_changed). was_changed is True only if
            data actually changed (not just fetched_at timestamp).
        """
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT order_id, order_date, total FROM amazon_orders_cache WHERE order_id = ?",
                (order_id,),
            ).fetchone()

            new_date = _date_str(order_date)

            if existing:
                data_changed = existing["order_date"] != new_date or existing["total"] != total

                if data_changed:
                    conn.execute(
                        """
                        UPDATE amazon_orders_cache
                        SET order_date = ?, total = ?, fetched_at = ?
                        WHERE order_id = ?
                        """,
                        (new_date, total, _now_iso(), order_id),
                    )
                return (False, data_changed)
            else:
                conn.execute(
                    """
                    INSERT INTO amazon_orders_cache
                    (order_id, order_date, total, fetched_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (order_id, new_date, total, _now_iso()),
                )
                return (True, True)

    def get_cached_orders_by_date_range(
        self, start_date: datetime, end_date: datetime
    ) -> list[AmazonOrderCache]:
        """Get cached Amazon orders within a date range.

        Args:
            start_date: Start of date range.
            end_date: End of date range.

        Returns:
            List of cached orders.
        """
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.order_id, c.order_date, c.total, c.fetched_at,
                    GROUP_CONCAT(i.item_name, '||') as items
                FROM amazon_orders_cache c
                LEFT JOIN amazon_order_items i ON c.order_id = i.order_id
                WHERE c.order_date BETWEEN ? AND ?
                GROUP BY c.order_id
                ORDER BY c.order_date DESC
                """,
                (_date_str(start_date), _date_str(end_date)),
            ).fetchall()

            return [
                AmazonOrderCache(
                    order_id=row["order_id"],
                    order_date=datetime.strptime(row["order_date"], "%Y-%m-%d")
                    if row["order_date"]
                    else datetime.min,
                    total=row["total"],
                    items=row["items"].split("||") if row["items"] else [],
                    fetched_at=datetime.fromisoformat(row["fetched_at"]),
                )
                for row in rows
            ]

    def get_cached_orders_for_year(self, year: int) -> list[AmazonOrderCache]:
        """Get cached Amazon orders for a specific year.

        Args:
            year: The year to filter by.

        Returns:
            List of cached orders for that year.
        """
        start_date = datetime(year, 1, 1)
        end_date = datetime(year, 12, 31)
        return self.get_cached_orders_by_date_range(start_date, end_date)

    def get_cached_order_by_amount(
        self,
        amount: float,
        date: datetime,
        window_days: int = 3,
        tolerance: float = 0.01,
    ) -> Optional[AmazonOrderCache]:
        """Find a cached order matching amount and date.

        Args:
            amount: Order amount to match.
            date: Transaction date.
            window_days: Days before/after to search.
            tolerance: Amount tolerance for matching (e.g., 0.01 = 1 cent).

        Returns:
            Matching cached order or None.
        """
        start = date - timedelta(days=window_days)
        end = date + timedelta(days=window_days)

        with self._connection() as conn:
            order_row = conn.execute(
                """
                SELECT order_id, order_date, total, fetched_at
                FROM amazon_orders_cache
                WHERE order_date BETWEEN ? AND ?
                  AND ABS(total - ?) <= ?
                ORDER BY ABS(total - ?) ASC, ABS(julianday(order_date) - julianday(?)) ASC
                LIMIT 1
                """,
                (_date_str(start), _date_str(end), amount, tolerance, amount, _date_str(date)),
            ).fetchone()

            if not order_row:
                return None

            item_rows = conn.execute(
                "SELECT item_name FROM amazon_order_items WHERE order_id = ?",
                (order_row["order_id"],),
            ).fetchall()
            items = [row["item_name"] for row in item_rows]

            return AmazonOrderCache(
                order_id=order_row["order_id"],
                order_date=datetime.strptime(order_row["order_date"], "%Y-%m-%d")
                if order_row["order_date"]
                else datetime.min,
                total=order_row["total"],
                items=items,
                fetched_at=datetime.fromisoformat(order_row["fetched_at"]),
            )

    def upsert_amazon_order_items(self, order_id: str, items: list[dict[str, Any]]) -> int:
        """Store Amazon order items for category matching.

        Args:
            order_id: Amazon order ID.
            items: List of item dictionaries with name, price, quantity.

        Returns:
            Number of items upserted.
        """
        with self._connection() as conn:
            conn.execute("DELETE FROM amazon_order_items WHERE order_id = ?", (order_id,))

            for item in items:
                conn.execute(
                    """
                    INSERT INTO amazon_order_items
                    (order_id, item_name, item_price, quantity)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        order_id,
                        item.get("name", "Unknown"),
                        item.get("price"),
                        item.get("quantity", 1),
                    ),
                )

            return len(items)

    def get_amazon_order_items_with_prices(self, order_id: str) -> list[dict[str, Any]]:
        """Get order items with prices for split transaction matching.

        Args:
            order_id: Amazon order ID.

        Returns:
            List of item dicts with name, price, quantity.
        """
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT item_name, item_price, quantity
                FROM amazon_order_items
                WHERE order_id = ?
                ORDER BY item_price DESC
                """,
                (order_id,),
            ).fetchall()

            return [
                {
                    "item_name": row["item_name"],
                    "item_price": row["item_price"],
                    "quantity": row["quantity"],
                }
                for row in rows
            ]

    def get_order_count(self) -> int:
        """Get total Amazon order count.

        Returns:
            Order count.
        """
        return self._count("amazon_orders_cache")

    def get_order_item_count(self) -> int:
        """Get total Amazon order item count.

        Returns:
            Item count.
        """
        return self._count("amazon_order_items")

    def get_order_date_range(self) -> tuple[Optional[str], Optional[str]]:
        """Get earliest and latest Amazon order dates.

        Returns:
            Tuple of (earliest_date, latest_date) as strings, or (None, None) if empty.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT MIN(order_date) as earliest, MAX(order_date) as latest "
                "FROM amazon_orders_cache"
            ).fetchone()
            if row and row["earliest"]:
                return (row["earliest"][:10], row["latest"][:10])
            return (None, None)
