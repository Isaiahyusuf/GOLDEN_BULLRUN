# GOLDEN BULLRUN

_“…which coin will lead the way”_

Telegram game bot where every player is a Bull. Bulls compete in the Bull
Arena (group PvP), earn Bullrun Points, complete Bull Missions, climb the Top
Bulls leaderboard, and the winner of each completed battle is crowned
**The Bull That Ran**. Includes Bull Protection, weekly earned-point rankings,
and manually settled weekly rewards.

Rebrand note: only player-facing text changed. Database names, environment
variables, and internal identifiers (for example `points`, `duels`,
`gold_token_mint`, set via `GOLD_TOKEN_MINT`; the old `TRUMPTY_TOKEN_MINT` is still accepted as a fallback) are unchanged. Wins are derived from settled battles
(`duels.status = 'settled'` and `duels.winner_id`), so no migration is needed.

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

X missions link to an X post and ask a question about it. Before points can be
awarded, players must connect their X account, Like and Repost the campaign
post, Reply to it, Follow its author, and answer the quiz correctly. A
successful claim awards 200 Bullrun Points once per campaign. Incorrect
answers allow up to three attempts; incomplete engagement does not consume an
answer attempt. X access failures do not award points.

Weekly reward rankings are based on gross eligible points awarded during the
week: welcome bonuses, quiz rewards, daily rewards, duel activity rewards, and
duel prizes. Spending points does not reduce this score. Timeout refunds and
automatic weekly-reset adjustments are not counted as earnings.

An admin starts a quiz in any group where the bot is present with:

```text
/setraid https://x.com/name/status/POST_ID | Question about the post? | correct answer
```

Separate the post URL, question, and answer with `|`. The answer is matched
without case or extra-whitespace differences. Use `/stopraid` to end the active
quiz. Players connect from the bot's private chat by opening `/start connectx`;
`/unlinkx` disconnects the linked account and deletes its stored tokens.

### X OAuth setup

X verification requires an X developer app configured for OAuth 2.0
Authorization Code with PKCE, a public HTTPS callback URL ending in
`/x/oauth/callback`, and permission to read users, posts, likes, follows, and
offline access. Configure these Railway variables on the worker:

- `X_API_CLIENT_ID`
- `X_API_CLIENT_SECRET` (leave blank only for a public OAuth client)
- `X_API_REDIRECT_URI` (must exactly match the X app callback URL)
- `X_API_TOKEN_ENCRYPTION_KEY` (a Fernet key generated privately)

Set the X app's callback URL to the Railway worker's public HTTPS domain plus
`/x/oauth/callback`. Keep the encryption key and client secret in Railway
variables; never commit or send them in chat. The X API plan must permit the
likes, reposts, follows, post lookup, and recent-search endpoints the verifier
uses; X may charge for API usage. If X is not configured or an action cannot be
verified, quiz points are not awarded.

Generate the encryption key locally with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
Configured bot admins and admins of any active registered group can manage
quizzes in the group. Telegram must allow the bot to check its admin membership
in a group; make the bot an administrator there if group-admin verification fails.

## Group play

All active groups where the bot is present receive a rotating, lore-style Play
post with an arena button every 10 minutes. PvP and game commands work in each
registered group. Use `/pvp @username 100` to challenge a player; only that
named player can accept or decline within 60 seconds. If the opponent is not
registered, the group prompt includes a button to open the bot and tap Start.
On acceptance, each player's stake is reserved. The battle starts with 100 HP
each and alternates turns. ATTACK deals 20 damage; each player can use GUARD
once to reduce the next hit by 10. The first player is chosen at random; the
first to 0 HP loses. Either player can forfeit. An inactive battle expires
after 15 minutes and refunds both stakes.
The bot publishes its command menu in all groups and private chats, so typing
`/` shows the available commands. Purchases and payment checkout remain in the
bot's private chat.

The bot deletes its previous tracked arena post before publishing the next
one. Give the bot permission to delete its own messages in each group.

When no X quiz is active, the bot mentions that group's administrators in a
raid-start reminder every 15 minutes, replacing its previous reminder in that
group. It also posts the detailed How to Play guide to every active group once
per hour.

Twenty-four hours before each Monday 00:00 UTC weekly point reset, the bot posts
one Points Protection reminder in each active group. Its button opens the bot's
private protection screen, where the existing purchase checkout can be started.

## Payment and reward safety

- Live payments must remain disabled until payment verification is reviewed.
- Never treat a pending payment as a credited purchase.
- If signature verification fails, users can retry with a corrected signature
  or check the existing pending payment from the private shop; neither action
  creates another purchase or payment request.
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
