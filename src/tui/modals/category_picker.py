"""Category picker modal using FuzzySelectModal base."""

from dataclasses import dataclass
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, ListView, Static

from .fuzzy_select import FuzzySelectModal


@dataclass
class CategorySelection:
    """Result of category selection."""

    category_id: str
    category_name: str


@dataclass
class TransactionSummary:
    """Summary of transaction being categorized."""

    date: str
    payee: str
    amount: str
    current_category: Optional[str] = None
    current_category_id: Optional[str] = None
    amazon_items: Optional[list[str]] = None


class CategoryPickerModal(FuzzySelectModal[CategorySelection]):
    """fzf-style fuzzy category picker modal.

    Opens as an overlay, type to filter, arrow keys to navigate, Enter to select.
    Returns CategorySelection on success, None on cancel.
    """

    DEFAULT_CSS = """
    CategoryPickerModal {
        align: center middle;
    }

    CategoryPickerModal > #fuzzy-container {
        width: 70;
        height: 80%;
        max-height: 45;
        background: $surface;
        border: thick $primary;
        padding: 1;
    }

    CategoryPickerModal > #fuzzy-container > #txn-summary {
        height: auto;
        padding: 0 1 1 1;
        border-bottom: solid $primary-background;
        margin-bottom: 1;
    }

    CategoryPickerModal > #fuzzy-container > #txn-summary .summary-line {
        height: 1;
    }

    CategoryPickerModal > #fuzzy-container > #txn-summary .amazon-items {
        color: $warning;
        height: auto;
        padding-left: 2;
    }

    CategoryPickerModal > #fuzzy-container > #fuzzy-input {
        height: 3;
        margin-bottom: 1;
    }

    CategoryPickerModal > #fuzzy-container > #fuzzy-list {
        height: 1fr;
        border: solid $primary-background;
    }

    CategoryPickerModal > #fuzzy-container > #fuzzy-footer {
        height: 1;
        text-align: center;
        color: $text-muted;
        margin-top: 1;
    }
    """

    def __init__(
        self,
        categories: list[dict],
        transaction: Optional[TransactionSummary] = None,
        **kwargs,
    ) -> None:
        """Initialize the category picker modal.

        Args:
            categories: List of category dicts with id, name, group_name.
            transaction: Optional transaction summary to display.
        """
        self._transaction = transaction
        self._current_category_id = transaction.current_category_id if transaction else None

        super().__init__(
            items=categories,
            display_fn=self._format_category,
            search_fn=self._search_text,
            result_fn=self._make_result,
            placeholder="Type to filter...",
            show_all_on_empty=True,
            debounce_delay=0,
            **kwargs,
        )

    def _format_category(self, cat: dict) -> str:
        """Format category for display: [Group] Name (with current marker)."""
        group = cat.get("group_name", "")
        name = cat["name"]
        display = f"[dim]\\[{group}][/dim] {name}" if group else name
        if self._current_category_id and cat["id"] == self._current_category_id:
            return f"{display} [dim]← current[/dim]"
        return display

    @staticmethod
    def _search_text(cat: dict) -> str:
        """Extract searchable text from category."""
        group = cat.get("group_name", "")
        name = cat["name"]
        return f"{group} {name}"

    @staticmethod
    def _make_result(cat: dict) -> CategorySelection:
        """Create result from selected category."""
        return CategorySelection(
            category_id=cat["id"],
            category_name=cat["name"],
        )

    def compose(self) -> ComposeResult:
        """Compose the modal UI with transaction summary."""
        with Vertical(id="fuzzy-container"):
            # Transaction summary (unique to CategoryPickerModal)
            if self._transaction:
                with Vertical(id="txn-summary"):
                    yield Static(
                        f"[b]{self._transaction.payee}[/b]  {self._transaction.amount}",
                        classes="summary-line",
                    )
                    category_text = self._transaction.current_category or "[dim]Uncategorized[/dim]"
                    yield Static(
                        f"[dim]{self._transaction.date}[/dim]  {category_text}",
                        classes="summary-line",
                    )
                    if self._transaction.amazon_items:
                        items_text = ", ".join(self._transaction.amazon_items[:3])
                        if len(self._transaction.amazon_items) > 3:
                            items_text += f" (+{len(self._transaction.amazon_items) - 3} more)"
                        yield Static(f"↳ {items_text}", classes="amazon-items")

            yield Input(placeholder=self._placeholder, id="fuzzy-input")
            yield ListView(id="fuzzy-list")
            yield Static(
                "↑↓ navigate • PgUp/PgDn scroll • Enter select • Esc cancel",
                id="fuzzy-footer",
            )
