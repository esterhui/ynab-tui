"""Service protocols for dependency injection.

These protocols define interfaces for service layer components,
enabling easier testing with mock implementations.
"""

from typing import Optional, Protocol

from ..db.database import AmazonOrderCache
from .amazon_matcher import AmazonMatchResult, TransactionInfo


class AmazonMatcherProtocol(Protocol):
    """Protocol for Amazon order matching service."""

    def match_transactions(
        self,
        transactions: list[TransactionInfo],
        orders: list[AmazonOrderCache],
        all_transactions: Optional[list[TransactionInfo]] = None,
    ) -> AmazonMatchResult:
        """Match transactions to orders using two-stage matching.

        Args:
            transactions: Transactions to match.
            orders: Amazon orders to match against.
            all_transactions: All Amazon transactions for reverse matching.

        Returns:
            AmazonMatchResult with all match types.
        """
        pass

    def get_orders_for_date_range(
        self, transactions: list[TransactionInfo]
    ) -> list[AmazonOrderCache]:
        """Get orders from repository for the date range of transactions.

        Args:
            transactions: Transactions to get date range from.

        Returns:
            Orders within extended date range of transactions.
        """
        pass

    def normalize_transaction(self, txn: dict) -> TransactionInfo:
        """Convert raw transaction dict to TransactionInfo.

        Args:
            txn: Raw transaction dictionary from database.

        Returns:
            Normalized TransactionInfo object.
        """
        pass
