"""Settings screen for viewing and editing configuration."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Static

from ...config import Config


class SettingsScreen(Screen):
    """Screen for viewing and editing application settings."""

    CSS = """
    SettingsScreen {
        background: $surface;
    }

    #settings-container {
        width: 100%;
        height: 100%;
        padding: 1;
    }

    .settings-section {
        height: auto;
        padding: 1;
        border: solid $primary;
        margin-bottom: 1;
    }

    .section-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    .setting-row {
        height: 3;
        padding: 0 1;
    }

    .setting-label {
        width: 25;
        color: $text-muted;
    }

    .setting-value {
        width: 1fr;
        color: $text;
    }

    .setting-masked {
        color: $warning;
    }

    #window-input {
        width: 10;
    }

    #action-bar {
        dock: bottom;
        height: 3;
        padding: 0 1;
        background: $primary-background;
    }

    #env-hint {
        height: auto;
        padding: 1;
        background: $warning-muted;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit_settings", "Quit"),
        Binding("escape", "quit_settings", "Quit"),
    ]

    def __init__(self, config: Config, **kwargs) -> None:
        """Initialize the settings screen.

        Args:
            config: Current application configuration.
        """
        super().__init__(**kwargs)
        self._config = config

    def compose(self) -> ComposeResult:
        """Compose the screen."""
        yield Header()
        yield Container(
            self._compose_content(),
            id="settings-container",
        )
        yield Footer()

    def _compose_content(self) -> Vertical:
        """Compose the settings content."""
        sections = []

        # YNAB Settings
        sections.append(
            Vertical(
                Static("YNAB Configuration", classes="section-title"),
                Horizontal(
                    Label("API Token:", classes="setting-label"),
                    Label(
                        self._mask_token(self._config.ynab.api_token),
                        classes="setting-value setting-masked",
                    ),
                    classes="setting-row",
                ),
                Horizontal(
                    Label("Budget ID:", classes="setting-label"),
                    Label(self._config.ynab.budget_id or "last-used", classes="setting-value"),
                    classes="setting-row",
                ),
                classes="settings-section",
            )
        )

        # Amazon Settings
        sections.append(
            Vertical(
                Static("Amazon Configuration", classes="section-title"),
                Horizontal(
                    Label("Username:", classes="setting-label"),
                    Label(
                        self._mask_email(self._config.amazon.username),
                        classes="setting-value setting-masked",
                    ),
                    classes="setting-row",
                ),
                Horizontal(
                    Label("Password:", classes="setting-label"),
                    Label(
                        "********" if self._config.amazon.password else "(not set)",
                        classes="setting-value setting-masked",
                    ),
                    classes="setting-row",
                ),
                Horizontal(
                    Label("OTP Secret:", classes="setting-label"),
                    Label(
                        "(configured)" if self._config.amazon.otp_secret else "(not set)",
                        classes="setting-value",
                    ),
                    classes="setting-row",
                ),
                classes="settings-section",
            )
        )

        # Categorization Settings
        sections.append(
            Vertical(
                Static("Categorization Settings", classes="section-title"),
                Horizontal(
                    Label("Date Match Window:", classes="setting-label"),
                    Input(
                        value=str(self._config.categorization.date_match_window_days),
                        placeholder="14",
                        id="window-input",
                    ),
                    Label(" days", classes="setting-value"),
                    classes="setting-row",
                ),
                classes="settings-section",
            )
        )

        # Environment variable hint
        sections.append(
            Vertical(
                Static(
                    "[b]Note:[/b] Sensitive values (tokens, passwords) should be set via environment variables:"
                ),
                Static("  • YNAB_API_TOKEN"),
                Static("  • AMAZON_USERNAME, AMAZON_PASSWORD"),
                Static("\nOr in config.toml (less secure)."),
                id="env-hint",
            )
        )

        # Action bar
        action_bar = Horizontal(
            Button("Save Changes", id="save-btn", variant="primary"),
            Button("Close [Q]", id="close-btn", variant="default"),
            id="action-bar",
        )

        return Vertical(*sections, action_bar)

    def _mask_token(self, token: str) -> str:
        """Mask a token for display."""
        if not token:
            return "(not set)"
        if len(token) <= 8:
            return "*" * len(token)
        return token[:4] + "*" * (len(token) - 8) + token[-4:]

    def _mask_email(self, email: str) -> str:
        """Mask an email for display."""
        if not email:
            return "(not set)"
        if "@" not in email:
            return self._mask_token(email)
        parts = email.split("@")
        if len(parts[0]) <= 2:
            return email
        return parts[0][:2] + "***@" + parts[1]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "save-btn":
            self._save_settings()
        elif event.button.id == "close-btn":
            self.action_quit_settings()

    def _save_settings(self) -> None:
        """Save the current settings."""
        try:
            window_input = self.query_one("#window-input", Input)

            try:
                window = int(window_input.value)
                if window >= 0:
                    self._config.categorization.date_match_window_days = window
                else:
                    raise ValueError("Window must be non-negative")
            except ValueError as e:
                self.notify(f"Invalid window: {e}", severity="error")
                return

            self.notify("Settings saved (in memory only)", severity="information")
            self.notify("To persist, update config.toml or env vars", severity="warning")

        except Exception as e:
            self.notify(f"Error saving settings: {e}", severity="error")

    def action_quit_settings(self) -> None:
        """Quit settings screen."""
        self.app.pop_screen()
