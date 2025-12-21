"""Type definitions for matching algorithms.

These are defined separately to avoid circular imports between
amazon_matcher.py and algorithms.py.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    pass


@dataclass
class TransactionInfo:
    """Normalized transaction info for matching."""

    transaction_id: str
    amount: float  # Absolute value
    date: datetime
    date_str: str
    display_amount: str
    is_split: bool = False
    category_id: Optional[str] = None
    category_name: Optional[str] = None
    approved: bool = False
    raw_data: dict = field(default_factory=dict)  # Original transaction dict


@dataclass
class AmazonMatchResult:
    """Results from Amazon order matching."""

    stage1_matches: list  # list[tuple[TransactionInfo, AmazonOrderCache]]
    stage2_matches: list  # list[tuple[TransactionInfo, AmazonOrderCache]]
    duplicate_matches: list  # list[tuple[TransactionInfo, AmazonOrderCache]]
    combo_matches: list  # list[tuple[AmazonOrderCache, tuple[TransactionInfo, ...]]]
    unmatched_transactions: list  # list[TransactionInfo]
    unmatched_orders: list  # list[AmazonOrderCache]

    @property
    def all_matches(self) -> list:
        """All matched transactions (stage1 + stage2)."""
        return self.stage1_matches + self.stage2_matches

    @property
    def total_matched(self) -> int:
        """Total number of matched transactions."""
        return len(self.stage1_matches) + len(self.stage2_matches)
