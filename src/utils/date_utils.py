"""Date parsing utilities for consistent date handling across the codebase."""

from datetime import date, datetime
from typing import Union


def parse_date(value: Union[str, date, datetime, None]) -> date:
    """Parse a value to a date object.

    Handles:
    - ISO format strings ("2024-01-15")
    - datetime objects (extracts date)
    - date objects (returns as-is)
    - None (raises ValueError)

    Args:
        value: String, date, or datetime to parse.

    Returns:
        date object.

    Raises:
        ValueError: If value is None or cannot be parsed.
    """
    if value is None:
        raise ValueError("Cannot parse None to date")

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    if isinstance(value, str):
        # Try ISO format first, then YYYY-MM-DD
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()

    raise ValueError(f"Cannot parse {type(value)} to date")


def parse_to_datetime(value: Union[str, date, datetime, None]) -> datetime:
    """Parse a value to a datetime object.

    Handles:
    - ISO format strings ("2024-01-15" or "2024-01-15T10:30:00")
    - datetime objects (returns as-is)
    - date objects (combines with midnight time)
    - None (raises ValueError)

    Args:
        value: String, date, or datetime to parse.

    Returns:
        datetime object.

    Raises:
        ValueError: If value is None or cannot be parsed.
    """
    if value is None:
        raise ValueError("Cannot parse None to datetime")

    if isinstance(value, datetime):
        return value

    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())

    if isinstance(value, str):
        # Try ISO format first
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            # Fall back to date-only string
            parsed_date = datetime.strptime(value[:10], "%Y-%m-%d").date()
            return datetime.combine(parsed_date, datetime.min.time())

    raise ValueError(f"Cannot parse {type(value)} to datetime")
