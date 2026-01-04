"""Main TUI application for YNAB Categorizer.

Built with Textual for a modern terminal UI experience.
"""

from datetime import datetime, timedelta
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.css.query import NoMatches
from textual.timer import Timer
from textual.widgets import Footer, ListItem, ListView, Static

from .. import __version__
from ..models import Transaction, TransactionBatch
from ..services import CategorizerService
from .constants import VIM_NAVIGATION_BINDINGS
from .handlers import ActionHandler
from .layout import ColumnWidths, calculate_column_widths, format_header_row
from .mixins import ListViewNavigationMixin
from .modals import (
    BudgetPickerModal,
    BudgetSelection,
    CategoryFilterModal,
    CategoryFilterResult,
    CategoryPickerModal,
    CategorySelection,
    PayeeFilterModal,
    TransactionSearchModal,
    TransactionSummary,
    get_unique_payees,
)
from .screens import HelpScreen, ItemSplitScreen, PushPreviewScreen, SettingsScreen
from .state import (
    CategoryFilter,
    FilterState,
    FilterStateMachine,
    TagManager,
    TagState,
)


class TransactionListItem(ListItem):
    """A list item displaying a transaction row."""

    def __init__(
        self,
        txn: Transaction,
        tag_state: TagState | None = None,
        column_widths: ColumnWidths | None = None,
        color_status_letters: bool = False,
    ) -> None:
        """Initialize with a transaction.

        Args:
            txn: The transaction to display.
            tag_state: Tag state for checking if transaction is tagged.
            column_widths: Column width configuration for formatting.
            color_status_letters: Whether to color-code status letters.
        """
        super().__init__()
        self.txn = txn
        self._tag_state = tag_state if tag_state is not None else TagState()
        self._column_widths = column_widths if column_widths is not None else ColumnWidths()
        self._color_status_letters = color_status_letters

        # Apply status-based styling classes
        if txn.sync_status == "pending_push":
            self.add_class("-pending")
        elif not txn.approved:
            self.add_class("-new")

    def compose(self) -> ComposeResult:
        """Compose the list item content."""
        yield Static(self._format_row(), id="row-content")

    def update_content(self) -> None:
        """Update the displayed content after transaction changes."""
        # Update CSS classes based on current state
        self.remove_class("-new", "-pending")
        if self.txn.sync_status == "pending_push":
            self.add_class("-pending")
        elif not self.txn.approved:
            self.add_class("-new")

        # Update text content
        try:
            static = self.query_one("#row-content", Static)
            static.update(self._format_row())
        except Exception:
            pass  # Widget might not be mounted yet

    def _format_row(self) -> str:
        """Format the transaction as a row string."""
        txn = self.txn
        w = self._column_widths
        sp = " " * w.col_spacing

        # Format date (fixed width)
        date_str = txn.display_date[: w.date].ljust(w.date)

        # Tag indicator (green star) - 2 chars + Amazon indicator - 2 chars
        # Remaining for payee name
        payee_name_width = w.payee - 4  # Reserve 4 chars for indicators
        tag = "[green]★[/green] " if self._tag_state.contains(txn.id) else "  "
        payee = txn.payee_name[:payee_name_width].ljust(payee_name_width)
        if txn.is_amazon:
            payee = f"[yellow]*[/yellow] {payee}"
        else:
            payee = f"  {payee}"  # Align with Amazon indicator
        payee = f"{tag}{payee}"

        # Format amount (fixed width, right-aligned)
        amount = txn.display_amount.rjust(w.amount)

        # Format category (dynamic width)
        cat_width = w.category
        if txn.is_transfer:
            target = txn.transfer_account_name or "Transfer"
            transfer_text = f"-> {target}"[:cat_width]
            category = f"[cyan]{transfer_text:<{cat_width}}[/cyan]"
        elif txn.is_balance_adjustment:
            category = f"[dim]{'(Balance Adj)':<{cat_width}}[/dim]"
        elif txn.category_name:
            category = txn.category_name[:cat_width].ljust(cat_width)
        else:
            category = " " * cat_width

        # Format account (dynamic width)
        account = (txn.account_name or "")[: w.account].ljust(w.account)

        # Format status (fixed width) with optional color-coding
        status_flags = ""
        if self._color_status_letters:
            if txn.approved:
                status_flags += "[green]A[/green]"
            if txn.cleared == "cleared":
                status_flags += "[cyan]C[/cyan]"
            elif txn.cleared == "reconciled":
                status_flags += "[blue]R[/blue]"
            if txn.memo:
                status_flags += "[yellow]M[/yellow]"
            if txn.sync_status == "pending_push":
                status_flags += "[magenta]P[/magenta]"
            elif txn.sync_status == "conflict":
                status_flags += "[red]![/red]"
            # Calculate visible length (without Rich markup)
            visible_len = sum(1 for c in status_flags if c in "ACRMP!")
            status = status_flags + " " * (w.status - visible_len)
        else:
            # Plain text status (no colors)
            if txn.approved:
                status_flags += "A"
            if txn.cleared == "cleared":
                status_flags += "C"
            elif txn.cleared == "reconciled":
                status_flags += "R"
            if txn.memo:
                status_flags += "M"
            if txn.sync_status == "pending_push":
                status_flags += "P"
            elif txn.sync_status == "conflict":
                status_flags += "!"
            status = status_flags.ljust(w.status)

        # Format enrichment on second line(s) - only show Amazon items
        enrichment = ""
        if txn.is_amazon and txn.amazon_items:
            indent = w.date + w.col_spacing
            lines = [f"{'':{indent}}[dim]↳ {item[:60]}[/dim]" for item in txn.amazon_items]
            enrichment = "\n" + "\n".join(lines)

        return (
            f"{date_str}{sp}{payee}{sp}{amount}{sp}{category}{sp}{account}{sp}{status}{enrichment}"
        )


