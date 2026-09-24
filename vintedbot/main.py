from __future__ import annotations

import asyncio
import logging
import sys

from vintedbot.config import ConfigError, load_settings
from vintedbot.storage import Storage
from vintedbot.telegram_bot import build_application
from vintedbot.vinted.client import VintedClient


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        settings = load_settings()
    except ConfigError as exc:
        sys.exit(f"Erro de configuração: {exc}")
    app = build_application(settings, Storage(settings.db_path), VintedClient())
    app.run_polling()


if __name__ == "__main__":
    main()
