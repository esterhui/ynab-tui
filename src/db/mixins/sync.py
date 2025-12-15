"""Sync state database operations."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from .base import _date_str, _now_iso


class SyncMixin:
    """Mixin for sync state database operations."""

    def _get_sync_key(self, base_key: str) -> str:
        """Get budget-specific sync key.

        Args:
            base_key: Base key (e.g., 'ynab', 'amazon', 'categories').

        Returns:
            Budget-specific key like 'ynab:budget_id' or just 'ynab' if no budget.
        """
        budget_id = getattr(self, "budget_id", None)
        if budget_id:
            return f"{base_key}:{budget_id}"
        return base_key

    def get_sync_state(self, key: str) -> Optional[dict]:
        """Get sync state for a given key.

        Args:
            key: Sync key (e.g., 'ynab', 'amazon'). Will be made budget-specific if budget_id is set.

        Returns:
            Sync state dictionary or None.
        """
        actual_key = self._get_sync_key(key)

        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT key, last_sync_date, last_sync_at, record_count
                FROM sync_state
                WHERE key = ?
                """,
                (actual_key,),
            ).fetchone()

            if not row:
                return None

            return {
                "key": row["key"],
                "last_sync_date": datetime.strptime(row["last_sync_date"], "%Y-%m-%d")
                if row["last_sync_date"]
                else None,
                "last_sync_at": datetime.fromisoformat(row["last_sync_at"])
                if row["last_sync_at"]
                else None,
                "record_count": row["record_count"],
            }

    def update_sync_state(self, key: str, last_sync_date: datetime, record_count: int) -> None:
        """Update sync state for a given key.

        Args:
            key: Sync key (e.g., 'ynab', 'amazon'). Will be made budget-specific if budget_id is set.
            last_sync_date: Date of last synced record.
            record_count: Total record count.
        """
        actual_key = self._get_sync_key(key)

        with self._connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sync_state
                (key, last_sync_date, last_sync_at, record_count)
                VALUES (?, ?, ?, ?)
                """,
                (actual_key, _date_str(last_sync_date), _now_iso(), record_count),
            )
