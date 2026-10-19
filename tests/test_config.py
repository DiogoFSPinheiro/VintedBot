import pytest

from vintedbot.config import ConfigError, load_settings


def test_defaults():
    s = load_settings({"TELEGRAM_TOKEN": "t"})
    assert s.telegram_token == "t"
    assert s.allowed_chat_id is None
    assert s.poll_interval == 120
    assert s.db_path == "vintedbot.db"


def test_values_are_parsed_and_poll_interval_clamped():
    s = load_settings({"TELEGRAM_TOKEN": "t", "ALLOWED_CHAT_ID": "-100123", "POLL_INTERVAL": "30", "DB_PATH": "x.db"})
    assert s.allowed_chat_id == -100123
    assert s.poll_interval == 60
    assert s.db_path == "x.db"


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"TELEGRAM_TOKEN": ""},
        {"TELEGRAM_TOKEN": "t", "ALLOWED_CHAT_ID": "abc"},
        {"TELEGRAM_TOKEN": "t", "POLL_INTERVAL": "rápido"},
    ],
)
def test_invalid_config_raises(env):
    with pytest.raises(ConfigError):
        load_settings(env)


def _no_claude(_name):
    return None


def test_price_check_uses_claude_found_on_path():
    s = load_settings({"TELEGRAM_TOKEN": "t"}, which=lambda name: f"/usr/bin/{name}")
    assert s.claude_bin == "/usr/bin/claude"
    assert s.claude_model == "sonnet"


def test_price_check_disabled_without_claude_or_by_config():
    assert load_settings({"TELEGRAM_TOKEN": "t"}, which=_no_claude).claude_bin is None
    env = {"TELEGRAM_TOKEN": "t", "PRICE_CHECK": "0"}
    assert load_settings(env, which=lambda name: f"/usr/bin/{name}").claude_bin is None


def test_price_check_custom_binary_and_model():
    env = {"TELEGRAM_TOKEN": "t", "CLAUDE_BIN": "/opt/claude", "CLAUDE_MODEL": "opus"}
    s = load_settings(env, which=_no_claude)
    assert (s.claude_bin, s.claude_model) == ("/opt/claude", "opus")
