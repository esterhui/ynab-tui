"""Help screen for displaying keyboard shortcuts."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

HELP_TEXT = """\
[b]Vim-style Navigation:[/b]
  j/Down    Move down
  k/Up      Move up
  g         Go to top
  G         Go to bottom
  Ctrl+d    Half page down
  Ctrl+u    Half page up
  Ctrl+f    Full page down
  Ctrl+b    Full page up

[b]Tagging & Bulk Actions:[/b]
  t         Tag/untag transaction (green star)
  c/Enter   Categorize (bulk if tagged)
  a         Approve (bulk if tagged)

[b]Categorization:[/b]
  x         Split mode (Amazon multi-item)
  m         Edit memo
  u         Undo pending change (revert to original)

[b]Other Actions:[/b]
  f         Filter menu (then press a/n/u/p/x)
  T         Untag all tagged transactions
  s         Settings
  p         Push pending changes to YNAB
  F5        Refresh
  q         Quit

[b]Filter Shortcuts (after pressing f):[/b]
  fa        Approved transactions
  fn        New (unapproved) transactions
  fu        Uncategorized transactions
  fp        Pending push to YNAB
  fx        All transactions

[b]Status Column Legend:[/b]
  A         Approved
  C         Cleared
  R         Reconciled
  M         Has memo
  P         Pending push to YNAB
  !         Sync conflict
"""


class HelpScreen(Screen):
    """Screen for displaying keyboard shortcuts and help information."""

    CSS = """
    HelpScreen {
        background: $surface;
    }

    #help-container {
        width: 100%;
        height: 100%;
        padding: 1;
    }

    #help-box {
        height: 1fr;
        padding: 1 2;
        border: solid $primary;
    }

    #help-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    #help-hint {
        dock: bottom;
        height: 1;
        background: $primary-background;
        padding: 0 1;
        text-align: center;
    }
    """

    BINDINGS = [
        Binding("question_mark", "close", "Close", show=False),
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close", show=False),
    ]

    def compose(self) -> ComposeResult:
        """Compose the screen."""
        yield Header()
        yield Container(
            VerticalScroll(
                Static("[b]Keyboard Shortcuts[/b]\n", id="help-title"),
                Static(HELP_TEXT),
                id="help-box",
            ),
            Static("[dim]Press ? or Esc to close[/dim]", id="help-hint"),
            id="help-container",
        )
        yield Footer()

    def action_close(self) -> None:
        """Close the help screen."""
        self.app.pop_screen()
