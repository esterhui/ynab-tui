"""Amazon-related utilities."""


def is_amazon_payee(payee_name: str, patterns: list[str]) -> bool:
    """Check if payee name matches Amazon patterns.

    Args:
        payee_name: The payee name to check.
        patterns: List of patterns to match against.

    Returns:
        True if any pattern matches (case-insensitive).
    """
    if not payee_name:
        return False

    payee_upper = payee_name.upper()
    return any(p.upper() in payee_upper for p in patterns)
