"""Base mixin providing database connection interface.

All mixins inherit from this to access _connection() context manager.
"""

from contextlib import contextmanager
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    import sqlite3


def _now_iso() -> str:
    """Return current datetime as ISO format string."""
    return datetime.now().isoformat()


def _date_str(dt: date | datetime) -> str:
    """Convert date/datetime to YYYY-MM-DD string."""
    return dt.strftime("%Y-%m-%d")


class DatabaseMixin:
    """Base mixin for all database mixins.

    This declares the expected interface that the concrete Database class must provide.
    The _connection method is defined here with a stub to satisfy type checking.
    """

    @contextmanager
    def _connection(self) -> Iterator["sqlite3.Connection"]:
        """Context manager for database connections.

        This is a stub that should be overridden by the concrete Database class.
        """
        raise NotImplementedError("Must be provided by concrete Database class")
        yield  # Makes this a generator


class CountMixin(DatabaseMixin):
    """Mixin providing generic count helper for database tables."""

    def _count(self, table: str, where: str = "", params: tuple[Any, ...] = ()) -> int:
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
            return int(row["count"]) if row else 0
