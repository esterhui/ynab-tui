"""Display formatting utilities for consistent UI presentation."""

from typing import Sequence


def truncate_list_display(
    items: Sequence[str],
    max_items: int = 3,
    separator: str = ", ",
) -> str:
    """Format a list of items for display, truncating if needed.

    Shows the first `max_items` items joined by separator. If there are more
    items, appends "(+N more)" to indicate the count of hidden items.

    Args:
        items: Sequence of string items to display.
        max_items: Maximum number of items to show before truncating.
        separator: String to join visible items.

    Returns:
        Formatted string like "item1, item2, item3 (+5 more)" or "(no items)"

    Examples:
        >>> truncate_list_display(["a", "b", "c", "d", "e"])
        'a, b, c (+2 more)'
        >>> truncate_list_display(["a", "b"])
        'a, b'
        >>> truncate_list_display([])
        '(no items)'
    """
    if not items:
        return "(no items)"

    visible = list(items[:max_items])
    result = separator.join(visible)

    remaining = len(items) - max_items
    if remaining > 0:
        result += f" (+{remaining} more)"

    return result
