"""Base mixin providing database connection interface.

All mixins inherit from this to access _connection() context manager.
"""

from contextlib import contextmanager
from datetime import date, datetime
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import sqlite3


def _now_iso() -> str:
    """Return current datetime as ISO format string."""
    return datetime.now().isoformat()


def _date_str(dt: date | datetime) -> str:
    """Convert date/datetime to YYYY-MM-DD string."""
    return dt.strftime("%Y-%m-%d")


class DatabaseConnectionProtocol(Protocol):
    """Protocol for database connection access."""

    @contextmanager
    def _connection(self) -> "sqlite3.Connection":
        """Context manager for database connections."""
        ...


class CountMixin:
    """Mixin providing generic count helper for database tables."""

    def _count(self, table: str, where: str = "", params: tuple = ()) -> int:
        """Count rows in a table with optional WHERE clause.

        Args:
            table: Table name to count from.
            where: Optional WHERE clause (without 'WHERE' keyword).
            params: Parameters for the WHERE clause.

        Returns:
            Number of matching rows.
        """
        query = f"SELECT COUNT(*) as count FROM {table}"
        if where:
            query += f" WHERE {where}"
        with self._connection() as conn:
            row = conn.execute(query, params).fetchone()
            return row["count"] if row else 0
