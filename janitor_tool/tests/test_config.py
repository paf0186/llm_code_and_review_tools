"""Tests for janitor_tool.config module."""

import os
from unittest.mock import patch

from janitor_tool.config import JanitorConfig, load_config


class TestJanitorConfig:
    """Tests for JanitorConfig dataclass."""

    def test_strips_trailing_slash(self):
        config = JanitorConfig(base_url="https://example.com/janitor/")
        assert config.base_url == "https://example.com/janitor"

    def test_no_trailing_slash(self):
        config = JanitorConfig(base_url="https://example.com/janitor")
        assert config.base_url == "https://example.com/janitor"

    def test_multiple_trailing_slashes(self):
        # rstrip("/") removes all trailing slashes
        config = JanitorConfig(base_url="https://example.com///")
        assert config.base_url == "https://example.com"


class TestLoadConfig:
    """Tests for load_config()."""

    @patch.dict(os.environ, {}, clear=True)
    def test_default_url(self):
        config = load_config()
        assert "testing.whamcloud.com" in config.base_url

    @patch.dict(os.environ, {"JANITOR_URL": "https://custom.example.com/janitor"})
    def test_custom_url(self):
        config = load_config()
        assert config.base_url == "https://custom.example.com/janitor"

    @patch.dict(os.environ, {"JANITOR_URL": "https://custom.example.com/janitor/"})
    def test_custom_url_stripped(self):
        config = load_config()
        assert config.base_url == "https://custom.example.com/janitor"
