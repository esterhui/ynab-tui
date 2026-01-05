"""Budget picker modal for switching between YNAB budgets."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .fuzzy_select import FuzzySelectModal


@dataclass
class BudgetSelection:
    """Result of budget selection."""

    budget_id: str
    budget_name: str


class BudgetPickerModal(FuzzySelectModal[BudgetSelection]):
    """fzf-style fuzzy budget picker modal.

    Opens as an overlay, type to filter, j/k to navigate, Enter to select.
    Returns BudgetSelection on success, None on cancel.
    """

    DEFAULT_CSS = """
    BudgetPickerModal {
        align: center middle;
    }

    BudgetPickerModal > #fuzzy-container {
        width: 60;
        height: auto;
        max-height: 30;
        background: $surface;
        border: thick $primary;
        padding: 1;
    }

    BudgetPickerModal > #fuzzy-container > #fuzzy-title {
        height: 1;
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }

    BudgetPickerModal > #fuzzy-container > #fuzzy-input {
        height: 3;
        margin-bottom: 1;
    }

    BudgetPickerModal > #fuzzy-container > #fuzzy-list {
        height: 1fr;
        min-height: 5;
        border: solid $primary-background;
    }

    BudgetPickerModal > #fuzzy-container > #fuzzy-footer {
        height: 1;
        text-align: center;
        color: $text-muted;
        margin-top: 1;
    }
    """

    def __init__(
        self,
        budgets: list[dict],
        current_budget_id: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Initialize the budget picker modal.

        Args:
            budgets: List of budget dicts with id, name, last_modified_on.
            current_budget_id: ID of currently selected budget (for highlighting).
        """
        self._current_budget_id = current_budget_id

        super().__init__(
            items=budgets,
            display_fn=self._format_budget,
            search_fn=self._search_text,
            result_fn=self._make_result,
            title="Switch Budget",
            placeholder="Type to filter...",
            show_all_on_empty=True,
            debounce_delay=0,
            **kwargs,
        )

    def _format_budget(self, budget: dict) -> str:
        """Format budget for display with last modified date."""
        name = budget["name"]
        last_modified = budget.get("last_modified_on")

        # Format last modified date
        if last_modified:
            if isinstance(last_modified, datetime):
                date_str = last_modified.strftime("%Y-%m-%d")
            else:
                date_str = str(last_modified)[:10]
            display = f"{name} [dim]({date_str})[/dim]"
        else:
            display = name

        # Mark current budget
        if self._current_budget_id and budget["id"] == self._current_budget_id:
            return f"{display} [dim]← current[/dim]"
        return display

    @staticmethod
    def _search_text(budget: dict) -> str:
        """Extract searchable text from budget."""
        return budget["name"]

    @staticmethod
    def _make_result(budget: dict) -> BudgetSelection:
        """Create result from selected budget."""
        return BudgetSelection(
            budget_id=budget["id"],
            budget_name=budget["name"],
        )
