TAGLINE = "…which coin will lead the way"

TOKEN_SYMBOL = "$GOLD"
TOKEN_ADDRESS = "HHegCiT5d2i6oUnvBoxPP9dsYjJt1dKoxWw3rWegpump"

LINKS = {
    "🌐 WEBSITE": "https://goldenbullrun.org",
    "𝕏 COMMUNITY": "https://x.com/golden_bullrun",
    "💬 TELEGRAM": "https://t.me/GoldenBullrun2024",
    "👽 REDDIT": "https://www.reddit.com/r/GoldenBullrunCTO2",
    "📈 CHART": f"https://dexscreener.com/solana/{TOKEN_ADDRESS}",
}

# Cosmetic ranks derived from Bullrun Points; they never affect the economy.
BULL_RANKS = (
    (50_000, "🏆 Bull Market Legend"),
    (25_000, "🥇 Golden Bull"),
    (15_000, "🔥 Raging Bull"),
    (10_000, "🐂 Bull"),
    (0, "🐄 Calf"),
)


def bull_rank(points: int) -> str:
    for threshold, title in BULL_RANKS:
        if points >= threshold:
            return title
    return BULL_RANKS[-1][1]


TOKEN_TEXT = (
    f"🪙 <b>{TOKEN_SYMBOL} — THE GOLDEN BULLRUN TOKEN</b>\n"
    f"<i>“{TAGLINE}”</i>\n\n"
    "The community token behind Golden Bullrun on Solana.\n\n"
    "<b>Contract address</b> (tap to copy):\n"
    f"<code>{TOKEN_ADDRESS}</code>\n\n"
    "🐂 In the game, Bulls compete for Bullrun Points. Bullrun Points are "
    "game points only: they have no cash value and are not the token.\n\n"
    "⚠️ Always verify the contract address above and only use the official "
    "links below. Never share a seed phrase or private key. Nothing here is "
    "financial advice."
)
