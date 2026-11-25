# VintedBot

Personal bot that monitors Vinted searches and sends a Telegram alert for every new listing.

> ⚠️ Uses Vinted's internal (unofficial) API (`https://api.vinted.<tld>/svc-catalogue/items`).

## Setup (Windows)

1. Install Python 3.12: `winget install -e --id Python.Python.3.12`
2. `python -m venv .venv` and `.venv\Scripts\Activate.ps1`
3. `python -m pip install -r requirements.txt`
4. Create a Telegram bot with [@BotFather](https://t.me/BotFather) and copy the token.
5. `copy .env.example .env` and fill in `TELEGRAM_TOKEN`.
6. `python -m vintedbot.main`, send `/id` to the bot, put the number in `ALLOWED_CHAT_ID` in `.env` and restart.

## Setup (Linux / Raspberry Pi)

Requires Python 3 with `venv` (`sudo apt install python3-venv`) and, on a Pi, a 64-bit OS.

1. Copy the `.env` (and `vintedbot.db`, to keep your searches) into the project folder.
2. `./vintedbot.sh`: creates the `.venv` on first run and starts the bot. Ctrl+C to stop.
3. `./vintedbot.sh install`: installs the `systemd` service, which starts on boot and restarts the bot if it crashes.
   - Logs: `journalctl -u vintedbot -f` · Status: `sudo systemctl status vintedbot`
4. Update: `./deploy.sh` runs `git pull`, installs dependencies if they changed, runs the tests and only restarts the service if they pass. `./deploy.sh --force` restarts even with no changes.

> Only **one** bot can run with the same token: stop the one on your PC before starting the one on the Pi (otherwise Telegram returns `409 Conflict`).

## Usage

1. On Vinted, run a search with whatever filters you want (brand, size, price, condition…).
2. Copy the URL and send `/add <url> [name]` to the bot.
3. From then on you get an alert for every new listing (up to 10 per cycle; the rest are summarised).

Commands: `/add`, `/list`, `/pause <id>`, `/resume <id>`, `/remove <id>`, `/status`, `/id`.

**Price check:** if [Claude Code](https://claude.com/claude-code) (`claude`) is installed and logged in, each alert gets a «💡 Check price» button. The bot searches Vinted for listings with the same title and asks Claude for a verdict (good deal / fair price / overpriced) with a fair price range. Takes 10–30 s, uses your Claude account quota, and only works for alerts received since the bot last started. Disable it with `PRICE_CHECK=0` in `.env`.

To test the Vinted connection without Telegram:
`python -m vintedbot.vinted.client "<search url>"`

## Tests

`python -m pytest`
