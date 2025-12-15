"""Category picker widget for selecting YNAB categories."""

from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Input, Static

from ..constants import VIM_NAVIGATION_BINDINGS
from ..mixins import NavigationMixin


class CategoryPicker(NavigationMixin, Vertical):
    """Widget for selecting a category from the available YNAB categories.

    Features:
    - Search/filter as you type
    - Vim-style navigation (j/k)
    - Groups categories by category group
    - Highlights AI-suggested category
    """

    DEFAULT_CSS = """
    CategoryPicker {
        height: 100%;
        width: 100%;
    }

    CategoryPicker > #search-input {
        dock: top;
        height: 3;
        margin: 0 0 1 0;
    }

    CategoryPicker > #category-list {
        height: 1fr;
        border: solid $primary;
    }

    CategoryPicker .category-item {
        height: 2;
        padding: 0 1;
    }

    CategoryPicker .category-item:hover {
        background: $primary-background;
    }

    CategoryPicker .category-item.--highlight {
        background: $primary;
        color: $text;
    }

    CategoryPicker .category-item.suggested {
        color: $success;
    }

    CategoryPicker .group-header {
        height: 2;
        padding: 0 1;
        background: $surface;
        color: $text-muted;
        text-style: bold;
    }
    """

    BINDINGS = [
        *VIM_NAVIGATION_BINDINGS,
        Binding("down", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up", show=False),
        Binding("enter", "select_category", "Select"),
        Binding("escape", "cancel", "Cancel"),
    ]

    class CategorySelected(Message):
        """Message sent when a category is selected."""

        def __init__(self, category_id: str, category_name: str) -> None:
            self.category_id = category_id
            self.category_name = category_name
            super().__init__()

    class Cancelled(Message):
        """Message sent when selection is cancelled."""

        pass

    def __init__(
        self,
        categories: list[dict],
        suggested_id: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Initialize the category picker.

        Args:
            categories: List of category dicts with id, name, group_name.
            suggested_id: ID of AI-suggested category to highlight.
        """
        super().__init__(**kwargs)
        self._all_categories = categories
        self._filtered_categories = categories.copy()
        self._suggested_id = suggested_id
        self._selected_index = 0

        # Find index of suggested category
        if suggested_id:
            for i, cat in enumerate(self._filtered_categories):
                if cat["id"] == suggested_id:
                    self._selected_index = i
                    break

    def compose(self) -> ComposeResult:
        """Compose the widget."""
        yield Input(placeholder="Type to filter categories...", id="search-input")
        yield VerticalScroll(id="category-list")

    def on_mount(self) -> None:
        """Handle mount event."""
        self._render_categories()
        # Focus the search input
        self.query_one("#search-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search input changes."""
        query = event.value.lower().strip()
        if query:
            self._filtered_categories = [
                cat
                for cat in self._all_categories
                if query in cat["name"].lower() or query in cat.get("group_name", "").lower()
            ]
        else:
            self._filtered_categories = self._all_categories.copy()

        self._selected_index = 0

        # If we have a suggested category and it's in filtered results, select it
        if self._suggested_id and not query:
            for i, cat in enumerate(self._filtered_categories):
                if cat["id"] == self._suggested_id:
                    self._selected_index = i
                    break

        self._render_categories()

    def _render_categories(self) -> None:
        """Render the category list."""
        container = self.query_one("#category-list", VerticalScroll)
        container.remove_children()

        if not self._filtered_categories:
            container.mount(Static("No matching categories", classes="category-item"))
            return

        # Group categories
        groups: dict[str, list[dict]] = {}
        for cat in self._filtered_categories:
            group = cat.get("group_name", "Other")
            if group not in groups:
                groups[group] = []
            groups[group].append(cat)

        # Render grouped categories
        flat_index = 0
        for group_name, cats in sorted(groups.items()):
            # Group header
            container.mount(Static(f"[{group_name}]", classes="group-header"))

            for cat in cats:
                classes = "category-item"
                if flat_index == self._selected_index:
                    classes += " --highlight"
                if cat["id"] == self._suggested_id:
                    classes += " suggested"

                # Format label
                label = cat["name"]
                if cat["id"] == self._suggested_id:
                    label = f"★ {label} (AI suggested)"

                item = Static(label, classes=classes)
                item.data = cat  # type: ignore[attr-defined]  # Textual widget data
                container.mount(item)
                flat_index += 1

    def _get_selectable_count(self) -> int:
        """Get the number of selectable items."""
        return len(self._filtered_categories)

    # NavigationMixin implementation
    def _nav_get_item_count(self) -> int:
        return self._get_selectable_count()

    def _nav_get_current_index(self) -> int:
        return self._selected_index

    def _nav_set_current_index(self, index: int) -> None:
        self._selected_index = index

    def _nav_on_index_changed(self) -> None:
        self._render_categories()
        self._scroll_to_selected()

    def _scroll_to_selected(self) -> None:
        """Scroll to ensure selected item is visible."""
        try:
            # Find the highlighted item
            item = self.query_one(".category-item.--highlight")
            item.scroll_visible()
        except Exception:
            pass

    def action_select_category(self) -> None:
        """Select the current category."""
        if self._filtered_categories and self._selected_index < len(self._filtered_categories):
            cat = self._filtered_categories[self._selected_index]
            self.post_message(self.CategorySelected(cat["id"], cat["name"]))

    def action_cancel(self) -> None:
        """Cancel category selection."""
        self.post_message(self.Cancelled())

    def on_key(self, event) -> None:
        """Handle key events for enter in input."""
        if event.key == "enter":
            self.action_select_category()
            event.stop()
