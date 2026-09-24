from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

MIN_POLL_INTERVAL = 60


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    allowed_chat_id: int | None
    poll_interval: int
    db_path: str


def _int(env: Mapping[str, str], key: str, default: int | None) -> int | None:
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} tem de ser um número inteiro (recebi {raw!r}).") from exc


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    if env is None:
        from dotenv import load_dotenv

        load_dotenv()
        env = os.environ
    token = (env.get("TELEGRAM_TOKEN") or "").strip()
    if not token:
        raise ConfigError("Falta TELEGRAM_TOKEN no .env (cria o bot no @BotFather).")
    return Settings(
        telegram_token=token,
        allowed_chat_id=_int(env, "ALLOWED_CHAT_ID", None),
        poll_interval=max(MIN_POLL_INTERVAL, _int(env, "POLL_INTERVAL", 120)),
        db_path=(env.get("DB_PATH") or "vintedbot.db").strip(),
    )