class YNABCategorizerApp(ListViewNavigationMixin, App):
    """Main YNAB Categorizer TUI application."""

    TITLE = "YNAB TUI"
    CSS = """
    Screen {
        background: $surface;
    }

    #app-header {
        dock: top;
        height: 1;
        background: $primary;
        padding: 0 1;
        text-align: center;
        text-style: bold;
    }

    #main-container {
        width: 100%;
        height: 100%;
        padding: 0;
    }

    #transactions-list {
        height: 1fr;
        border: solid $primary;
    }

    .transaction-header {
        height: auto;
        padding: 0 1;
        background: $primary-background;
        text-style: bold;
    }

    /* ListView item styling */
    TransactionListItem {
        height: auto;
        padding: 0 1;
        background: $surface;
    }

    TransactionListItem:hover {
        background: $primary-background;
    }

    /* ListView handles the highlight class for selected items */
    TransactionListItem.-highlight {
        background: $primary;
    }

    /* New/unapproved transactions - different text color */
    TransactionListItem.-new {
        color: #88aacc;
    }

    /* When highlighted, use light cyan to distinguish from normal rows */
    TransactionListItem.-new.-highlight {
        color: #ccddee;
    }

    /* Pending push transactions - green text (ready to push) */
    TransactionListItem.-pending {
        color: #98c379;
    }

    TransactionListItem.-pending.-highlight {
        color: #b5e890;
    }

    .amazon-indicator {
        color: $warning;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: $primary-background;
        padding: 0 1;
    }

    #loading-indicator {
        width: 100%;
        height: 100%;
        content-align: center middle;
    }
    """

    BINDINGS = [
        # Vim-style navigation (forward to ListView)
        *VIM_NAVIGATION_BINDINGS,
        # Essential actions (shown in footer - 8 total)
        Binding("c", "categorize", "Category"),
        Binding("a", "approve", "Approve"),
        Binding("u", "undo", "Undo"),
        Binding("f", "cycle_filter", "Filter"),
        Binding("/", "fuzzy_search", "Search"),
        Binding("p", "push_preview", "Push"),
        Binding("x", "split", "Split"),
        Binding("?", "show_help", "Help"),
        # Hidden actions (still work, not shown in footer)
        Binding("m", "edit_memo", "Memo", show=False),
        Binding("s", "settings", "Settings", show=False),
        Binding("q", "quit", "Quit", show=False),
        Binding("escape", "quit", "Quit", show=False),
        Binding("b", "switch_budget", "Budget", show=False),
        Binding("t", "toggle_tag", "Tag", show=False),
        Binding("T", "clear_all_tags", "Untag All", show=False),
        Binding("f5", "refresh", "Refresh", show=False),
    ]

    # Filter modes and their labels
    FILTER_MODES = ["all", "approved", "new", "uncategorized", "pending"]
    FILTER_LABELS = {
        "all": "All",
        "approved": "Approved",
        "new": "New (Unapproved)",
        "uncategorized": "Uncategorized",
        "pending": "Pending Push",
    }
    # Key mappings for filter submenu
    FILTER_KEYS = {
        "a": "approved",
        "n": "new",
        "u": "uncategorized",
        "e": "pending",
        "r": "all",  # Reset to all
        "c": "category",  # Opens category filter modal
        "p": "payee",  # Opens payee filter modal
    }

    def __init__(
        self,
        categorizer: CategorizerService,
        is_mock: bool = False,
        load_since_months: Optional[int] = 6,
    ):
        """Initialize the app.

        Args:
            categorizer: Categorizer service instance.
            is_mock: Whether running in mock mode.
            load_since_months: Only load transactions from the last N months.
                None means load all transactions.
        """
        super().__init__()
        self._categorizer = categorizer
        self._action_handler = ActionHandler(categorizer)
        self._is_mock = is_mock
        self._load_since_months = load_since_months
        self._transactions: TransactionBatch = TransactionBatch()
        # Filter state (immutable - replaced on changes)
        self._filter_state = FilterState()
        self._filter_timer: Timer | None = None  # Timer to cancel pending state
        # Tag state (immutable - replaced on changes)
        self._tag_state = TagState()
        # Budget state - will be populated on mount
        self._current_budget_id: Optional[str] = None
        self._current_budget_name: Optional[str] = None
        # Column widths - calculated based on terminal size
        self._column_widths = ColumnWidths()
        # Display settings from config
        self._color_status_letters = categorizer.get_config().display.color_status_letters

    def _get_list_view(self) -> ListView | None:
        """Get the transactions ListView if it exists."""
        try:
            return self.query_one("#transactions-list", ListView)
        except Exception:
            return None

    def _build_header_text(self) -> str:
        """Build the header text with program name, version, and budget."""
        budget_name = self._current_budget_name or "Loading..."
        return f"YNAB TUI v{__version__} │ [cyan]{budget_name}[/cyan]"

    def _update_header(self) -> None:
        """Update the header text with current budget name."""
        try:
            header = self.query_one("#app-header", Static)
            header.update(self._build_header_text())
        except Exception:
            pass  # Header might not be mounted yet

    def _build_status_bar_text(self) -> str:
        """Build the status bar text with filter and counts."""
        parts = []

        # Mock indicator
        if self._is_mock:
            parts.append("[yellow]MOCK[/yellow]")

        # Filter label (no "Filter:" prefix)
        parts.append(f"[b]{self._get_filter_display_label()}[/b]")

        # Compact transaction counts
        if hasattr(self, "_transactions") and self._transactions:
            total = self._transactions.total_count
            uncategorized = sum(1 for t in self._transactions.transactions if t.is_uncategorized)
            unapproved = sum(1 for t in self._transactions.transactions if t.is_unapproved)

            counts = [str(total)]
            if uncategorized:
                counts.append(f"{uncategorized} uncat")
            if unapproved:
                counts.append(f"{unapproved} new")
            parts.append(" / ".join(counts))

        return " │ ".join(parts)

    def compose(self) -> ComposeResult:
        """Compose the UI."""
        yield Static(self._build_header_text(), id="app-header")
        yield Container(
            Static("Loading transactions...", id="loading-indicator"),
            id="main-container",
        )
        yield Footer()

    async def on_mount(self) -> None:
        """Handle app mount - load initial data."""
        # Calculate initial column widths based on terminal size
        self._column_widths = calculate_column_widths(self.size.width)
        # Initialize budget info
        await self._init_budget()
        self.run_worker(self._load_transactions(), exclusive=True)

    def on_resize(self, event) -> None:
        """Handle terminal resize - recalculate column widths."""
        new_widths = calculate_column_widths(event.size.width)
        if new_widths != self._column_widths:
            self._column_widths = new_widths
            # Re-render transactions with new widths
            self.run_worker(self._render_transactions(), exclusive=True)

    async def _init_budget(self) -> None:
        """Initialize budget state from the YNAB client."""
        try:
            # Get current budget ID from YNAB client
            self._current_budget_id = self._categorizer.get_current_budget_id()

            # Find the budget name from available budgets
            budgets = self._categorizer.get_budgets()
            for budget in budgets:
                if budget["id"] == self._current_budget_id:
                    self._current_budget_name = budget["name"]
                    break

            if not self._current_budget_name:
                self._current_budget_name = "Unknown Budget"

            # Set the budget_id on the database for filtering
            self._categorizer.set_budget_id(self._current_budget_id)

            # Update header to show budget name
            self._update_header()
        except Exception as e:
            self._current_budget_name = f"Error: {e}"

    async def _load_transactions(self) -> None:
        """Load transactions from YNAB based on current filter."""
        # Clear existing content and show loading state
        container = self.query_one("#main-container")
        await container.remove_children()
        loading = Static("Loading transactions...", id="loading-indicator")
        await container.mount(loading)
        filter_label = self.FILTER_LABELS[self._filter_state.mode]
        loading.update(f"Fetching {filter_label.lower()} transactions...")

        # Calculate since_date based on load_since_months setting
        since_date = None
        if self._load_since_months is not None:
            since_date = datetime.now() - timedelta(days=self._load_since_months * 30)

        try:
            # Fetch transactions with current filter
            self._transactions = self._categorizer.get_transactions(
                filter_mode=self._filter_state.mode,
                since_date=since_date,
                category_id=self._filter_state.category.category_id
                if self._filter_state.category
                else None,
                payee_name=self._filter_state.payee,
            )

            # Update UI
            await self._render_transactions()

        except Exception as e:
            loading.update(f"Error: {e}")

    async def _render_transactions(self) -> None:
        """Render the transactions list."""
        container = self.query_one("#main-container")

        # Clear and rebuild content
        await container.remove_children()

        # Column header (separate from ListView)
        header_row = self._render_header_row()

        # Transaction list using ListView for efficient navigation
        items = [
            TransactionListItem(
                txn, self._tag_state, self._column_widths, self._color_status_letters
            )
            for txn in self._transactions.transactions
        ]
        txn_list = ListView(*items, id="transactions-list")

        # Status bar with filter stats and sync times (consolidated)
        status = Static(
            self._build_status_bar_text(),
            id="status-bar",
        )

        await container.mount(header_row, txn_list, status)

        # Focus ListView for keyboard navigation
        txn_list.focus()

    def _render_header_row(self) -> Static:
        """Render the header row with column names."""
        header = format_header_row(self._column_widths)
        return Static(header, classes="transaction-header")

    async def action_quit(self) -> None:
        """Handle quit action."""
        self.exit()

    def action_refresh(self) -> None:
        """Refresh transactions."""
        self.run_worker(self._load_transactions(), exclusive=True)

    def action_toggle_tag(self) -> None:
        """Toggle tag on the currently selected transaction for bulk actions."""
        txn = self._get_selected_transaction()
        if not txn:
            return

        # Update immutable tag state
        self._tag_state = TagManager.toggle(self._tag_state, txn.id)

        # Update visual display
        try:
            txn_list = self.query_one("#transactions-list", ListView)
            if txn_list.highlighted_child and isinstance(
                txn_list.highlighted_child, TransactionListItem
            ):
                txn_list.highlighted_child._tag_state = self._tag_state
                txn_list.highlighted_child.update_content()
        except NoMatches:
            pass  # Widget not mounted yet, safe to ignore

    def action_clear_all_tags(self) -> None:
        """Clear all tagged transactions."""
        if self._tag_state.is_empty:
            self.notify("No tagged transactions", severity="warning", timeout=2)
            return

        count = self._tag_state.count
        # Store IDs to update before clearing
        ids_to_update = self._tag_state.tagged_ids
        self._tag_state = TagManager.clear_all(self._tag_state)

        # Update only the affected rows (removes star indicators)
        try:
            txn_list = self.query_one("#transactions-list", ListView)
            for child in txn_list.children:
                if isinstance(child, TransactionListItem) and child.txn.id in ids_to_update:
                    child._tag_state = self._tag_state
                    child.update_content()
        except NoMatches:
            pass  # Widget not mounted yet, safe to ignore

        self.notify(f"Cleared {count} tag(s)", timeout=2)

    def _update_status_bar(self, text: str) -> None:
        """Update the status bar text."""
        try:
            status_bar = self.query_one("#status-bar", Static)
            status_bar.update(text)
        except Exception:
            pass  # Status bar might not exist yet

    def _restore_status_bar(self) -> None:
        """Restore the status bar to its normal content."""
        self._update_status_bar(self._build_status_bar_text())

    def action_cycle_filter(self) -> None:
        """Show filter menu in status bar and wait for sub-key."""
        # Cancel any existing timer
        if self._filter_timer is not None:
            self._filter_timer.stop()
            self._filter_timer = None

        # Enter filter submenu mode
        self._filter_state = FilterStateMachine.enter_submenu(self._filter_state)
        filter_text = (
            "[yellow]Filter:[/yellow] "
            "[cyan]a[/cyan]pproved "
            "[cyan]n[/cyan]ew "
            "[cyan]u[/cyan]ncat "
            "p[cyan]e[/cyan]nding "
            "[cyan]c[/cyan]ategory "
            "[cyan]p[/cyan]ayee "
            "[cyan]r[/cyan]eset"
        )
        self._update_status_bar(filter_text)

        # Set timer to cancel pending state after 3 seconds
        self._filter_timer = self.set_timer(3.0, self._cancel_filter_pending)

    def _cancel_filter_pending(self) -> None:
        """Cancel filter pending state after timeout."""
        self._filter_state = FilterStateMachine.cancel_submenu(self._filter_state)
        self._filter_timer = None
        self._restore_status_bar()

    def _apply_filter(self, filter_mode: str) -> None:
        """Apply a filter mode and reload transactions."""
        self._filter_state = FilterStateMachine.apply_mode(self._filter_state, filter_mode)
        if self._filter_timer is not None:
            self._filter_timer.stop()
            self._filter_timer = None
        self._restore_status_bar()
        self.notify(f"Filter: {self._get_filter_display_label()}", timeout=2)
        self.run_worker(self._load_transactions(), exclusive=True)

    def _get_filter_display_label(self) -> str:
        """Get the display label for current filter state including category/payee."""
        return FilterStateMachine.get_display_label(self._filter_state)

    def on_key(self, event) -> None:
        """Handle key events for filter sub-keys."""
        # Handle filter sub-keys
        if self._filter_state.is_submenu_active and event.key in self.FILTER_KEYS:
            event.stop()  # Stop event propagation
            event.prevent_default()  # Prevent action bindings from firing
            filter_action = self.FILTER_KEYS[event.key]
            # Special handling for category and payee filters (open modals)
            if filter_action == "category":
                self._cancel_filter_pending()
                self._open_category_filter()
            elif filter_action == "payee":
                self._cancel_filter_pending()
                self._open_payee_filter()
            else:
                self._apply_filter(filter_action)
        elif self._filter_state.is_submenu_active:
            # Any other key cancels filter mode
            self._cancel_filter_pending()

    def _get_selected_transaction(self) -> Optional[Transaction]:
        """Get the currently selected transaction from the list."""
        try:
            txn_list = self.query_one("#transactions-list", ListView)
            if txn_list.index is not None and txn_list.index < len(self._transactions.transactions):
                item = txn_list.highlighted_child
                if isinstance(item, TransactionListItem):
                    return item.txn
        except NoMatches:
            pass  # Widget not mounted yet, safe to ignore
        return None

    def _get_categories_for_picker(self) -> list[dict]:
        """Get categories formatted for the picker modal."""
        categories = []
        for group in self._categorizer.get_category_groups():
            for cat in group.categories:
                if not cat.hidden and not cat.deleted:
                    categories.append(
                        {
                            "id": cat.id,
                            "name": cat.name,
                            "group_name": group.name,
                        }
                    )
        return categories

    def action_categorize(self) -> None:
        """Open category picker modal - bulk mode if items tagged."""
        if not self._tag_state.is_empty:
            # Bulk mode - categorize all tagged transactions
            tagged_txns = TagManager.get_tagged_transactions(
                self._tag_state, self._transactions.transactions
            )
            if not tagged_txns:
                self._tag_state = TagManager.clear_all(self._tag_state)
                return

            # Show summary for bulk operation
            summary = TransactionSummary(
                date=f"{len(tagged_txns)} tagged",
                payee="[Bulk Categorize]",
                amount="",
                current_category=None,
                current_category_id=None,
                amazon_items=None,
            )
            categories = self._get_categories_for_picker()
            match_style = self._categorizer.get_search_match_style()
            modal = CategoryPickerModal(
                categories=categories,
                transaction=summary,
                match_style=match_style,
            )
            self.push_screen(modal, self._on_bulk_category_selected)
        else:
            # Single item mode
            txn = self._get_selected_transaction()
            if not txn:
                self.notify("No transaction selected", severity="warning")
                return

            # Build transaction summary for display in modal
            # Look up full category info to get group name
            current_category_display = None
            if txn.category_id:
                cat = self._categorizer.categories.find_by_id(txn.category_id)
                if cat:
                    current_category_display = f"[{cat.group_name}] {cat.name}"
                else:
                    current_category_display = txn.category_name

            summary = TransactionSummary(
                date=txn.display_date,
                payee=txn.payee_name,
                amount=txn.display_amount,
                current_category=current_category_display,
                current_category_id=txn.category_id if txn.category_id else None,
                amazon_items=txn.amazon_items if txn.is_amazon else None,
            )

            categories = self._get_categories_for_picker()
            match_style = self._categorizer.get_search_match_style()
            modal = CategoryPickerModal(
                categories=categories,
                transaction=summary,
                match_style=match_style,
            )
            self.push_screen(modal, self._on_category_selected)

    def _on_category_selected(self, result: Optional[CategorySelection]) -> None:
        """Handle category selection from modal."""
        if result is None:
            return  # Cancelled

        txn = self._get_selected_transaction()
        if not txn:
            return

        # Use action handler for categorization
        action_result = self._action_handler.categorize(
            txn, result.category_id, result.category_name
        )

        if action_result.success:
            self.notify(action_result.message)
        else:
            self.notify(action_result.error or "Failed to categorize", severity="error")
            return

        # Update just the selected item in the ListView (not full rebuild)
        try:
            txn_list = self.query_one("#transactions-list", ListView)
            if txn_list.highlighted_child:
                item = txn_list.highlighted_child
                if isinstance(item, TransactionListItem):
                    item.update_content()  # Update the Static widget's text
        except Exception:
            # Fallback to full re-render if something goes wrong
            self.run_worker(self._render_transactions(), exclusive=True)

    def _on_bulk_category_selected(self, result: Optional[CategorySelection]) -> None:
        """Handle category selection for bulk tagging."""
        if result is None:
            return  # Cancelled

        # Get tagged transactions
        tagged_txns = TagManager.get_tagged_transactions(
            self._tag_state, self._transactions.transactions
        )

        # Use action handler for bulk categorization
        action_result = self._action_handler.categorize_batch(
            tagged_txns, result.category_id, result.category_name
        )

        # Clear all tags
        self._tag_state = TagManager.clear_all(self._tag_state)

        # Refresh display
        self.run_worker(self._render_transactions(), exclusive=True)
        self.notify(action_result.message)

    def action_fuzzy_search(self) -> None:
        """Open fuzzy search modal for transactions."""
        transactions = self._transactions.transactions
        if not transactions:
            self.notify("No transactions to search", severity="warning")
            return
        match_style = self._categorizer.get_search_match_style()
        modal = TransactionSearchModal(
            transactions=transactions,
            match_style=match_style,
        )
        self.push_screen(modal, self._on_search_selected)

    def _on_search_selected(self, transaction_id: Optional[str]) -> None:
        """Navigate to selected transaction from search."""
        if transaction_id is None:
            return
        # Find index of transaction in current list and scroll to it
        txn_list = self.query_one("#transactions-list", ListView)
        for i, item in enumerate(txn_list.children):
            if isinstance(item, TransactionListItem) and item.txn.id == transaction_id:
                txn_list.index = i
                break

    def _open_category_filter(self) -> None:
        """Open the category filter modal."""
        categories = self._get_categories_for_picker()
        if not categories:
            self.notify("No categories available", severity="warning")
            return
        match_style = self._categorizer.get_search_match_style()
        modal = CategoryFilterModal(
            categories=categories,
            match_style=match_style,
        )
        self.push_screen(modal, self._on_category_filter_selected)

    def _on_category_filter_selected(self, result: Optional[CategoryFilterResult]) -> None:
        """Handle category filter selection."""
        if result is None:
            # Cancelled - clear category filter
            if self._filter_state.category:
                self._filter_state = FilterStateMachine.clear_category(self._filter_state)
                self.notify("Category filter cleared", timeout=2)
                self.run_worker(self._load_transactions(), exclusive=True)
            return
        # Convert modal result to our state type
        cat_filter = CategoryFilter(
            category_id=result.category_id,
            category_name=result.category_name,
        )
        self._filter_state = FilterStateMachine.set_category(self._filter_state, cat_filter)
        self.notify(f"Filtering by: {result.category_name}", timeout=2)
        self.run_worker(self._load_transactions(), exclusive=True)

    def _open_payee_filter(self) -> None:
        """Open the payee filter modal."""
        # Get unique payees from ALL transactions (not just currently filtered)
        # First load unfiltered to get all payees
        payees = get_unique_payees(self._transactions.transactions)
        if not payees:
            self.notify("No payees available", severity="warning")
            return
        match_style = self._categorizer.get_search_match_style()
        modal = PayeeFilterModal(
            payees=payees,
            match_style=match_style,
        )
        self.push_screen(modal, self._on_payee_filter_selected)

    def _on_payee_filter_selected(self, result: Optional[str]) -> None:
        """Handle payee filter selection."""
        if result is None:
            # Cancelled - clear payee filter
            if self._filter_state.payee:
                self._filter_state = FilterStateMachine.clear_payee(self._filter_state)
                self.notify("Payee filter cleared", timeout=2)
                self.run_worker(self._load_transactions(), exclusive=True)
            return
        self._filter_state = FilterStateMachine.set_payee(self._filter_state, result)
        self.notify(f"Filtering by payee: {result}", timeout=2)
        self.run_worker(self._load_transactions(), exclusive=True)

    def action_split(self) -> None:
        """Open split screen for Amazon transactions."""
        txn = self._get_selected_transaction()
        if not txn:
            self.notify("No transaction selected", severity="warning")
            return

        if not txn.is_amazon:
            self.notify("Split mode is only for Amazon transactions", severity="warning")
            return

        if not txn.amazon_order_id:
            self.notify("No Amazon order linked to this transaction", severity="warning")
            return

        # Get items with prices via service layer
        all_items_with_prices = self._categorizer.get_amazon_order_items_with_prices(
            txn.amazon_order_id
        )

        if not all_items_with_prices:
            self.notify("No items found for this order", severity="warning")
            return

        # For combo matches, filter to only items assigned to this transaction
        # txn.amazon_items contains the distributed items for this specific transaction
        if txn.amazon_items:
            assigned_item_names = set(txn.amazon_items)
            items_with_prices = [
                item
                for item in all_items_with_prices
                if item.get("item_name") in assigned_item_names
            ]
            # Fallback if filtering results in no items (shouldn't happen)
            if not items_with_prices:
                items_with_prices = all_items_with_prices
        else:
            items_with_prices = all_items_with_prices

        # Single item: open CategoryPickerModal directly (same as 'c')
        if len(items_with_prices) == 1:
            item = items_with_prices[0]
            summary = TransactionSummary(
                date=txn.display_date,
                payee=txn.payee_name,
                amount=txn.display_amount,
                current_category=txn.category_name if txn.category_name else None,
                current_category_id=txn.category_id if txn.category_id else None,
                amazon_items=[item.get("item_name", "Unknown")],
            )
            categories = self._get_categories_for_picker()
            match_style = self._categorizer.get_search_match_style()
            modal = CategoryPickerModal(
                categories=categories,
                transaction=summary,
                match_style=match_style,
            )
            self.push_screen(modal, self._on_category_selected)
            return

        # Multi-item: open ItemSplitScreen
        # Get existing pending splits if any (for re-editing)
        existing_splits = self._categorizer.get_pending_splits(txn.id)

        # If no pending splits but transaction is already split (synced to YNAB),
        # load categories from synced subtransactions
        if not existing_splits and txn.is_split:
            existing_splits = self._categorizer.get_synced_splits(txn.id)

        screen = ItemSplitScreen(
            categorizer=self._categorizer,
            transaction=txn,
            categories=self._get_categories_for_picker(),
            items_with_prices=items_with_prices,
            existing_splits=existing_splits,
        )
        self.push_screen(screen, self._on_split_completed)

    def _on_split_completed(self, result: Optional[bool]) -> None:
        """Handle split screen completion."""
        if not result:
            return  # Cancelled

        # Update the ListView item (same pattern as _on_category_selected)
        try:
            txn_list = self.query_one("#transactions-list", ListView)
            if txn_list.highlighted_child:
                item = txn_list.highlighted_child
                if isinstance(item, TransactionListItem):
                    item.update_content()
        except Exception:
            # Fallback to full re-render if something goes wrong
            self.run_worker(self._render_transactions(), exclusive=True)

    def action_undo(self) -> None:
        """Undo pending category change on selected transaction."""
        txn = self._get_selected_transaction()
        if not txn:
            self.notify("No transaction selected", severity="warning")
            return

        if txn.sync_status != "pending_push":
            self.notify("Transaction has no pending changes to undo", severity="warning")
            return

        # Use action handler for undo
        action_result = self._action_handler.undo(txn)

        if action_result.success:
            self.notify(action_result.message)
            # Update list item visually
            try:
                txn_list = self.query_one("#transactions-list", ListView)
                if txn_list.highlighted_child:
                    item = txn_list.highlighted_child
                    if isinstance(item, TransactionListItem):
                        item.update_content()
            except Exception:
                # Fallback to full re-render
                self.run_worker(self._render_transactions(), exclusive=True)
        else:
            self.notify(action_result.error or "Failed to undo", severity="error")

    def action_approve(self) -> None:
        """Approve transaction(s) - bulk mode if items tagged."""
        if not self._tag_state.is_empty:
            # Bulk approve all tagged transactions
            tagged_txns = TagManager.get_tagged_transactions(
                self._tag_state, self._transactions.transactions
            )

            # Use action handler for bulk approval
            action_result = self._action_handler.approve_batch(tagged_txns)

            # Clear all tags
            self._tag_state = TagManager.clear_all(self._tag_state)

            # Refresh display
            self.run_worker(self._render_transactions(), exclusive=True)
            self.notify(action_result.message)
        else:
            # Single item mode
            txn = self._get_selected_transaction()
            if not txn:
                self.notify("No transaction selected", severity="warning")
                return

            if txn.approved:
                # Already approved - no-op, silent
                return

            # Use action handler for approval
            action_result = self._action_handler.approve(txn)

            if action_result.success:
                self.notify(action_result.message)
                # Update the list item visually
                try:
                    txn_list = self.query_one("#transactions-list", ListView)
                    if txn_list.highlighted_child:
                        item = txn_list.highlighted_child
                        if isinstance(item, TransactionListItem):
                            item.update_content()
                except Exception:
                    # Fallback to full re-render
                    self.run_worker(self._render_transactions(), exclusive=True)
            else:
                self.notify(action_result.error or "Failed to approve", severity="error")

    def action_edit_memo(self) -> None:
        """Open memo edit modal for selected transaction."""
        txn = self._get_selected_transaction()
        if not txn:
            self.notify("No transaction selected", severity="warning")
            return

        from .modals import MemoEditModal, MemoTransactionInfo

        transaction_info = MemoTransactionInfo(
            date=txn.display_date,
            payee=txn.payee_name,
            amount=txn.display_amount,
            current_memo=txn.memo,
        )

        modal = MemoEditModal(transaction=transaction_info)
        self.push_screen(modal, self._on_memo_edited)

    def _on_memo_edited(self, result) -> None:
        """Handle memo edit completion."""
        if result is None or not result.changed:
            return  # Cancelled or no change

        txn = self._get_selected_transaction()
        if not txn:
            return

        # Use action handler for memo update
        action_result = self._action_handler.update_memo(txn, result.memo)

        if action_result.success:
            self.notify(action_result.message)
            # Update the list item visually
            try:
                txn_list = self.query_one("#transactions-list", ListView)
                if txn_list.highlighted_child:
                    item = txn_list.highlighted_child
                    if isinstance(item, TransactionListItem):
                        item.update_content()
            except Exception:
                self.run_worker(self._render_transactions(), exclusive=True)
        else:
            self.notify(action_result.error or "Failed to update memo", severity="error")

    def action_settings(self) -> None:
        """Show settings screen."""
        screen = SettingsScreen(config=self._categorizer.get_config())
        self.push_screen(screen)

    def action_switch_budget(self) -> None:
        """Open budget picker modal to switch budgets."""
        try:
            budgets = self._categorizer.get_budgets()
            if not budgets:
                self.notify("No budgets available", severity="warning")
                return

            if len(budgets) == 1:
                self.notify("Only one budget available", severity="information")
                return

            match_style = self._categorizer.get_search_match_style()
            modal = BudgetPickerModal(
                budgets=budgets,
                current_budget_id=self._current_budget_id,
                match_style=match_style,
            )
            self.push_screen(modal, self._on_budget_selected)
        except Exception as e:
            self.notify(f"Error loading budgets: {e}", severity="error")

    def _on_budget_selected(self, result: Optional[BudgetSelection]) -> None:
        """Handle budget selection from picker modal."""
        if result is None:
            return  # Cancelled

        if result.budget_id == self._current_budget_id:
            self.notify("Already on this budget", severity="information")
            return

        # Update state
        self._current_budget_id = result.budget_id
        self._current_budget_name = result.budget_name

        # Update categorizer (YNAB client + database)
        self._categorizer.set_budget_id(result.budget_id)

        # Clear local state
        self._tag_state = TagManager.clear_all(self._tag_state)
        self._filter_state = FilterStateMachine.reset(self._filter_state)

        # Update header and reload transactions
        self._update_header()
        self.notify(f"Switched to: {result.budget_name}")
        self.run_worker(self._load_transactions(), exclusive=True)

    def action_push_preview(self) -> None:
        """Show push preview screen with pending changes."""
        pending = self._categorizer.get_pending_changes()
        if not pending:
            self.notify("No pending changes to push", severity="warning")
            return
        screen = PushPreviewScreen(categorizer=self._categorizer, changes=pending)
        self.push_screen(screen)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle Enter key on ListView - open category picker modal."""
        # Same as pressing 'c' - open category picker for selected transaction
        self.action_categorize()

    def action_show_help(self) -> None:
        """Show help screen."""
        self.push_screen(HelpScreen())
