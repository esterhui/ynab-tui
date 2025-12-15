"""Tests for configuration management."""

import os
from pathlib import Path

from src.config import (
    AmazonConfig,
    CategorizationConfig,
    Config,
    PayeesConfig,
    YNABConfig,
    load_config,
)


class TestYNABConfig:
    """Tests for YNABConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = YNABConfig()
        assert config.api_token == ""
        assert config.budget_id == "last-used"

    def test_custom_values(self):
        """Test custom configuration values."""
        config = YNABConfig(api_token="my-token", budget_id="my-budget")
        assert config.api_token == "my-token"
        assert config.budget_id == "my-budget"


class TestAmazonConfig:
    """Tests for AmazonConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = AmazonConfig()
        assert config.username == ""
        assert config.password == ""
        assert config.otp_secret == ""

    def test_custom_values(self):
        """Test custom configuration values."""
        config = AmazonConfig(
            username="user@example.com",
            password="secret",
            otp_secret="TOTP123",
        )
        assert config.username == "user@example.com"
        assert config.password == "secret"
        assert config.otp_secret == "TOTP123"


class TestCategorizationConfig:
    """Tests for CategorizationConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = CategorizationConfig()
        assert config.date_match_window_days == 14

    def test_custom_values(self):
        """Test custom configuration values."""
        config = CategorizationConfig(
            date_match_window_days=5,
        )
        assert config.date_match_window_days == 5


class TestPayeesConfig:
    """Tests for PayeesConfig dataclass."""

    def test_default_amazon_patterns(self):
        """Test default Amazon patterns."""
        config = PayeesConfig()
        assert "AMAZON" in config.amazon_patterns
        assert "AMZN" in config.amazon_patterns

    def test_custom_patterns(self):
        """Test custom Amazon patterns."""
        config = PayeesConfig(amazon_patterns=["CUSTOM_AMAZON"])
        assert config.amazon_patterns == ["CUSTOM_AMAZON"]


class TestConfig:
    """Tests for main Config dataclass."""

    def test_default_config(self):
        """Test default configuration."""
        config = Config()
        assert isinstance(config.ynab, YNABConfig)
        assert isinstance(config.amazon, AmazonConfig)
        assert isinstance(config.categorization, CategorizationConfig)
        assert isinstance(config.payees, PayeesConfig)

    def test_db_path(self, tmp_path):
        """Test database path property."""
        config = Config(data_dir=tmp_path)
        assert config.db_path == tmp_path / "categorizer.db"

    def test_data_dir_creation(self, tmp_path):
        """Test that data directory is created on init."""
        new_dir = tmp_path / "new_data_dir"
        assert not new_dir.exists()
        _ = Config(data_dir=new_dir)  # Creating config triggers directory creation
        assert new_dir.exists()


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_defaults_no_file(self, tmp_path):
        """Test loading defaults when no config file exists."""
        # Change to temp directory with no config.toml
        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            config = load_config()
            assert config.ynab.budget_id == "last-used"
            assert config.categorization.date_match_window_days == 14
        finally:
            os.chdir(original_cwd)

    def test_load_from_toml(self, tmp_path, config_toml_content, monkeypatch):
        """Test loading configuration from TOML file."""
        # Clear any env vars that would override TOML
        monkeypatch.delenv("YNAB_API_TOKEN", raising=False)
        monkeypatch.delenv("YNAB_BUDGET_ID", raising=False)
        monkeypatch.delenv("AMAZON_USERNAME", raising=False)
        monkeypatch.delenv("AMAZON_PASSWORD", raising=False)

        config_path = tmp_path / "config.toml"
        config_path.write_text(config_toml_content)

        config = load_config(config_path)

        assert config.ynab.api_token == "toml-token"
        assert config.ynab.budget_id == "toml-budget"
        assert config.amazon.username == "toml@example.com"
        assert config.categorization.date_match_window_days == 5
        assert config.payees.amazon_patterns == ["AMAZON", "AMZN"]

    def test_env_vars_override_toml(self, tmp_path, config_toml_content, monkeypatch):
        """Test that environment variables override TOML values."""
        config_path = tmp_path / "config.toml"
        config_path.write_text(config_toml_content)

        # Set environment variables
        monkeypatch.setenv("YNAB_API_TOKEN", "env-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "env-budget")
        monkeypatch.setenv("AMAZON_USERNAME", "env@example.com")
        monkeypatch.setenv("DATE_MATCH_WINDOW_DAYS", "10")

        config = load_config(config_path)

        # Environment variables should override TOML
        assert config.ynab.api_token == "env-token"
        assert config.ynab.budget_id == "env-budget"
        assert config.amazon.username == "env@example.com"
        assert config.categorization.date_match_window_days == 10

    def test_env_vars_without_toml(self, tmp_path, monkeypatch):
        """Test loading from environment variables only."""
        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            monkeypatch.setenv("YNAB_API_TOKEN", "env-only-token")

            config = load_config()

            assert config.ynab.api_token == "env-only-token"
            # Defaults should still apply
            assert config.categorization.date_match_window_days == 14
        finally:
            os.chdir(original_cwd)

    def test_invalid_int_env_var_uses_default(self, tmp_path, monkeypatch):
        """Test that invalid int env vars fall back to defaults."""
        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            monkeypatch.setenv("DATE_MATCH_WINDOW_DAYS", "not-a-number")

            config = load_config()

            assert config.categorization.date_match_window_days == 14  # Default
        finally:
            os.chdir(original_cwd)

    def test_search_paths(self, tmp_path, config_toml_content, monkeypatch):
        """Test config file search paths."""
        # Clear any env vars that would override TOML
        monkeypatch.delenv("YNAB_API_TOKEN", raising=False)

        # Mock home directory to avoid picking up real config
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        # Create config in cwd
        config_path = tmp_path / "config.toml"
        config_path.write_text(config_toml_content)

        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            config = load_config()  # No explicit path
            assert config.ynab.api_token == "toml-token"
        finally:
            os.chdir(original_cwd)
