"""Item split screen for Amazon multi-item transactions."""

from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, ListItem, ListView, Static

from ...models import Transaction
from ...services import CategorizerService
from ..constants import VIM_NAVIGATION_BINDINGS
from ..modals import CategoryPickerModal, CategorySelection, TransactionSummary


class SplitItemListItem(ListItem):
    """A list item for an Amazon order item in split view."""

    def __init__(
        self,
        item: dict,
        index: int,
        assigned_category: Optional[dict] = None,
    ) -> None:
        super().__init__()
        self.item = item
        self.index = index
        self.assigned_category = assigned_category

    def compose(self) -> ComposeResult:
        yield Static(self._format_row())

    def _format_row(self) -> str:
        """Format the item row display."""
        name = self.item.get("item_name", "Unknown Item")
        price = self.item.get("item_price", 0) or 0
        quantity = self.item.get("quantity", 1) or 1

        # Truncate name to ~40 chars
        if len(name) > 40:
            name = name[:37] + "..."

        # Format price
        price_str = f"${price:.2f}"

        # Format quantity
        qty_str = f"x{quantity}" if quantity > 1 else "   "

        # Status indicator and category
        if self.assigned_category:
            status = "[*]"
            cat_name = self.assigned_category.get("category_name", "")[:20]
            cat_str = f"[green]{cat_name}[/green]"
        else:
            status = "[ ]"
            cat_str = "[dim]uncategorized[/dim]"

        return f"{status} {name:<40}  {qty_str:>3}  {price_str:>8}  {cat_str}"

    def update_category(self, category: Optional[dict]) -> None:
        """Update the assigned category and refresh display."""
        self.assigned_category = category
        self.query_one(Static).update(self._format_row())


