"""Fuzzy matching utilities.

Provides multiple matching styles for search functionality:
- substring: Simple substring matching (default, most intuitive)
- fuzzy: fzf-style matching where characters must appear in order
- word_boundary: Fuzzy matching that prioritizes word starts
"""

from typing import Callable, Literal

MatchStyle = Literal["substring", "fuzzy", "word_boundary"]


def substring_match(query: str, text: str) -> bool:
    """Simple substring matching.

    Args:
        query: Substring to search for.
        text: Text to search in.

    Returns:
        True if query appears as a substring in text.
    """
    return query in text


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


def word_boundary_match(query: str, text: str) -> bool:
    """Word-boundary fuzzy match: prioritizes matching at word starts.

    Matches if query characters appear in order, with bonus for word boundaries.
    A match is valid if each query character matches either:
    - At a word boundary (start of word, after space/punctuation)
    - After the previous matched character

    Args:
        query: Characters to search for.
        text: Text to search in.

    Returns:
        True if query matches with word boundary preference.
    """
    if not query:
        return True
    if not text:
        return False

    # First try: match at word boundaries only
    query_idx = 0
    prev_was_boundary = True  # Start of string is a boundary

    for char in text:
        is_boundary = prev_was_boundary
        if query_idx < len(query) and char == query[query_idx] and is_boundary:
            query_idx += 1

        # Next char is a boundary if this char is a separator
        prev_was_boundary = not char.isalnum()

    if query_idx == len(query):
        return True

    # Fall back to regular fuzzy match if word boundary match fails
    return fuzzy_match(query, text)


def get_match_fn(style: MatchStyle) -> Callable[[str, str], bool]:
    """Get the matching function for the given style.

    Args:
        style: One of "substring", "fuzzy", or "word_boundary".

    Returns:
        The matching function for the given style.
    """
    match_fns: dict[MatchStyle, Callable[[str, str], bool]] = {
        "substring": substring_match,
        "fuzzy": fuzzy_match,
        "word_boundary": word_boundary_match,
    }
    return match_fns.get(style, substring_match)
