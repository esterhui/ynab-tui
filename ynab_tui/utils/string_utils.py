"""String utility functions."""


def normalize_string(value: str) -> str:
    """Normalize a string for consistent matching.

    Converts to lowercase and strips whitespace.

    Args:
        value: String to normalize.

    Returns:
        Lowercase, trimmed string.
    """
    return value.lower().strip()
