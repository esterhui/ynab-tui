"""Help screen for displaying keyboard shortcuts."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

HELP_TEXT = """\
[b]Navigation:[/b]
  j/k       Move down/up
  g/G       Top/bottom
  Ctrl+d/u  Half page down/up
  Ctrl+f/b  Full page down/up

[b]Actions:[/b]
  c         Categorize (bulk if tagged)
  a         Approve (bulk if tagged)
  u         Undo pending change
  x         Split (Amazon multi-item)
  m         Edit memo
  p         Push to YNAB

[b]Tagging:[/b]
  t         Tag/untag (★)
  T         Clear all tags

[b]Filter (f + key):[/b]
  a         Unapproved
  u         Uncategorized
  e         Pending push
  c         By category
  p         By payee
  r         Reset (all)

[b]Other:[/b]
  /         Search
  b         Switch budget
  s         Settings
  Enter     Categorize selected
  Escape    Quit
  F5        Refresh
  q         Quit

[b]Status Flags:[/b]
  A=Approved  C=Cleared  R=Reconciled
  M=Memo  P=Pending  !=Conflict
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
