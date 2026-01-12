"""Category picker modal using FuzzySelectModal base."""

from dataclasses import dataclass
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, ListItem, ListView, Static

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
    suggested_categories: Optional[list[dict]] = None


class CategoryPickerModal(FuzzySelectModal[CategorySelection]):
    """fzf-style fuzzy category picker modal.

    Opens as an overlay, type to filter, j/k to navigate, Enter to select.
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
            return f"[bold cyan]{display}[/bold cyan] [yellow]<- Current[/yellow]"
        return display

    def _format_suggestion(self, suggestion: dict) -> str:
        """Format a suggested category for display."""
        group = suggestion.get("group_name", "")
        name = suggestion["category_name"]
        count = suggestion["count"]

        # Build count display
        if suggestion.get("source") == "items" and suggestion.get("item_count", 0) > 1:
            count_str = f"({count}x, {suggestion['item_count']} items)"
        else:
            count_str = f"({count}x)"

        display = f"[dim]\\[{group}][/dim] {name}" if group else name
        return f"[bold green]★ {display}[/bold green] [green]{count_str}[/green]"

    def _find_current_category_index(self) -> int:
        """Find the index of the current category in filtered items."""
        if not self._current_category_id:
            return 0
        for i, cat in enumerate(self._filtered_items):
            if cat["id"] == self._current_category_id:
                return i
        return 0

    def _populate_list(self) -> None:
        """Populate list with suggestions at top, then all categories."""
        from .fuzzy_select import FuzzySelectItem

        self._populate_generation += 1
        generation = self._populate_generation

        list_view = self.query_one("#fuzzy-list", ListView)
        list_view.clear()

        query = self.query_one("#fuzzy-input", Input).value.strip()

        # Show suggestions only when no search query
        suggestions = (
            self._transaction.suggested_categories
            if self._transaction and self._transaction.suggested_categories
            else None
        )
        suggestion_count = 0
        if not query and suggestions:
            for suggestion in suggestions:
                display_text = self._format_suggestion(suggestion)
                # Create a category dict that maps to the suggestion
                cat_dict = {
                    "id": suggestion["category_id"],
                    "name": suggestion["category_name"],
                    "group_name": suggestion.get("group_name", ""),
                }
                list_view.append(FuzzySelectItem(display_text, cat_dict))
                suggestion_count += 1

            # Add separator
            list_view.append(ListItem(Static("[dim]─── All Categories ───[/dim]")))

        # Handle empty filtered items
        if not query and not self._show_all_on_empty:
            list_view.append(ListItem(Static("[dim]Type to search...[/dim]")))
            return

        if not self._filtered_items:
            list_view.append(ListItem(Static("No matches found")))
            return

        # Add regular categories (limit results for performance)
        max_results = 100
        for item in self._filtered_items[:max_results]:
            display_text = self._display_fn(item)
            list_view.append(FuzzySelectItem(display_text, item))

        # Determine initial selection
        def set_selection() -> None:
            if generation != self._populate_generation:
                return
            if not query and self._current_category_id:
                # Scroll to current category (after suggestions + separator)
                offset = suggestion_count + (1 if suggestion_count > 0 else 0)
                current_idx = self._find_current_category_index()
                list_view.index = offset + current_idx
            elif len(list_view) > 0:
                list_view.index = 0

        self.call_after_refresh(set_selection)

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
                "j/k navigate • Enter select • Esc cancel",
                id="fuzzy-footer",
            )
