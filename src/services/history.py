"""Historical pattern analysis service.

Provides methods for analyzing and learning from past categorization decisions.
"""

from dataclasses import dataclass
from typing import Optional

from ..db.database import CategorizationRecord, Database


@dataclass
class PayeePattern:
    """Summarized categorization patterns for a payee."""

    payee_name: str
    total_transactions: int
    categories: dict[str, dict]  # category_name -> {count, percentage, avg_amount, category_id}
    dominant_category: Optional[str]
    dominant_percentage: float
    is_consistent: bool  # True if >80% goes to one category


class HistoryService:
    """Service for historical pattern analysis."""

    def __init__(self, db: Database):
        """Initialize history service.

        Args:
            db: Database instance.
        """
        self._db = db

    def get_payee_pattern(self, payee_name: str) -> Optional[PayeePattern]:
        """Get categorization patterns for a payee.

        Args:
            payee_name: Payee name to analyze.

        Returns:
            PayeePattern or None if no history.
        """
        distribution = self._db.get_payee_category_distribution(payee_name)
        if not distribution:
            return None

        total = sum(stats["count"] for stats in distribution.values())

        # Find dominant category
        dominant = max(distribution.items(), key=lambda x: x[1]["count"])
        dominant_category = dominant[0]
        dominant_pct = dominant[1]["percentage"]

        return PayeePattern(
            payee_name=payee_name,
            total_transactions=total,
            categories=distribution,
            dominant_category=dominant_category,
            dominant_percentage=dominant_pct,
            is_consistent=dominant_pct >= 0.80,
        )

    def get_recent_categorizations(
        self,
        payee_name: str,
        limit: int = 10,
    ) -> list[CategorizationRecord]:
        """Get recent categorization records for a payee.

        Args:
            payee_name: Payee to look up.
            limit: Maximum records to return.

        Returns:
            List of recent categorization records.
        """
        return self._db.get_payee_history(payee_name, limit=limit)

    def format_history_for_prompt(self, payee_name: str) -> str:
        """Format payee history for AI prompt context.

        Args:
            payee_name: Payee to format history for.

        Returns:
            Formatted history string for prompt.
        """
        pattern = self.get_payee_pattern(payee_name)
        if not pattern:
            return "No historical data available for this payee."

        header = f"Historical patterns for '{payee_name}' ({pattern.total_transactions} txns):"
        lines = [header]

        for cat_name, stats in sorted(
            pattern.categories.items(),
            key=lambda x: x[1]["count"],
            reverse=True,
        ):
            pct = stats["percentage"] * 100
            count = stats["count"]
            avg = stats.get("avg_amount")

            if avg:
                lines.append(f"  - {cat_name}: {pct:.0f}% ({count} txns, avg ${abs(avg):.2f})")
            else:
                lines.append(f"  - {cat_name}: {pct:.0f}% ({count} transactions)")

        if pattern.is_consistent:
            pct = pattern.dominant_percentage * 100
            lines.append(f"  → Strong pattern: {pct:.0f}% to {pattern.dominant_category}")

        return "\n".join(lines)

    def record_categorization(
        self,
        payee_name: str,
        category_name: str,
        category_id: str,
        amount: Optional[float] = None,
        amazon_items: Optional[list[str]] = None,
    ) -> int:
        """Record a new categorization decision.

        Args:
            payee_name: Transaction payee.
            category_name: Chosen category.
            category_id: YNAB category ID.
            amount: Transaction amount.
            amazon_items: Amazon item names if applicable.

        Returns:
            ID of inserted record.
        """
        return self._db.add_categorization(
            payee_name=payee_name,
            category_name=category_name,
            category_id=category_id,
            amount=amount,
            amazon_items=amazon_items,
        )
