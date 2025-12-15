"""Main TUI application for YNAB Categorizer.

Built with Textual for a modern terminal UI experience.
"""

import subprocess
from datetime import datetime, timedelta
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.widgets import Footer, ListItem, ListView, Static

from ..models import Transaction, TransactionBatch
from ..services import CategorizerService
from .constants import VIM_NAVIGATION_BINDINGS
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
from .screens import ItemSplitScreen, PushPreviewScreen, SettingsScreen


def _get_git_version() -> str:
    """Get short git hash if in a git repo."""
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _format_sync_time(timestamp: Optional[datetime]) -> str:
    """Format sync timestamp as absolute time."""
    if timestamp is None:
        return "Never"
    return timestamp.strftime("%Y-%m-%d %H:%M")


class TransactionListItem(ListItem):
    """A list item displaying a transaction row."""

    def __init__(
        self,
        txn: Transaction,
        tagged_ids: set[str] | None = None,
    ) -> None:
        """Initialize with a transaction.

        Args:
            txn: The transaction to display.
            tagged_ids: Reference to set of tagged transaction IDs for bulk actions.
        """
        super().__init__()
        self.txn = txn
        self._tagged_ids = tagged_ids if tagged_ids is not None else set()

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

        # Format date (10 chars)
        date_str = txn.display_date

        # Tag indicator (green star) - 2 chars
        tag = "[green]★[/green] " if txn.id in self._tagged_ids else "  "

        # Format payee with Amazon indicator (20 chars total: 2 for tag + 2 for amazon + 18 for name)
        payee = txn.payee_name[:18].ljust(18)
        if txn.is_amazon:
            payee = f"[yellow]*[/yellow] {payee}"
        else:
            payee = f"  {payee}"  # Align with Amazon indicator
        payee = f"{tag}{payee}"

        # Format amount (12 chars, right-aligned)
        amount = txn.display_amount.rjust(12)

        # Format category (20 chars)
        if txn.is_transfer:
            # Show transfer target account
            target = txn.transfer_account_name or "Transfer"
            transfer_text = f"-> {target}"[:20]
            category = f"[cyan]{transfer_text:<20}[/cyan]"
        elif txn.is_balance_adjustment:
            # Show descriptive label for balance adjustments
            # Note: Use parentheses, not brackets - Rich interprets [] as markup
            category = f"[dim]{'(Balance Adj)':<20}[/dim]"
        elif txn.category_name:
            category = txn.category_name[:20].ljust(20)
        else:
            category = " " * 20

        # Format account (16 chars)
        account = (txn.account_name or "")[:16].ljust(16)

        # Format status (6 chars)
        status_flags = ""
        if txn.approved:
            status_flags += "A"
        if txn.cleared == "cleared":
            status_flags += "C"
        elif txn.cleared == "reconciled":
            status_flags += "R"
        if txn.sync_status == "pending_push":
            status_flags += "P"
        elif txn.sync_status == "conflict":
            status_flags += "!"
        status = status_flags.ljust(6)

        # Format enrichment on second line(s) - only show Amazon items
        enrichment = ""
        if txn.is_amazon and txn.amazon_items:
            # Show all items on separate lines
            lines = [f"{'':>12}[dim]↳ {item[:60]}[/dim]" for item in txn.amazon_items]
            enrichment = "\n" + "\n".join(lines)

        return f"{date_str}  {payee}  {amount}  {category}  {account}  {status}{enrichment}"


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

    #header-stats {
        dock: top;
        height: 3;
        background: $primary-background;
        padding: 0 1;
    }

    .stat-box {
        width: 1fr;
        height: 100%;
        content-align: center middle;
        text-align: center;
    }

    .stat-value {
        text-style: bold;
        color: $text;
    }

    .stat-label {
        color: $text-muted;
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
        # Categorization
        Binding("c", "categorize", "Categorize"),
        Binding("x", "split", "Split"),
        Binding("a", "approve", "Approve"),
        Binding("u", "undo", "Undo"),
        Binding("p", "push_preview", "Push"),
        # Other actions
        Binding("q", "quit", "Quit"),
        Binding("escape", "quit", "Quit", show=False),
        Binding("s", "settings", "Settings"),
        Binding("b", "switch_budget", "Budget"),
        Binding("f", "cycle_filter", "Filter"),
        Binding("/", "fuzzy_search", "Search"),
        Binding("t", "toggle_tag", "Tag"),
        Binding("T", "clear_all_tags", "Untag All", show=False),
        Binding("f5", "refresh", "Refresh"),
        Binding("?", "show_help", "Help"),
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
        "e": "pending",  # Changed from 'p' to free up for payee
        "x": "all",
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
        self._is_mock = is_mock
        self._load_since_months = load_since_months
        self._git_version = _get_git_version()
        self._transactions: TransactionBatch = TransactionBatch()
        self._filter_mode: str = "all"  # Current filter
        self._filter_pending: bool = False  # Waiting for filter sub-key
        self._filter_timer: Optional[object] = None  # Timer to cancel pending state
        # Category and payee filters (combined with filter_mode)
        self._category_filter: Optional[CategoryFilterResult] = None
        self._payee_filter: Optional[str] = None
        # Tagged transactions for bulk actions (in-memory only)
        self._tagged_ids: set[str] = set()
        # Budget state - will be populated on mount
        self._current_budget_id: Optional[str] = None
        self._current_budget_name: Optional[str] = None

    def _get_list_view(self) -> ListView | None:
        """Get the transactions ListView if it exists."""
        try:
            return self.query_one("#transactions-list", ListView)
        except Exception:
            return None

    def _build_header_text(self) -> str:
        """Build the header text with program name, version, mode, and budget."""
        mode_indicator = "[yellow][MOCK][/yellow]" if self._is_mock else "[green][PROD][/green]"
        budget_name = self._current_budget_name or "Loading..."
        return f"YNAB TUI v{self._git_version} {mode_indicator} | [cyan]{budget_name}[/cyan]"

    def _update_header(self) -> None:
        """Update the header text with current budget name."""
        try:
            header = self.query_one("#app-header", Static)
            header.update(self._build_header_text())
        except Exception:
            pass  # Header might not be mounted yet

    def _build_status_bar_text(self) -> str:
        """Build the status bar text with sync times and mode."""
        # PROD/MOCK indicator
        db_indicator = "[yellow]MOCK[/yellow]" if self._is_mock else "[green]PROD[/green]"

        # Get sync times via service layer (not direct DB access)
        sync_status = self._categorizer.get_sync_status()
        ynab_sync = sync_status["ynab"]
        amazon_sync = sync_status["amazon"]

        ynab_time = _format_sync_time(ynab_sync.get("last_sync_at") if ynab_sync else None)
        amazon_time = _format_sync_time(amazon_sync.get("last_sync_at") if amazon_sync else None)

        return f"{db_indicator} | YNAB: {ynab_time} | Amazon: {amazon_time} | [b]?[/b] Help"

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
        # Initialize budget info
        await self._init_budget()
        self.run_worker(self._load_transactions())

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
        filter_label = self.FILTER_LABELS[self._filter_mode]
        loading.update(f"Fetching {filter_label.lower()} transactions...")

        # Calculate since_date based on load_since_months setting
        since_date = None
        if self._load_since_months is not None:
            since_date = datetime.now() - timedelta(days=self._load_since_months * 30)

        try:
            # Fetch transactions with current filter
            self._transactions = self._categorizer.get_transactions(
                filter_mode=self._filter_mode,
                since_date=since_date,
                category_id=self._category_filter.category_id if self._category_filter else None,
                payee_name=self._payee_filter,
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

        # Stats header - show filter and counts
        filter_label = self._get_filter_display_label()
        # Count uncategorized in current view
        uncategorized_count = sum(1 for t in self._transactions.transactions if t.is_uncategorized)
        stats = Horizontal(
            Static(
                f"[b]{filter_label}[/b]\nFilter (f)",
                classes="stat-box",
            ),
            Static(
                f"[b]{self._transactions.total_count}[/b]\nShowing",
                classes="stat-box",
            ),
            Static(
                f"[b]{uncategorized_count}[/b]\nUncategorized",
                classes="stat-box",
            ),
            Static(
                f"[b]{self._transactions.amazon_count}[/b]\nAmazon",
                classes="stat-box",
            ),
            id="header-stats",
        )

        # Column header (separate from ListView)
        header_row = self._render_header_row()

        # Transaction list using ListView for efficient navigation
        items = [
            TransactionListItem(txn, self._tagged_ids) for txn in self._transactions.transactions
        ]
        txn_list = ListView(*items, id="transactions-list")

        # Status bar with DB path and sync times
        status = Static(
            self._build_status_bar_text(),
            id="status-bar",
        )

        await container.mount(stats, header_row, txn_list, status)

        # Focus ListView for keyboard navigation
        txn_list.focus()

    def _render_header_row(self) -> Static:
        """Render the header row with column names."""
        # Column widths: date(10) payee(22) amount(12) category(20) account(16) status(6)
        header = (
            f"{'Date':<10}  "
            f"{'Payee':<22}  "
            f"{'Amount':>12}  "
            f"{'Category':<20}  "
            f"{'Account':<16}  "
            f"{'Status':<6}"
        )
        return Static(header, classes="transaction-header")

    def action_quit(self) -> None:
        """Handle quit action."""
        self.exit()

    def action_refresh(self) -> None:
        """Refresh transactions."""
        self.run_worker(self._load_transactions())

    def action_toggle_tag(self) -> None:
        """Toggle tag on the currently selected transaction for bulk actions."""
        txn = self._get_selected_transaction()
        if not txn:
            return

        if txn.id in self._tagged_ids:
            self._tagged_ids.discard(txn.id)
        else:
            self._tagged_ids.add(txn.id)

        # Update visual display
        try:
            txn_list = self.query_one("#transactions-list", ListView)
            if txn_list.highlighted_child and isinstance(
                txn_list.highlighted_child, TransactionListItem
            ):
                txn_list.highlighted_child.update_content()
        except Exception:
            pass

    def action_clear_all_tags(self) -> None:
        """Clear all tagged transactions."""
        if not self._tagged_ids:
            self.notify("No tagged transactions", severity="warning", timeout=2)
            return

        count = len(self._tagged_ids)
        # Store IDs to update before clearing
        ids_to_update = set(self._tagged_ids)
        self._tagged_ids.clear()

        # Update only the affected rows (removes star indicators)
        try:
            txn_list = self.query_one("#transactions-list", ListView)
            for child in txn_list.children:
                if isinstance(child, TransactionListItem) and child.txn.id in ids_to_update:
                    child.update_content()
        except Exception:
            pass

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

        # Show filter options in status bar with countdown hint
        self._filter_pending = True
        filter_text = (
            "[bold yellow]Filter (press key within 3s):[/bold yellow] "
            "[bold cyan]a[/bold cyan]=Approved  "
            "[bold cyan]n[/bold cyan]=New  "
            "[bold cyan]u[/bold cyan]=Uncategorized  "
            "[bold cyan]e[/bold cyan]=Pending  "
            "[bold cyan]c[/bold cyan]=Category  "
            "[bold cyan]p[/bold cyan]=Payee  "
            "[bold cyan]x[/bold cyan]=All"
        )
        self._update_status_bar(filter_text)

        # Set timer to cancel pending state after 3 seconds
        self._filter_timer = self.set_timer(3.0, self._cancel_filter_pending)

    def _cancel_filter_pending(self) -> None:
        """Cancel filter pending state after timeout."""
        self._filter_pending = False
        self._filter_timer = None
        self._restore_status_bar()

    def _apply_filter(self, filter_mode: str) -> None:
        """Apply a filter mode and reload transactions."""
        self._filter_mode = filter_mode
        self._filter_pending = False
        if self._filter_timer is not None:
            self._filter_timer.stop()
            self._filter_timer = None
        # Clear category and payee filters when selecting "all"
        if filter_mode == "all":
            self._category_filter = None
            self._payee_filter = None
        self._restore_status_bar()
        self.notify(f"Filter: {self._get_filter_display_label()}", timeout=2)
        self.run_worker(self._load_transactions())

    def _get_filter_display_label(self) -> str:
        """Get the display label for current filter state including category/payee."""
        parts = [self.FILTER_LABELS[self._filter_mode]]

        if self._category_filter:
            # Truncate long category names
            cat_name = self._category_filter.category_name
            if len(cat_name) > 15:
                cat_name = cat_name[:12] + "..."
            parts.append(f"Cat:{cat_name}")

        if self._payee_filter:
            # Truncate long payee names
            payee = self._payee_filter
            if len(payee) > 15:
                payee = payee[:12] + "..."
            parts.append(f"Payee:{payee}")

        return " + ".join(parts)

    def on_key(self, event) -> None:
        """Handle key events for filter sub-keys."""
        # Handle filter sub-keys
        if self._filter_pending and event.key in self.FILTER_KEYS:
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
        elif self._filter_pending:
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
        except Exception:
            pass
        return None

    def _get_categories_for_picker(self) -> list[dict]:
        """Get categories formatted for the picker modal."""
        categories = []
        for group in self._categorizer.categories.groups:
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
        if self._tagged_ids:
            # Bulk mode - categorize all tagged transactions
            tagged_txns = [t for t in self._transactions.transactions if t.id in self._tagged_ids]
            if not tagged_txns:
                self._tagged_ids.clear()
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
            modal = CategoryPickerModal(categories=categories, transaction=summary)
            self.push_screen(modal, self._on_bulk_category_selected)
        else:
            # Single item mode
            txn = self._get_selected_transaction()
            if not txn:
                self.notify("No transaction selected", severity="warning")
                return

            # Build transaction summary for display in modal
            summary = TransactionSummary(
                date=txn.display_date,
                payee=txn.payee_name,
                amount=txn.display_amount,
                current_category=txn.category_name if txn.category_name else None,
                current_category_id=txn.category_id if txn.category_id else None,
                amazon_items=txn.amazon_items if txn.is_amazon else None,
            )

            categories = self._get_categories_for_picker()
            modal = CategoryPickerModal(categories=categories, transaction=summary)
            self.push_screen(modal, self._on_category_selected)

    def _on_category_selected(self, result: Optional[CategorySelection]) -> None:
        """Handle category selection from modal."""
        if result is None:
            return  # Cancelled

        txn = self._get_selected_transaction()
        if not txn:
            return

        # Apply the category to DB
        self._categorizer.apply_category(
            transaction=txn,
            category_id=result.category_id,
            category_name=result.category_name,
        )

        # Update the transaction object in memory (avoids full DB reload)
        txn.category_id = result.category_id
        txn.category_name = result.category_name
        txn.sync_status = "pending_push"

        self.notify(f"Categorized as: {result.category_name}")

        # Update just the selected item in the ListView (not full rebuild)
        try:
            txn_list = self.query_one("#transactions-list", ListView)
            if txn_list.highlighted_child:
                item = txn_list.highlighted_child
                if isinstance(item, TransactionListItem):
                    item.update_content()  # Update the Static widget's text
        except Exception:
            # Fallback to full re-render if something goes wrong
            self.run_worker(self._render_transactions())

    def _on_bulk_category_selected(self, result: Optional[CategorySelection]) -> None:
        """Handle category selection for bulk tagging."""
        if result is None:
            return  # Cancelled

        count = 0
        for txn_id in list(self._tagged_ids):
            txn = next((t for t in self._transactions.transactions if t.id == txn_id), None)
            if txn:
                self._categorizer.apply_category(
                    transaction=txn,
                    category_id=result.category_id,
                    category_name=result.category_name,
                )
                txn.category_id = result.category_id
                txn.category_name = result.category_name
                txn.sync_status = "pending_push"
                count += 1

        # Clear all tags
        self._tagged_ids.clear()

        # Refresh display
        self.run_worker(self._render_transactions())
        self.notify(f"Categorized {count} transactions as: {result.category_name}")

    def action_fuzzy_search(self) -> None:
        """Open fuzzy search modal for transactions."""
        transactions = self._transactions.transactions
        if not transactions:
            self.notify("No transactions to search", severity="warning")
            return
        modal = TransactionSearchModal(transactions=transactions)
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
        modal = CategoryFilterModal(categories=categories)
        self.push_screen(modal, self._on_category_filter_selected)

    def _on_category_filter_selected(self, result: Optional[CategoryFilterResult]) -> None:
        """Handle category filter selection."""
        if result is None:
            # Cancelled - clear category filter
            if self._category_filter:
                self._category_filter = None
                self.notify("Category filter cleared", timeout=2)
                self.run_worker(self._load_transactions())
            return
        self._category_filter = result
        self.notify(f"Filtering by: {result.category_name}", timeout=2)
        self.run_worker(self._load_transactions())

    def _open_payee_filter(self) -> None:
        """Open the payee filter modal."""
        # Get unique payees from ALL transactions (not just currently filtered)
        # First load unfiltered to get all payees
        payees = get_unique_payees(self._transactions.transactions)
        if not payees:
            self.notify("No payees available", severity="warning")
            return
        modal = PayeeFilterModal(payees=payees)
        self.push_screen(modal, self._on_payee_filter_selected)

    def _on_payee_filter_selected(self, result: Optional[str]) -> None:
        """Handle payee filter selection."""
        if result is None:
            # Cancelled - clear payee filter
            if self._payee_filter:
                self._payee_filter = None
                self.notify("Payee filter cleared", timeout=2)
                self.run_worker(self._load_transactions())
            return
        self._payee_filter = result
        self.notify(f"Filtering by payee: {result}", timeout=2)
        self.run_worker(self._load_transactions())

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
            modal = CategoryPickerModal(categories=categories, transaction=summary)
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
            self.run_worker(self._render_transactions())

    def action_undo(self) -> None:
        """Undo pending category change on selected transaction."""
        txn = self._get_selected_transaction()
        if not txn:
            self.notify("No transaction selected", severity="warning")
            return

        if txn.sync_status != "pending_push":
            self.notify("Transaction has no pending changes to undo", severity="warning")
            return

        try:
            # Call service to undo
            self._categorizer.undo_category(txn)

            # Build message based on restored state
            restored_cat = txn.category_name or "Uncategorized"
            self.notify(f"Undone: restored to '{restored_cat}'")

            # Update list item visually
            try:
                txn_list = self.query_one("#transactions-list", ListView)
                if txn_list.highlighted_child:
                    item = txn_list.highlighted_child
                    if isinstance(item, TransactionListItem):
                        item.update_content()
            except Exception:
                # Fallback to full re-render
                self.run_worker(self._render_transactions())

        except ValueError as e:
            self.notify(str(e), severity="error")

    def action_approve(self) -> None:
        """Approve transaction(s) - bulk mode if items tagged."""
        if self._tagged_ids:
            # Bulk approve all tagged transactions
            count = 0
            for txn_id in list(self._tagged_ids):
                txn = next((t for t in self._transactions.transactions if t.id == txn_id), None)
                if txn and not txn.approved:
                    self._categorizer.approve_transaction(txn)
                    count += 1

            # Clear all tags
            self._tagged_ids.clear()

            # Refresh display
            self.run_worker(self._render_transactions())
            if count > 0:
                self.notify(f"Approved {count} transactions")
            else:
                self.notify("All tagged transactions were already approved", severity="warning")
        else:
            # Single item mode
            txn = self._get_selected_transaction()
            if not txn:
                self.notify("No transaction selected", severity="warning")
                return

            if txn.approved:
                # Already approved - no-op, silent
                return

            # Approve the transaction
            self._categorizer.approve_transaction(txn)
            self.notify("Transaction approved")

            # Update the list item visually
            try:
                txn_list = self.query_one("#transactions-list", ListView)
                if txn_list.highlighted_child:
                    item = txn_list.highlighted_child
                    if isinstance(item, TransactionListItem):
                        item.update_content()
            except Exception:
                # Fallback to full re-render
                self.run_worker(self._render_transactions())

    def action_settings(self) -> None:
        """Show settings screen."""
        screen = SettingsScreen(config=self._categorizer._config)
        self.push_screen(screen)

    def action_switch_budget(self) -> None:
        """Open budget picker modal to switch budgets."""
        try:
            budgets = self._categorizer.get_budgets()
            if not budgets:
                self.notify("No budgets available", severity="warning")
                return

            if len(budgets) == 1:
                self.notify("Only one budget available", severity="info")
                return

            modal = BudgetPickerModal(
                budgets=budgets,
                current_budget_id=self._current_budget_id,
            )
            self.push_screen(modal, self._on_budget_selected)
        except Exception as e:
            self.notify(f"Error loading budgets: {e}", severity="error")

    def _on_budget_selected(self, result: Optional[BudgetSelection]) -> None:
        """Handle budget selection from picker modal."""
        if result is None:
            return  # Cancelled

        if result.budget_id == self._current_budget_id:
            self.notify("Already on this budget", severity="info")
            return

        # Update state
        self._current_budget_id = result.budget_id
        self._current_budget_name = result.budget_name

        # Update categorizer (YNAB client + database)
        self._categorizer.set_budget_id(result.budget_id)

        # Clear local state
        self._tagged_ids.clear()
        self._category_filter = None
        self._payee_filter = None
        self._filter_mode = "all"

        # Update header and reload transactions
        self._update_header()
        self.notify(f"Switched to: {result.budget_name}")
        self.run_worker(self._load_transactions())

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
        # Clear any existing notifications first to prevent stacking
        self.clear_notifications()
        help_text = """
[b]Vim-style Navigation:[/b]
  j/↓     Move down
  k/↑     Move up
  g       Go to top
  G       Go to bottom
  Ctrl+d  Half page down
  Ctrl+u  Half page up
  Ctrl+f  Full page down
  Ctrl+b  Full page up

[b]Tagging & Bulk Actions:[/b]
  t       Tag/untag transaction (★ green star)
  c/Enter Categorize (bulk if tagged)
  a       Approve (bulk if tagged)

[b]Categorization:[/b]
  x       Split mode (Amazon multi-item)
  u       Undo pending change (revert to original)

[b]Other Actions:[/b]
  f       Filter menu (then press a/n/u/p/x)
  T       Untag all tagged transactions
  s       Settings
  F5      Refresh
  q       Quit

[b]Filter Shortcuts (after pressing f):[/b]
  fa      Approved transactions
  fn      New (unapproved) transactions
  fu      Uncategorized transactions
  fp      Pending push to YNAB
  fx      All transactions

[b]Status Column Legend:[/b]
  A       Approved
  C       Cleared
  R       Reconciled
  P       Pending push to YNAB
  !       Sync conflict
"""
        self.notify(help_text, title="Help", timeout=15)
