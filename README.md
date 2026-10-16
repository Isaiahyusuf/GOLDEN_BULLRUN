# TRUMPTY ROYALE

Telegram group PvP game bot with points, duels, points protection,
weekly leaderboard snapshots, and manually settled weekly rewards.

## Requirements

- Python 3.12
- PostgreSQL
- Telegram bot token from BotFather

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` locally and set the real `BOT_TOKEN`.
Keep `.env` private and never commit it.

For PostgreSQL, set `DATABASE_URL` to a valid PostgreSQL connection URL.
The application converts standard `postgres://` and `postgresql://`
URLs to the asyncpg driver where necessary.

Run locally with:

```bash
python -m app.main
```

## Railway deployment

1. Create a Railway project.
2. Add a PostgreSQL service.
3. Deploy this repository as a separate worker service from the project root.
4. Set the worker start command to `python -m app.main`, or use the included
   Procfile.
5. Reference the PostgreSQL service's `DATABASE_URL` variable in the worker.
6. Add `BOT_TOKEN` in the worker's variables.
7. Set `PAYMENTS_ENABLED=false`.
8. Set optional configuration variables only when their values are known.
9. Deploy and inspect the worker logs for successful database initialization
   and the Telegram bot startup message.

Do not expose `.env`, bot tokens, database credentials, or RPC credentials.

## X raid missions

X missions link to an X post and ask a question about it. Players answer the
quiz in the group or the bot; a correct answer awards 200 competitive points
once per campaign, with up to three attempts. Points are awarded for the quiz
only; liking, reposting, replying to, or following an X account is not required.

An admin starts a quiz in any group where the bot is present with:

```text
/setraid https://x.com/name/status/POST_ID | Question about the post? | correct answer
```

Separate the post URL, question, and answer with `|`. The answer is matched
without case or extra-whitespace differences. Use `/stopraid` to end the active
quiz. No X app credentials, account connection, or API verification is needed.
Configured bot admins and admins of any active registered group can manage
quizzes in the group. Telegram must allow the bot to check its admin membership
in a group; make the bot an administrator there if group-admin verification fails.

## Group play

All active groups where the bot is present receive a rotating, lore-style Play
post with an arena button every 10 minutes. PvP and game commands work in each
group. Use `/pvp @username 100` to challenge a player; only that named player
can accept. The bot publishes its command menu in all groups and private chats,
so typing `/` shows the available commands. Purchases and payment checkout
remain in the bot's private chat.

## Payment and reward safety

- Live payments must remain disabled until payment verification is reviewed.
- Never treat a pending payment as a credited purchase.
- Weekly reward transfers are manual; the bot must not automatically transfer
  tokens to winners.
- Verify wallet addresses and transaction signatures before recording payouts.
- Review database backups and recovery procedures before production use.

## Tests

Run tests against a dedicated disposable test database, never the production
database:

```bash
DATABASE_URL="postgresql+asyncpg://localhost/trumpty_royale_test_clean" \
python -m pytest -q
```