class ItemSplitScreen(ModalScreen[bool]):
    """Modal screen for splitting Amazon transactions by item.

    Shows a ListView of order items, navigate with j/k, press 'c' to
    categorize each using CategoryPickerModal.

    Returns True if split was applied, False if cancelled.
    """

    CSS = """
    ItemSplitScreen {
        background: $surface;
    }

    #split-container {
        width: 100%;
        height: 1fr;
        padding: 1;
    }

    #header-section {
        height: auto;
        padding: 1;
        border: solid $primary;
        margin-bottom: 1;
    }

    #items-list {
        height: 1fr;
        border: solid $primary-background;
    }

    #summary-section {
        height: auto;
        padding: 1;
        border-top: solid $primary-background;
    }

    SplitItemListItem {
        height: 1;
        padding: 0 1;
    }

    SplitItemListItem.--highlight {
        background: $primary;
    }
    """

    BINDINGS = [
        *VIM_NAVIGATION_BINDINGS,
        Binding("down", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up", show=False),
        Binding("c", "categorize_item", "Categorize"),
        Binding("enter", "submit_or_categorize", "Select/Submit", show=False),
        Binding("s", "submit_split", "Submit"),
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "cancel", "Cancel", show=False),
    ]

    def __init__(
        self,
        categorizer: CategorizerService,
        transaction: Transaction,
        categories: list[dict],
        items_with_prices: list[dict],
        existing_splits: Optional[list[dict]] = None,
        **kwargs,
    ) -> None:
        """Initialize the item split screen.

        Args:
            categorizer: Categorizer service for applying categories.
            transaction: The Amazon transaction to split.
            categories: List of category dicts for picker.
            items_with_prices: List of dicts with item_name, item_price, quantity.
            existing_splits: Existing pending splits to pre-populate (for re-editing).
        """
        super().__init__(**kwargs)
        self._categorizer = categorizer
        self._transaction = transaction
        self._categories = categories
        self._items = items_with_prices

        # Track assignments: {index: {category_id, category_name}}
        self._assignments: dict[int, dict] = {}

        # Pre-populate assignments from existing pending splits
        if existing_splits:
            self._load_existing_splits(existing_splits)

    def _load_existing_splits(self, existing_splits: list[dict]) -> None:
        """Load existing pending splits into assignments.

        Matches splits to items by memo (which contains item name).
        """
        for split in existing_splits:
            memo = split.get("memo", "")
            category_id = split.get("category_id")
            category_name = split.get("category_name")

            if not category_id or not category_name:
                continue

            # Find matching item by name (memo contains item name)
            for i, item in enumerate(self._items):
                item_name = item.get("item_name", "")
                # Match if memo starts with item name (memo may be truncated)
                if memo and item_name and (memo == item_name[:100] or item_name.startswith(memo)):
                    if i not in self._assignments:
                        self._assignments[i] = {
                            "category_id": category_id,
                            "category_name": category_name,
                        }
                        break

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="split-container"):
            # Transaction header
            yield Vertical(
                Static("[b]Amazon Order Split[/b]"),
                Static(
                    f"{self._transaction.payee_name}  |  "
                    f"{self._transaction.display_date}  |  "
                    f"{self._transaction.display_amount}"
                ),
                id="header-section",
            )

            # Items list
            yield ListView(id="items-list")

            # Summary section
            yield Vertical(
                Static(id="summary-text"),
                id="summary-section",
            )

        yield Footer()

    def on_mount(self) -> None:
        """Populate the items list on mount."""
        self._populate_list()
        self._update_summary()

    def _populate_list(self) -> None:
        """Populate the ListView with items."""
        list_view = self.query_one("#items-list", ListView)
        list_view.clear()

        for i, item in enumerate(self._items):
            assigned = self._assignments.get(i)
            list_item = SplitItemListItem(item, i, assigned)
            list_view.append(list_item)

        if self._items:
            list_view.index = 0

    def _update_summary(self) -> None:
        """Update the summary section with totals and remainder."""
        items_total = sum(item.get("item_price", 0) or 0 for item in self._items)
        txn_total = abs(self._transaction.amount)
        remainder = txn_total - items_total
        categorized = len(self._assignments)
        total_items = len(self._items)

        summary_parts = [
            f"Items: {categorized}/{total_items} categorized",
            f"Items total: ${items_total:.2f}",
            f"Transaction: ${txn_total:.2f}",
        ]
        if remainder > 0.01:
            summary_parts.append(
                f"Remainder (tax/shipping): ${remainder:.2f} [dim](distributed evenly)[/dim]"
            )

        self.query_one("#summary-text", Static).update("  |  ".join(summary_parts))

    def _get_current_item_index(self) -> Optional[int]:
        """Get the index of the currently selected item."""
        list_view = self.query_one("#items-list", ListView)
        return list_view.index

    def _get_current_item(self) -> Optional[dict]:
        """Get the currently selected item."""
        idx = self._get_current_item_index()
        if idx is not None and 0 <= idx < len(self._items):
            return self._items[idx]
        return None

    def action_cursor_down(self) -> None:
        """Move cursor down."""
        list_view = self.query_one("#items-list", ListView)
        if list_view.index is not None and list_view.index < len(self._items) - 1:
            list_view.index += 1

    def action_cursor_up(self) -> None:
        """Move cursor up."""
        list_view = self.query_one("#items-list", ListView)
        if list_view.index is not None and list_view.index > 0:
            list_view.index -= 1

    def action_categorize_item(self) -> None:
        """Open category picker for the current item."""
        item = self._get_current_item()
        if not item:
            return

        idx = self._get_current_item_index()
        item_name = item.get("item_name", "Unknown")[:40]
        item_price = item.get("item_price", 0) or 0

        # Build summary for modal header
        current_cat = self._assignments.get(idx) if idx is not None else None
        summary = TransactionSummary(
            date=self._transaction.display_date,
            payee=item_name,
            amount=f"${item_price:.2f}",
            current_category=current_cat.get("category_name") if current_cat else None,
            current_category_id=current_cat.get("category_id") if current_cat else None,
            amazon_items=None,
        )

        modal = CategoryPickerModal(categories=self._categories, transaction=summary)
        self.app.push_screen(modal, self._on_item_category_selected)

    def _on_item_category_selected(self, result: Optional[CategorySelection]) -> None:
        """Handle category selection for current item."""
        if result is None:
            return  # Cancelled

        idx = self._get_current_item_index()
        if idx is None:
            return

        # Store assignment
        self._assignments[idx] = {
            "category_id": result.category_id,
            "category_name": result.category_name,
        }

        # Update the list item display
        list_view = self.query_one("#items-list", ListView)
        if list_view.highlighted_child and isinstance(
            list_view.highlighted_child, SplitItemListItem
        ):
            list_view.highlighted_child.update_category(self._assignments[idx])

        # Update summary
        self._update_summary()

        # Notify
        item = self._items[idx]
        item_name = item.get("item_name", "Unknown")[:25]
        self.notify(f"✓ {item_name} → {result.category_name}")

        # Auto-advance to next uncategorized item
        self._advance_to_next_uncategorized()

    def _advance_to_next_uncategorized(self) -> None:
        """Move to the next uncategorized item if any."""
        list_view = self.query_one("#items-list", ListView)
        current = list_view.index or 0

        # Look for next uncategorized starting from current+1
        for i in range(current + 1, len(self._items)):
            if i not in self._assignments:
                list_view.index = i
                return

        # Wrap around and check from beginning
        for i in range(0, current):
            if i not in self._assignments:
                list_view.index = i
                return

        # All categorized - stay on current

    def action_submit_or_categorize(self) -> None:
        """Enter key: categorize if uncategorized, submit if all done."""
        idx = self._get_current_item_index()

        # If current item uncategorized, categorize it
        if idx is not None and idx not in self._assignments:
            self.action_categorize_item()
            return

        # If all items categorized, submit
        if len(self._assignments) == len(self._items):
            self.action_submit_split()
        else:
            # Move to next uncategorized
            self._advance_to_next_uncategorized()
            self.notify(f"{len(self._items) - len(self._assignments)} items still need categories")

    def action_submit_split(self) -> None:
        """Submit the split transaction."""
        # Validate all items are categorized
        if len(self._assignments) != len(self._items):
            uncategorized = len(self._items) - len(self._assignments)
            self.notify(f"{uncategorized} items still need categories", severity="warning")
            return

        # Calculate splits with distributed remainder
        splits = self._calculate_splits_with_remainder()

        # Apply to categorizer
        try:
            self._categorizer.apply_split_categories(
                transaction=self._transaction,
                splits=splits,
            )
            self.notify(f"✓ Split into {len(splits)} categories!")
            self.dismiss(True)  # Signal success to callback

        except Exception as e:
            self.notify(f"Error: {e}", severity="error")

    def _calculate_splits_with_remainder(self) -> list[dict]:
        """Build splits list with remainder distributed evenly."""
        txn_total = abs(self._transaction.amount)
        items_total = sum(item.get("item_price", 0) or 0 for item in self._items)
        remainder = txn_total - items_total

        # Calculate per-item remainder share
        num_items = len(self._items)
        per_item_remainder = remainder / num_items if num_items > 0 else 0

        splits = []
        running_total = 0.0

        for i, item in enumerate(self._items):
            assignment = self._assignments.get(i)
            if not assignment:
                continue  # Should not happen

            base_price = item.get("item_price", 0) or 0

            # Last item gets remaining to ensure exact total match
            if i == num_items - 1:
                item_amount = round(txn_total - running_total, 2)
            else:
                item_amount = round(base_price + per_item_remainder, 2)

            running_total += item_amount

            splits.append(
                {
                    "category_id": assignment["category_id"],
                    "category_name": assignment["category_name"],
                    "amount": -item_amount,  # Negative for outflow
                    "memo": item.get("item_name", "")[:100],
                }
            )

        return splits

    def action_cancel(self) -> None:
        """Cancel and return to main screen."""
        self.dismiss(False)  # Signal cancellation to callback
