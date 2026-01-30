"""Unit tests for configuration handling."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from jira_tool.config import (
    JiraConfig,
    _load_env_file,
    create_sample_config,
    load_config,
)
from jira_tool.errors import ConfigError


class TestJiraConfig:
    """Tests for JiraConfig dataclass."""

    def test_basic_creation(self):
        """Should create config with required fields."""
        config = JiraConfig(
            server="https://jira.example.com",
            token="test-token",
        )
        assert config.server == "https://jira.example.com"
        assert config.token == "test-token"

    def test_server_url_normalization(self):
        """Should strip trailing slash from server URL."""
        config = JiraConfig(
            server="https://jira.example.com/",
            token="test-token",
        )
        assert config.server == "https://jira.example.com"

    def test_multiple_trailing_slashes(self):
        """Should strip multiple trailing slashes."""
        config = JiraConfig(
            server="https://jira.example.com///",
            token="test-token",
        )
        assert config.server == "https://jira.example.com"

    def test_empty_server_raises_error(self):
        """Should raise ConfigError for empty server."""
        with pytest.raises(ConfigError) as exc_info:
            JiraConfig(server="", token="test-token")
        assert "Server URL is required" in str(exc_info.value)

    def test_empty_token_raises_error(self):
        """Should raise ConfigError for empty token."""
        with pytest.raises(ConfigError) as exc_info:
            JiraConfig(server="https://jira.example.com", token="")
        assert "API token is required" in str(exc_info.value)

    def test_from_dict_flat_format(self):
        """Should parse flat config format."""
        data = {
            "server": "https://jira.example.com",
            "token": "my-token",
        }
        config = JiraConfig.from_dict(data)
        assert config.server == "https://jira.example.com"
        assert config.token == "my-token"

    def test_from_dict_nested_auth_format(self):
        """Should parse nested auth config format."""
        data = {
            "server": "https://jira.example.com",
            "auth": {
                "type": "token",
                "token": "my-token",
            },
        }
        config = JiraConfig.from_dict(data)
        assert config.token == "my-token"


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_from_explicit_overrides(self, tmp_path):
        """Explicit overrides should take precedence."""
        # Create a config file with different values
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "server": "https://file-server.com",
                    "token": "file-token",
                }
            )
        )

        # Override should win
        config = load_config(
            config_path=config_file,
            server_override="https://override-server.com",
            token_override="override-token",
        )
        assert config.server == "https://override-server.com"
        assert config.token == "override-token"

    def test_load_from_env_vars(self, tmp_path, monkeypatch):
        """Environment variables should override config file."""
        # Create config file
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "server": "https://file-server.com",
                    "token": "file-token",
                }
            )
        )

        # Set env vars
        monkeypatch.setenv("JIRA_SERVER", "https://env-server.com")
        monkeypatch.setenv("JIRA_TOKEN", "env-token")

        config = load_config(config_path=config_file)
        assert config.server == "https://env-server.com"
        assert config.token == "env-token"

    def test_load_from_config_file(self, tmp_path, monkeypatch):
        """Should load from config file when no overrides."""
        # Clear any env vars
        monkeypatch.delenv("JIRA_SERVER", raising=False)
        monkeypatch.delenv("JIRA_TOKEN", raising=False)

        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "server": "https://file-server.com",
                    "token": "file-token",
                }
            )
        )

        config = load_config(config_path=config_file)
        assert config.server == "https://file-server.com"
        assert config.token == "file-token"

    def test_missing_config_and_env_raises_error(self, tmp_path, monkeypatch):
        """Should raise ConfigError when no config source available."""
        monkeypatch.delenv("JIRA_SERVER", raising=False)
        monkeypatch.delenv("JIRA_TOKEN", raising=False)

        nonexistent = tmp_path / "nonexistent.json"

        with pytest.raises(ConfigError) as exc_info:
            load_config(config_path=nonexistent)
        assert "No configuration found" in str(exc_info.value)

    def test_missing_server_raises_error(self, tmp_path, monkeypatch):
        """Should raise ConfigError when server is missing."""
        monkeypatch.delenv("JIRA_SERVER", raising=False)
        monkeypatch.delenv("JIRA_TOKEN", raising=False)

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"token": "my-token"}))

        with pytest.raises(ConfigError) as exc_info:
            load_config(config_path=config_file)
        assert "Server URL not configured" in str(exc_info.value)

    def test_missing_token_raises_error(self, tmp_path, monkeypatch):
        """Should raise ConfigError when token is missing."""
        monkeypatch.delenv("JIRA_SERVER", raising=False)
        monkeypatch.delenv("JIRA_TOKEN", raising=False)

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"server": "https://jira.example.com"}))

        with pytest.raises(ConfigError) as exc_info:
            load_config(config_path=config_file)
        assert "API token not configured" in str(exc_info.value)

    def test_invalid_json_raises_error(self, tmp_path, monkeypatch):
        """Should raise ConfigError for invalid JSON."""
        monkeypatch.delenv("JIRA_SERVER", raising=False)
        monkeypatch.delenv("JIRA_TOKEN", raising=False)

        config_file = tmp_path / "config.json"
        config_file.write_text("not valid json {")

        with pytest.raises(ConfigError) as exc_info:
            load_config(config_path=config_file)
        assert "Invalid JSON" in str(exc_info.value)

    def test_priority_order(self, tmp_path, monkeypatch):
        """Test full priority chain: explicit > env > file."""
        # Config file
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "server": "https://file.com",
                    "token": "file-token",
                }
            )
        )

        # Env vars (higher priority)
        monkeypatch.setenv("JIRA_SERVER", "https://env.com")
        monkeypatch.setenv("JIRA_TOKEN", "env-token")

        # Test env wins over file
        config = load_config(config_path=config_file)
        assert config.server == "https://env.com"

        # Test explicit wins over env
        config = load_config(
            config_path=config_file,
            server_override="https://explicit.com",
        )
        assert config.server == "https://explicit.com"
        assert config.token == "env-token"  # Not overridden


class TestCreateSampleConfig:
    """Tests for create_sample_config function."""

    def test_returns_valid_json(self):
        """Sample config should be valid JSON."""
        sample = create_sample_config()
        data = json.loads(sample)
        assert "server" in data
        assert "auth" in data

    def test_has_placeholder_values(self):
        """Sample config should have placeholder values."""
        sample = create_sample_config()
        data = json.loads(sample)
        assert "example.com" in data["server"]
        assert "token" in data["auth"]["type"]


class TestLoadEnvFile:
    """Tests for _load_env_file function."""

    def test_loads_from_user_config_dir(self, tmp_path, monkeypatch):
        """Should load .env from ~/.config/jira-tool/.env."""
        # Clear any existing env vars
        monkeypatch.delenv("JIRA_SERVER", raising=False)
        monkeypatch.delenv("JIRA_TOKEN", raising=False)

        # Create fake user config directory
        user_config = tmp_path / ".config" / "jira-tool"
        user_config.mkdir(parents=True)
        env_file = user_config / ".env"
        env_file.write_text("JIRA_SERVER=https://user-config.example.com\nJIRA_TOKEN=user-token\n")

        # Patch Path.home() to return our temp directory
        with patch.object(Path, "home", return_value=tmp_path):
            _load_env_file()

        assert os.environ.get("JIRA_SERVER") == "https://user-config.example.com"
        assert os.environ.get("JIRA_TOKEN") == "user-token"

        # Cleanup
        monkeypatch.delenv("JIRA_SERVER", raising=False)
        monkeypatch.delenv("JIRA_TOKEN", raising=False)

    def test_loads_from_cwd_env(self, tmp_path, monkeypatch):
        """Should load .env from current directory."""
        # Clear any existing env vars
        monkeypatch.delenv("JIRA_SERVER", raising=False)
        monkeypatch.delenv("JIRA_TOKEN", raising=False)

        # Create .env in "current directory"
        env_file = tmp_path / ".env"
        env_file.write_text("JIRA_SERVER=https://cwd.example.com\nJIRA_TOKEN=cwd-token\n")

        # Change to temp directory and patch home to avoid user config
        original_cwd = os.getcwd()
        os.chdir(tmp_path)

        # Patch home to a non-existent path so user config isn't found
        fake_home = tmp_path / "fake_home"
        try:
            with patch.object(Path, "home", return_value=fake_home):
                _load_env_file()

            assert os.environ.get("JIRA_SERVER") == "https://cwd.example.com"
            assert os.environ.get("JIRA_TOKEN") == "cwd-token"
        finally:
            os.chdir(original_cwd)
            monkeypatch.delenv("JIRA_SERVER", raising=False)
            monkeypatch.delenv("JIRA_TOKEN", raising=False)

    def test_user_config_takes_priority_over_cwd(self, tmp_path, monkeypatch):
        """User config .env should take priority over cwd .env."""
        # Clear any existing env vars
        monkeypatch.delenv("JIRA_SERVER", raising=False)
        monkeypatch.delenv("JIRA_TOKEN", raising=False)

        # Create user config .env
        user_config = tmp_path / ".config" / "jira-tool"
        user_config.mkdir(parents=True)
        user_env = user_config / ".env"
        user_env.write_text("JIRA_SERVER=https://user.example.com\n")

        # Create cwd .env with different value
        cwd_env = tmp_path / ".env"
        cwd_env.write_text("JIRA_SERVER=https://cwd.example.com\n")

        original_cwd = os.getcwd()
        os.chdir(tmp_path)

        try:
            with patch.object(Path, "home", return_value=tmp_path):
                _load_env_file()

            # User config should win
            assert os.environ.get("JIRA_SERVER") == "https://user.example.com"
        finally:
            os.chdir(original_cwd)
            monkeypatch.delenv("JIRA_SERVER", raising=False)

    def test_no_env_file_does_not_error(self, tmp_path, monkeypatch):
        """Should not error when no .env file exists."""
        # Clear any existing env vars
        monkeypatch.delenv("JIRA_SERVER", raising=False)

        # Point to empty directories
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()

        original_cwd = os.getcwd()
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        os.chdir(empty_dir)

        try:
            with patch.object(Path, "home", return_value=fake_home):
                # Should not raise
                _load_env_file()

            # Env var should not be set
            assert os.environ.get("JIRA_SERVER") is None
        finally:
            os.chdir(original_cwd)

    def test_env_file_integrates_with_load_config(self, tmp_path, monkeypatch):
        """Variables from .env should be available to load_config."""
        # Clear any existing env vars
        monkeypatch.delenv("JIRA_SERVER", raising=False)
        monkeypatch.delenv("JIRA_TOKEN", raising=False)

        # Create .env file
        env_file = tmp_path / ".env"
        env_file.write_text("JIRA_SERVER=https://dotenv.example.com\nJIRA_TOKEN=dotenv-token\n")

        original_cwd = os.getcwd()
        os.chdir(tmp_path)

        # Patch home to avoid user config
        fake_home = tmp_path / "fake_home"
        try:
            with patch.object(Path, "home", return_value=fake_home):
                _load_env_file()

            # Now load_config should pick up the env vars
            config = load_config(config_path=tmp_path / "nonexistent.json")
            assert config.server == "https://dotenv.example.com"
            assert config.token == "dotenv-token"
        finally:
            os.chdir(original_cwd)
            monkeypatch.delenv("JIRA_SERVER", raising=False)
            monkeypatch.delenv("JIRA_TOKEN", raising=False)
