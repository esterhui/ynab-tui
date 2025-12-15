"""Fuzzy matching utilities."""


def fuzzy_match(query: str, text: str) -> bool:
    """Fuzzy match: all query chars must appear in text in order (fzf-style).

    Args:
        query: Characters to search for.
        text: Text to search in.

    Returns:
        True if all query chars appear in text in order.
    """
    query_idx = 0
    for char in text:
        if query_idx < len(query) and char == query[query_idx]:
            query_idx += 1
    return query_idx == len(query)
