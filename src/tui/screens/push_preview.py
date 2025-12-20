"""Push preview screen for reviewing and pushing pending changes to YNAB."""

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widgets import Footer, Header, ListItem, ListView, ProgressBar, Static
from textual.worker import Worker, WorkerState

from ...services.sync import SyncService
from ..constants import VIM_NAVIGATION_BINDINGS
from ..mixins import ListViewNavigationMixin

if TYPE_CHECKING:
    from ...services import CategorizerService


class PushChangeItem(ListItem):
    """A list item displaying a pending change row."""

    def __init__(self, change: dict) -> None:
        """Initialize with a pending change dict.

        Args:
            change: Dict from get_all_pending_changes() with transaction details.
        """
        super().__init__()
        self.change = change

    def compose(self) -> ComposeResult:
        """Compose the list item content."""
        yield Static(self._format_row())

    def _format_row(self) -> str:
        """Format the pending change as a row string."""
        change = self.change

        # Format date (10 chars)
        date_str = str(change.get("date", ""))[:10]

        # Format payee (30 chars)
        payee = (change.get("payee_name") or "Unknown")[:28].ljust(28)

        # Format amount (12 chars, right-aligned)
        amount = change.get("amount", 0)
        amount_str = f"${abs(amount):.2f}".rjust(10)

        # Format change description
        change_type = change.get("change_type", "category")
        old_cat = change.get("original_category_name") or "Uncategorized"
        new_cat = change.get("new_category_name") or "Uncategorized"

        if change_type == "split":
            # For splits, show simple indicator
            change_desc = "[cyan]-> Split[/cyan]"
        else:
            # Category change: old -> new
            if old_cat == new_cat:
                change_desc = f"{new_cat[:20]}"
            else:
                change_desc = f"{old_cat[:15]} -> {new_cat[:15]}"

        # Format approval change (+A or -A)
        approval_change = ""
        new_approved = change.get("new_approved")
        original_approved = change.get("original_approved") or change.get("approved")

        if new_approved is not None:
            if new_approved and not original_approved:
                approval_change = " [green]+A[/green]"
            elif not new_approved and original_approved:
                approval_change = " [red]-A[/red]"

        return f"{date_str}  {payee}  {amount_str}  {change_desc}{approval_change}"


