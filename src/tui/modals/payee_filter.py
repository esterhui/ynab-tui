"""Payee filter modal using FuzzySelectModal base."""

from .fuzzy_select import FuzzySelectModal


class PayeeFilterModal(FuzzySelectModal[str]):
    """Fuzzy search modal for filtering transactions by payee.

    Shows unique payees from the provided transaction list.
    Returns the selected payee name, or None on cancel.
    """

    def __init__(self, payees: list[str], **kwargs) -> None:
        """Initialize the payee filter modal.

        Args:
            payees: List of unique payee names to search through.
        """
        # Sort payees alphabetically for better UX
        sorted_payees = sorted(payees, key=str.lower)

        super().__init__(
            items=sorted_payees,
            display_fn=lambda p: p,  # Display payee name as-is
            search_fn=lambda p: p,  # Search on payee name
            result_fn=lambda p: p,  # Return payee name
            placeholder="Filter by payee...",
            title="Select Payee Filter",
            **kwargs,
        )


def get_unique_payees(transactions: list) -> list[str]:
    """Extract unique payee names from a list of transactions.

    Args:
        transactions: List of Transaction objects.

    Returns:
        List of unique payee names (excluding None/empty).
    """
    payees = set()
    for txn in transactions:
        if txn.payee_name:
            payees.add(txn.payee_name)
    return list(payees)
