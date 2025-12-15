"""Reusable fuzzy select modal with fzf-style matching."""

from typing import Any, Callable, Generic, Optional, TypeVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Input, ListItem, ListView, Static

from ...utils import fuzzy_match

# Type variable for the return type
T = TypeVar("T")

# Performance constants
MAX_RESULTS = 100
DEBOUNCE_DELAY = 0.15


class FuzzySelectItem(ListItem):
    """A list item for fuzzy select results."""

    def __init__(self, display_text: str, item: Any) -> None:
        super().__init__()
        self.item = item
        self._display_text = display_text

    def compose(self) -> ComposeResult:
        yield Static(self._display_text)


class FuzzySelectModal(ModalScreen[Optional[T]], Generic[T]):
    """Reusable fzf-style fuzzy selection modal.

    Opens as an overlay, type to filter, arrow keys to navigate, Enter to select.
    Returns the selected item via result_fn, or None on cancel.
    """

    DEFAULT_CSS = """
    FuzzySelectModal {
        align: center middle;
    }

    FuzzySelectModal > #fuzzy-container {
        width: 70;
        height: 80%;
        max-height: 45;
        background: $surface;
        border: thick $primary;
        padding: 1;
    }

    FuzzySelectModal > #fuzzy-container > #fuzzy-title {
        height: 1;
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }

    FuzzySelectModal > #fuzzy-container > #fuzzy-input {
        height: 3;
        margin-bottom: 1;
    }

    FuzzySelectModal > #fuzzy-container > #fuzzy-list {
        height: 1fr;
        border: solid $primary-background;
    }

    FuzzySelectModal > #fuzzy-container > #fuzzy-footer {
        height: 1;
        text-align: center;
        color: $text-muted;
        margin-top: 1;
    }

    FuzzySelectItem {
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        items: list[Any],
        display_fn: Callable[[Any], str],
        search_fn: Callable[[Any], str],
        result_fn: Callable[[Any], T],
        placeholder: str = "Type to filter...",
        title: str = "",
        show_all_on_empty: bool = False,
        debounce_delay: float = DEBOUNCE_DELAY,
        **kwargs,
    ) -> None:
        """Initialize the fuzzy select modal.

        Args:
            items: List of items to search through.
            display_fn: Function to format item for display in the list.
            search_fn: Function to extract searchable text from item.
            result_fn: Function to extract return value from selected item.
            placeholder: Placeholder text for the search input.
            title: Optional title to display above the search input.
            show_all_on_empty: If True, show all items when search is empty.
            debounce_delay: Delay before searching (0 for immediate).
        """
        super().__init__(**kwargs)
        self._all_items = items
        self._filtered_items: list[Any] = items.copy() if show_all_on_empty else []
        self._display_fn = display_fn
        self._search_fn = search_fn
        self._result_fn = result_fn
        self._placeholder = placeholder
        self._title = title
        self._show_all_on_empty = show_all_on_empty
        self._debounce_delay = debounce_delay
        self._populate_generation = 0
        self._search_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        """Compose the modal UI."""
        with Vertical(id="fuzzy-container"):
            if self._title:
                yield Static(self._title, id="fuzzy-title")
            yield Input(placeholder=self._placeholder, id="fuzzy-input")
            yield ListView(id="fuzzy-list")
            yield Static(
                "↑↓ navigate • PgUp/PgDn scroll • Enter select • Esc cancel",
                id="fuzzy-footer",
            )

    def on_mount(self) -> None:
        """Handle mount - focus input and optionally populate list."""
        self.query_one("#fuzzy-input", Input).focus()
        if self._show_all_on_empty:
            self._populate_list()

    def _populate_list(self) -> None:
        """Populate the ListView with filtered items."""
        self._populate_generation += 1
        generation = self._populate_generation

        list_view = self.query_one("#fuzzy-list", ListView)
        list_view.clear()

        query = self.query_one("#fuzzy-input", Input).value.strip()
        if not query and not self._show_all_on_empty:
            list_view.append(ListItem(Static("[dim]Type to search...[/dim]")))
            return

        if not self._filtered_items:
            list_view.append(ListItem(Static("No matches found")))
            return

        # Limit results for performance
        for item in self._filtered_items[:MAX_RESULTS]:
            display_text = self._display_fn(item)
            list_view.append(FuzzySelectItem(display_text, item))

        def set_selection():
            if generation != self._populate_generation:
                return
            if len(self._filtered_items) > 0:
                list_view.index = 0

        self.call_after_refresh(set_selection)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search input changes with debounced fuzzy matching."""
        if self._search_timer:
            self._search_timer.stop()
        if self._debounce_delay > 0:
            self._search_timer = self.set_timer(self._debounce_delay, self._do_search)
        else:
            self._do_search()

    def _do_search(self) -> None:
        """Execute the fuzzy search (called after debounce delay)."""
        query = self.query_one("#fuzzy-input", Input).value.lower().strip()
        if query:
            self._filtered_items = [
                item
                for item in self._all_items
                if fuzzy_match(query, self._search_fn(item).lower())
            ]
        else:
            self._filtered_items = self._all_items.copy() if self._show_all_on_empty else []
        self._populate_list()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle Enter on ListView - select the item."""
        if isinstance(event.item, FuzzySelectItem):
            result = self._result_fn(event.item.item)
            self.dismiss(result)
        event.stop()

    def action_cancel(self) -> None:
        """Cancel and dismiss modal."""
        self.dismiss(None)

    def on_key(self, event) -> None:
        """Forward navigation and Enter keys to ListView even when Input is focused."""
        list_view = self.query_one("#fuzzy-list", ListView)

        # Handle Enter - select current item
        if event.key == "enter":
            if list_view.index is not None and len(self._filtered_items) > 0:
                idx = list_view.index
                if 0 <= idx < len(self._filtered_items):
                    item = self._filtered_items[idx]
                    result = self._result_fn(item)
                    self.dismiss(result)
                    event.stop()
                    event.prevent_default()
            return

        # Handle navigation keys
        if event.key in ("pageup", "pagedown", "up", "down"):
            current = list_view.index or 0
            max_index = len(list_view) - 1
            if max_index < 0:
                return
            if event.key == "pageup":
                new_index = max(current - 10, 0)
            elif event.key == "pagedown":
                new_index = min(current + 10, max_index)
            elif event.key == "up":
                new_index = max(current - 1, 0)
            elif event.key == "down":
                new_index = min(current + 1, max_index)
            list_view.index = new_index
            event.prevent_default()