class PushPreviewScreen(ListViewNavigationMixin, Screen):
    """Screen for previewing and pushing pending changes to YNAB."""

    CSS = """
    PushPreviewScreen {
        background: $surface;
    }

    #push-container {
        width: 100%;
        height: 100%;
        padding: 1;
    }

    #header-label {
        height: auto;
        padding: 1;
        text-style: bold;
        border: solid $primary;
        margin-bottom: 1;
    }

    #changes-list {
        height: 1fr;
        border: solid $warning;
    }

    PushChangeItem {
        height: auto;
        padding: 0 1;
        background: $surface;
    }

    PushChangeItem:hover {
        background: $primary-background;
    }

    PushChangeItem.-highlight {
        background: $primary;
    }

    #confirmation-bar {
        dock: bottom;
        height: 3;
        padding: 0 1;
        background: $warning-darken-2;
        content-align: center middle;
    }

    #confirmation-bar.--hidden {
        display: none;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: $primary-background;
        padding: 0 1;
    }

    #progress-container {
        dock: bottom;
        height: 3;
        padding: 0 1;
        background: $surface;
    }

    #progress-container.--hidden {
        display: none;
    }

    #progress-label {
        width: auto;
        padding-right: 1;
        content-align: center middle;
    }

    ProgressBar {
        width: 1fr;
    }
    """

    BINDINGS = [
        Binding("p", "confirm_push", "Push"),
        Binding("q", "cancel", "Cancel"),
        Binding("y", "do_push", "Confirm", show=False),
        Binding("n", "cancel_confirm", "Cancel", show=False),
        Binding("escape", "cancel_confirm", "Cancel", show=False),
        # Vim-style navigation
        *VIM_NAVIGATION_BINDINGS,
    ]

    def __init__(
        self,
        categorizer: "CategorizerService",
        changes: list[dict],
        **kwargs,
    ) -> None:
        """Initialize the push preview screen.

        Args:
            categorizer: Categorizer service for push operations.
            changes: List of pending change dicts from get_all_pending_changes().
        """
        super().__init__(**kwargs)
        self._categorizer = categorizer
        self._changes = changes
        self._confirming = False
        self._pushing = False

    def compose(self) -> ComposeResult:
        """Compose the screen."""
        yield Header()
        yield Container(
            Static(
                f"[b]Pending Changes ({len(self._changes)})[/b]\n"
                "[dim]Press 'p' to push, 'q' to cancel[/dim]",
                id="header-label",
            ),
            ListView(
                *[PushChangeItem(change) for change in self._changes],
                id="changes-list",
            ),
            Static("", id="status-bar"),
            id="push-container",
        )
        yield Horizontal(
            Static("Pushing 0/0", id="progress-label"),
            ProgressBar(total=100, show_eta=False, id="progress-bar"),
            id="progress-container",
            classes="--hidden",
        )
        yield Static(
            f"[b]Push {len(self._changes)} changes to YNAB? (y/n)[/b]",
            id="confirmation-bar",
            classes="--hidden",
        )
        yield Footer()

    def _get_list_view(self) -> ListView | None:
        """Get the changes ListView if it exists."""
        try:
            return self.query_one("#changes-list", ListView)
        except Exception:
            return None

    def action_confirm_push(self) -> None:
        """Show confirmation prompt."""
        if self._pushing:
            return

        self._confirming = True
        confirmation_bar = self.query_one("#confirmation-bar")
        confirmation_bar.remove_class("--hidden")
        self._update_status("Press 'y' to confirm push, 'n' to cancel")

    def action_cancel_confirm(self) -> None:
        """Cancel the confirmation, or exit screen if not confirming."""
        if not self._confirming:
            self.action_cancel()
            return

        self._confirming = False
        confirmation_bar = self.query_one("#confirmation-bar")
        confirmation_bar.add_class("--hidden")
        self._update_status("")

    def action_do_push(self) -> None:
        """Execute the push to YNAB."""
        if not self._confirming or self._pushing:
            return

        self._pushing = True
        self._confirming = False
        confirmation_bar = self.query_one("#confirmation-bar")
        confirmation_bar.add_class("--hidden")
        self._update_status("")
        self._show_progress_bar()

        # Run push in background worker (thread=True for sync function)
        self.run_worker(self._execute_push, exclusive=True, thread=True)

    def _execute_push(self) -> dict:
        """Execute the push operation (runs in worker thread)."""

        def on_progress(current: int, total: int) -> None:
            """Progress callback that updates the UI from the worker thread."""
            self.app.call_from_thread(self._update_progress, current, total)

        # Create SyncService using categorizer's components
        sync_service = SyncService(
            db=self._categorizer._db,
            ynab=self._categorizer._ynab,
            amazon=None,  # Not needed for push
        )
        result = sync_service.push_ynab(dry_run=False, progress_callback=on_progress)
        return {
            "succeeded": result.succeeded,
            "failed": result.failed,
            "errors": result.errors,
        }

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle worker state changes."""
        if event.state == WorkerState.SUCCESS:
            self._hide_progress_bar()
            result = event.worker.result
            if result is None:
                return
            if result["failed"] == 0:
                self.notify(
                    f"Pushed {result['succeeded']} changes to YNAB",
                    severity="information",
                )
            else:
                self.notify(
                    f"Pushed {result['succeeded']}, failed {result['failed']}",
                    severity="warning",
                )
                # Show all errors so users can see what failed
                for error in result["errors"]:
                    self.notify(error, severity="error", timeout=10)

            # Pop screen first
            self.app.pop_screen()

            # Reload transactions to apply current filter (removes pushed items from view)
            self.app.run_worker(self.app._load_transactions())  # type: ignore[attr-defined]

        elif event.state == WorkerState.ERROR:
            self._hide_progress_bar()
            self.notify(f"Push failed: {event.worker.error}", severity="error")
            self._pushing = False
            self._update_status("Push failed - press 'p' to retry or 'q' to cancel")

    def action_cancel(self) -> None:
        """Cancel and close the screen."""
        if self._pushing:
            self.notify("Cannot cancel while pushing", severity="warning")
            return
        self.app.pop_screen()

    def _update_status(self, message: str) -> None:
        """Update the status bar message."""
        try:
            status_bar = self.query_one("#status-bar", Static)
            status_bar.update(message)
        except NoMatches:
            pass  # Widget not mounted yet, safe to ignore

    def _update_progress(self, current: int, total: int) -> None:
        """Update the progress bar.

        Args:
            current: Current item number (1-indexed).
            total: Total number of items.
        """
        try:
            progress_label = self.query_one("#progress-label", Static)
            progress_label.update(f"Pushing {current}/{total}")

            progress_bar = self.query_one("#progress-bar", ProgressBar)
            progress_bar.update(total=total, progress=current)
        except NoMatches:
            pass  # Widgets not mounted yet, safe to ignore

    def _show_progress_bar(self) -> None:
        """Show the progress bar container."""
        try:
            container = self.query_one("#progress-container")
            container.remove_class("--hidden")
        except NoMatches:
            pass  # Widget not mounted yet, safe to ignore

    def _hide_progress_bar(self) -> None:
        """Hide the progress bar container."""
        try:
            container = self.query_one("#progress-container")
            container.add_class("--hidden")
        except NoMatches:
            pass  # Widget not mounted yet, safe to ignore
