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
