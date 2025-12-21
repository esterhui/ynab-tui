"""Memo edit modal for viewing and editing transaction memos."""

from dataclasses import dataclass
from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static


@dataclass
class MemoEditResult:
    """Result of memo editing."""

    memo: str
    changed: bool


@dataclass
class TransactionInfo:
    """Transaction info to display in modal."""

    date: str
    payee: str
    amount: str
    current_memo: Optional[str] = None


class MemoEditModal(ModalScreen[Optional[MemoEditResult]]):
    """Modal for viewing and editing transaction memos.

    Shows current memo (if any) and allows editing.
    Returns MemoEditResult on save, None on cancel.
    """

    DEFAULT_CSS = """
    MemoEditModal {
        align: center middle;
    }

    MemoEditModal > #memo-container {
        width: 70;
        height: auto;
        max-height: 20;
        background: $surface;
        border: thick $primary;
        padding: 1;
    }

    MemoEditModal > #memo-container > #txn-info {
        height: auto;
        padding: 0 1 1 1;
        border-bottom: solid $primary-background;
        margin-bottom: 1;
    }

    MemoEditModal > #memo-container > #current-memo {
        height: auto;
        padding: 0 1 1 1;
        color: $text-muted;
    }

    MemoEditModal > #memo-container > #memo-input {
        height: 3;
        margin-bottom: 1;
    }

    MemoEditModal > #memo-container > #memo-footer {
        height: 1;
        text-align: center;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "save", "Save", priority=True),
    ]

    def __init__(
        self,
        transaction: TransactionInfo,
        **kwargs,
    ) -> None:
        """Initialize memo edit modal.

        Args:
            transaction: Transaction info to display.
        """
        super().__init__(**kwargs)
        self._transaction = transaction
        self._original_memo = transaction.current_memo or ""

    def compose(self) -> ComposeResult:
        """Compose the modal UI."""
        with Vertical(id="memo-container"):
            # Transaction info
            with Vertical(id="txn-info"):
                yield Static(
                    f"[b]{self._transaction.payee}[/b]  {self._transaction.amount}",
                )
                yield Static(
                    f"[dim]{self._transaction.date}[/dim]",
                )

            # Current memo display
            if self._original_memo:
                yield Static(
                    f"[dim]Current:[/dim] {self._original_memo}",
                    id="current-memo",
                )
            else:
                yield Static(
                    "[dim]No memo set[/dim]",
                    id="current-memo",
                )

            # Memo input
            yield Input(
                value=self._original_memo,
                placeholder="Enter memo...",
                id="memo-input",
            )

            yield Static(
                "Enter save | Esc cancel",
                id="memo-footer",
            )

    def on_mount(self) -> None:
        """Focus the input on mount."""
        self.query_one("#memo-input", Input).focus()

    def action_cancel(self) -> None:
        """Cancel and dismiss."""
        self.dismiss(None)

    def action_save(self) -> None:
        """Save the memo."""
        new_memo = self.query_one("#memo-input", Input).value.strip()
        changed = new_memo != self._original_memo
        self.dismiss(MemoEditResult(memo=new_memo, changed=changed))
