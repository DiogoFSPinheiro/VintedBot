from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping
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
    # Caminho do Claude CLI para o botão «Avaliar preço»; None desliga a funcionalidade.
    claude_bin: str | None = None
    claude_model: str = "sonnet"


def _int(env: Mapping[str, str], key: str, default: int | None) -> int | None:
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} tem de ser um número inteiro (recebi {raw!r}).") from exc


def load_settings(
    env: Mapping[str, str] | None = None, which: Callable[[str], str | None] = shutil.which
) -> Settings:
    if env is None:
        from dotenv import load_dotenv

        load_dotenv()
        env = os.environ
    token = (env.get("TELEGRAM_TOKEN") or "").strip()
    if not token:
        raise ConfigError("Falta TELEGRAM_TOKEN no .env (cria o bot no @BotFather).")
    claude_bin = None
    if (env.get("PRICE_CHECK") or "1").strip() != "0":
        claude_bin = (env.get("CLAUDE_BIN") or "").strip() or which("claude")
    return Settings(
        telegram_token=token,
        allowed_chat_id=_int(env, "ALLOWED_CHAT_ID", None),
        poll_interval=max(MIN_POLL_INTERVAL, _int(env, "POLL_INTERVAL", 120)),
        db_path=(env.get("DB_PATH") or "vintedbot.db").strip(),
        claude_bin=claude_bin,
        claude_model=(env.get("CLAUDE_MODEL") or "sonnet").strip(),
    )
