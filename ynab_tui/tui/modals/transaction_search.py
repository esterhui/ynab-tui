"""Transaction search modal using FuzzySelectModal base."""

from ynab_tui.models.transaction import Transaction

from ..layout import ColumnWidths
from .fuzzy_select import FuzzySelectModal

# Default widths for search modal (slightly reduced for modal width)
_WIDTHS = ColumnWidths(payee=24, category=0, account=0)


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
        w = _WIDTHS
        date_str = txn.display_date[: w.date].ljust(w.date)
        payee = (txn.payee_name or "")[: w.payee].ljust(w.payee)
        amount = txn.display_amount.rjust(w.amount)
        return f"{date_str}  {payee}  {amount}"
