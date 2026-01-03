"""Configuration management for YNAB Categorizer.

Loads configuration from TOML file with environment variable overrides.
Environment variables take precedence over TOML values.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import tomli


@dataclass
class YNABConfig:
    """YNAB API configuration."""

    api_token: str = ""
    budget_id: str = "last-used"
    # API resilience settings
    timeout_seconds: int = 30  # Request timeout
    max_retries: int = 3  # Max retry attempts for transient failures
    retry_base_delay: float = 1.0  # Initial retry delay in seconds


@dataclass
class AmazonConfig:
    """Amazon orders scraping configuration."""

    username: str = ""
    password: str = ""
    otp_secret: str = ""
    # Matching parameters
    stage1_window_days: int = 7  # Days for strict matching (first pass)
    stage2_window_days: int = 24  # Days for extended matching (second pass)
    amount_tolerance: float = 0.10  # Dollar tolerance for amount matching
    recent_orders_days: int = 30  # Default lookback for recent orders
    earliest_history_year: int = 2006  # Start year for order history


@dataclass
class CategorizationConfig:
    """Categorization behavior configuration."""

    date_match_window_days: int = 14
    sync_overlap_days: int = 7  # Overlap for incremental syncs
    min_category_confidence: float = 0.5  # Minimum confidence for category suggestions


@dataclass
class PayeesConfig:
    """Payee matching patterns."""

    amazon_patterns: list[str] = field(
        default_factory=lambda: ["AMAZON", "AMZN", "Amazon.com", "AMAZON MKTPLACE"]
    )


@dataclass
class DisplayConfig:
    """Display configuration for TUI and CLI."""

    # TUI column widths
    payee_width: int = 18
    amount_width: int = 12
    category_width: int = 20
    account_width: int = 16
    status_width: int = 6
    # Pagination
    half_page_size: int = 10
    full_page_size: int = 20
    # Items display
    amazon_items_preview_count: int = 3
    item_name_truncate_length: int = 60
    # CLI formatting
    cli_payee_width: int = 25
    cli_category_width: int = 20
    # Search matching style: "substring" (default), "fuzzy" (fzf-style), "word_boundary"
    search_match_style: str = "substring"
    # Color-code status letters (A, C, R, M, P, !) in transaction list
    color_status_letters: bool = False


@dataclass
class Config:
    """Main application configuration."""

    ynab: YNABConfig = field(default_factory=YNABConfig)
    amazon: AmazonConfig = field(default_factory=AmazonConfig)
    categorization: CategorizationConfig = field(default_factory=CategorizationConfig)
    payees: PayeesConfig = field(default_factory=PayeesConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    data_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get("YNAB_TUI_DATA_DIR", str(Path.home() / ".config" / "ynab-tui"))
        )
    )

    def __post_init__(self):
        """Ensure data directory exists."""
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @property
    def db_path(self) -> Path:
        """Path to SQLite database."""
        return self.data_dir / "categorizer.db"


def _get_env(key: str, default: str = "") -> str:
    """Get environment variable with fallback."""
    return os.environ.get(key, default)


def _get_env_float(key: str, default: float) -> float:
    """Get environment variable as float with fallback."""
    val = os.environ.get(key)
    if val is not None:
        try:
            return float(val)
        except ValueError:
            pass
    return default


def _get_env_int(key: str, default: int) -> int:
    """Get environment variable as int with fallback."""
    val = os.environ.get(key)
    if val is not None:
        try:
            return int(val)
        except ValueError:
            pass
    return default


def load_config(config_path: Optional[Path] = None) -> Config:
    """Load configuration from TOML file with environment variable overrides.

    Args:
        config_path: Path to config.toml file. If None, looks for config.toml
                     in ~/.config/ynab-tui/config.toml or current directory.

    Returns:
        Config object with all settings.

    Environment variables override TOML values:
        - YNAB_API_TOKEN: YNAB API token
        - YNAB_BUDGET_ID: YNAB budget ID
        - AMAZON_USERNAME: Amazon username
        - AMAZON_PASSWORD: Amazon password
        - AMAZON_OTP_SECRET: Amazon TOTP secret for 2FA
        - DATE_MATCH_WINDOW_DAYS: Days for fuzzy date matching
    """
    toml_data: dict = {}

    # Search for config file
    if config_path is None:
        search_paths = [
            Path.home() / ".config" / "ynab-tui" / "config.toml",
            Path.cwd() / "config.toml",
        ]
        for path in search_paths:
            if path.exists():
                config_path = path
                break

    # Load TOML if found
    if config_path and config_path.exists():
        with open(config_path, "rb") as f:
            toml_data = tomli.load(f)

    # Build config with TOML values, then override with env vars
    ynab_data = toml_data.get("ynab", {})
    ynab = YNABConfig(
        api_token=_get_env("YNAB_API_TOKEN", ynab_data.get("api_token", "")),
        budget_id=_get_env("YNAB_BUDGET_ID", ynab_data.get("budget_id", "last-used")),
        timeout_seconds=_get_env_int("YNAB_TIMEOUT_SECONDS", ynab_data.get("timeout_seconds", 30)),
        max_retries=_get_env_int("YNAB_MAX_RETRIES", ynab_data.get("max_retries", 3)),
        retry_base_delay=_get_env_float(
            "YNAB_RETRY_BASE_DELAY", ynab_data.get("retry_base_delay", 1.0)
        ),
    )

    amazon_data = toml_data.get("amazon", {})
    amazon = AmazonConfig(
        username=_get_env("AMAZON_USERNAME", amazon_data.get("username", "")),
        password=_get_env("AMAZON_PASSWORD", amazon_data.get("password", "")),
        otp_secret=_get_env("AMAZON_OTP_SECRET", amazon_data.get("otp_secret", "")),
        stage1_window_days=amazon_data.get("stage1_window_days", 7),
        stage2_window_days=amazon_data.get("stage2_window_days", 24),
        amount_tolerance=amazon_data.get("amount_tolerance", 0.10),
        recent_orders_days=amazon_data.get("recent_orders_days", 30),
        earliest_history_year=amazon_data.get("earliest_history_year", 2006),
    )

    cat_data = toml_data.get("categorization", {})
    categorization = CategorizationConfig(
        date_match_window_days=_get_env_int(
            "DATE_MATCH_WINDOW_DAYS", cat_data.get("date_match_window_days", 14)
        ),
        sync_overlap_days=cat_data.get("sync_overlap_days", 7),
        min_category_confidence=cat_data.get("min_category_confidence", 0.5),
    )

    payees_data = toml_data.get("payees", {})
    payees = PayeesConfig(
        amazon_patterns=payees_data.get(
            "amazon_patterns", ["AMAZON", "AMZN", "Amazon.com", "AMAZON MKTPLACE"]
        )
    )

    display_data = toml_data.get("display", {})
    display = DisplayConfig(
        payee_width=display_data.get("payee_width", 18),
        amount_width=display_data.get("amount_width", 12),
        category_width=display_data.get("category_width", 20),
        account_width=display_data.get("account_width", 16),
        status_width=display_data.get("status_width", 6),
        half_page_size=display_data.get("half_page_size", 10),
        full_page_size=display_data.get("full_page_size", 20),
        amazon_items_preview_count=display_data.get("amazon_items_preview_count", 3),
        item_name_truncate_length=display_data.get("item_name_truncate_length", 60),
        cli_payee_width=display_data.get("cli_payee_width", 25),
        cli_category_width=display_data.get("cli_category_width", 20),
        search_match_style=display_data.get("search_match_style", "substring"),
        color_status_letters=display_data.get("color_status_letters", False),
    )

    return Config(
        ynab=ynab,
        amazon=amazon,
        categorization=categorization,
        payees=payees,
        display=display,
    )
