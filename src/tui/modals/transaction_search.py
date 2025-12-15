"""Transaction search modal using FuzzySelectModal base."""

from src.models.transaction import Transaction

from .fuzzy_select import FuzzySelectModal


class TransactionSearchModal(FuzzySelectModal[str]):
    """Fuzzy search modal for finding transactions by payee.

    Shows transactions with date, payee, and amount.
    Returns transaction ID on success, None on cancel.
    """

    def __init__(self, transactions: list[Transaction], **kwargs) -> None:
        """Initialize the transaction search modal.

        Args:
            transactions: List of transactions to search through.
        """
        super().__init__(
            items=transactions,
            display_fn=self._format_transaction,
            search_fn=lambda t: t.payee_name or "",
            result_fn=lambda t: t.id,
            placeholder="Search transactions by payee...",
            title="Search Transactions",
            **kwargs,
        )

    @staticmethod
    def _format_transaction(txn: Transaction) -> str:
        """Format transaction for display: date | payee | amount."""
        date_str = txn.display_date
        payee = (txn.payee_name or "")[:22].ljust(22)
        amount = txn.display_amount.rjust(12)
        return f"{date_str}  {payee}  {amount}"
