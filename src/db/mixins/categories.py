"""YNAB category database operations."""

from __future__ import annotations

from typing import Any, Optional

from .base import DatabaseMixin, _now_iso


class CategoryMixin(DatabaseMixin):
    """Mixin for YNAB category database operations."""

    def upsert_category(
        self,
        category_id: str,
        name: str,
        group_id: str,
        group_name: str,
        hidden: bool = False,
        deleted: bool = False,
        budget_id: Optional[str] = None,
    ) -> tuple[bool, bool]:
        """Insert or update a YNAB category.

        Args:
            category_id: YNAB category ID.
            name: Category name.
            group_id: Category group ID.
            group_name: Category group name.
            hidden: Whether category is hidden.
            deleted: Whether category is deleted.
            budget_id: Budget ID. If None, uses self.budget_id.

        Returns:
            Tuple of (was_inserted, was_changed).
        """
        budget_id = budget_id or getattr(self, "budget_id", None)

        with self._connection() as conn:
            existing = conn.execute(
                """SELECT id, name, group_id, group_name, hidden, deleted
                   FROM ynab_categories WHERE id = ?""",
                (category_id,),
            ).fetchone()

            if existing:
                data_changed = (
                    existing["name"] != name
                    or existing["group_id"] != group_id
                    or existing["group_name"] != group_name
                    or existing["hidden"] != hidden
                    or existing["deleted"] != deleted
                )

                if data_changed:
                    conn.execute(
                        """
                        UPDATE ynab_categories SET
                            name = ?, group_id = ?, group_name = ?,
                            hidden = ?, deleted = ?, synced_at = ?,
                            budget_id = COALESCE(?, budget_id)
                        WHERE id = ?
                        """,
                        (
                            name,
                            group_id,
                            group_name,
                            hidden,
                            deleted,
                            _now_iso(),
                            budget_id,
                            category_id,
                        ),
                    )
                return (False, data_changed)
            else:
                conn.execute(
                    """
                    INSERT INTO ynab_categories
                    (id, budget_id, name, group_id, group_name, hidden, deleted, synced_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        category_id,
                        budget_id,
                        name,
                        group_id,
                        group_name,
                        hidden,
                        deleted,
                        _now_iso(),
                    ),
                )
                return (True, True)

    def upsert_categories(self, category_list: Any) -> tuple[int, int]:
        """Batch upsert YNAB categories from CategoryList.

        Args:
            category_list: CategoryList object with groups and categories.

        Returns:
            Tuple of (inserted_count, updated_count).
        """
        inserted = 0
        updated = 0

        for group in category_list.groups:
            for cat in group.categories:
                was_inserted, was_changed = self.upsert_category(
                    category_id=cat.id,
                    name=cat.name,
                    group_id=group.id,
                    group_name=group.name,
                    hidden=cat.hidden,
                    deleted=cat.deleted,
                )
                if was_inserted:
                    inserted += 1
                elif was_changed:
                    updated += 1

        return inserted, updated

    def get_categories(self, include_hidden: bool = False) -> list[dict[str, Any]]:
        """Get all categories grouped by category group.

        Args:
            include_hidden: Include hidden categories.

        Returns:
            List of group dictionaries with nested categories.
        """
        conditions: list[str] = []
        params: list[str] = []

        if not include_hidden:
            conditions.append("hidden = 0 AND deleted = 0")

        # Filter by budget_id if set
        budget_id = getattr(self, "budget_id", None)
        if budget_id:
            conditions.append("budget_id = ?")
            params.append(budget_id)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT id, name, group_id, group_name, hidden, deleted, budget_id
                FROM ynab_categories
                WHERE {where_clause}
                ORDER BY group_name, name
                """,
                params,
            ).fetchall()

            groups: dict[str, dict[str, Any]] = {}
            for row in rows:
                group_id = row["group_id"]
                if group_id not in groups:
                    groups[group_id] = {
                        "id": group_id,
                        "name": row["group_name"],
                        "categories": [],
                    }
                groups[group_id]["categories"].append(
                    {
                        "id": row["id"],
                        "name": row["name"],
                        "group_id": row["group_id"],
                        "group_name": row["group_name"],
                        "hidden": bool(row["hidden"]),
                        "deleted": bool(row["deleted"]),
                        "budget_id": row["budget_id"],
                    }
                )

            return list(groups.values())

    def get_category_by_id(self, category_id: str) -> Optional[dict[str, Any]]:
        """Get a category by ID.

        Args:
            category_id: YNAB category ID.

        Returns:
            Category dictionary or None.
        """
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT id, name, group_id, group_name, hidden, deleted
                FROM ynab_categories
                WHERE id = ?
                """,
                (category_id,),
            ).fetchone()

            return dict(row) if row else None

    def get_category_by_name(self, name: str) -> Optional[dict[str, Any]]:
        """Get a category by name (case-insensitive).

        Args:
            name: Category name to find.

        Returns:
            Category dictionary or None.
        """
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT id, name, group_id, group_name, hidden, deleted
                FROM ynab_categories
                WHERE LOWER(name) = LOWER(?)
                """,
                (name,),
            ).fetchone()

            return dict(row) if row else None

    def get_category_count(self, include_hidden: bool = False) -> int:
        """Get total category count.

        Args:
            include_hidden: Include hidden categories.

        Returns:
            Category count.
        """
        conditions = []
        if not include_hidden:
            conditions.append("hidden = 0 AND deleted = 0")

        # Filter by budget_id if set
        budget_id = getattr(self, "budget_id", None)
        if budget_id:
            conditions.append(f"budget_id = '{budget_id}'")

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

        with self._connection() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) as count FROM ynab_categories{where_clause}"
            ).fetchone()
            return row["count"] if row else 0
