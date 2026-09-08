# Discord Game — Home Assistant Integration

Track Discord users' online status and currently played games in Home Assistant. For each monitored user the integration creates a status sensor, a game sensor, an avatar sensor, a username sensor and a media player entity, all grouped under one device per user.

The bot token is compatible with Home Assistant's built-in Discord notification integration, so both can share a single bot.

## Setup

1. Create a Discord application at <https://discord.com/developers/applications>, add a bot, disable **Public Bot**, enable all three **Privileged Gateway Intents** (Presence, Server Members, Message Content), and copy the bot token.
2. Invite the bot to your server using
   `https://discord.com/api/oauth2/authorize?client_id=[CLIENT_ID]&scope=bot&permissions=0`
3. In Home Assistant: **Settings → Devices & Services → Add Integration → Discord Game**, paste the token, pick an avatar image format (`webp` recommended; use `png` for Safari / iOS), then select the users (and optionally channels) to track.

Full instructions: <https://github.com/Levtos/discord-game>

## Game artwork

Automatic chain: Steam → PlayStation public game catalog → user-owned local
image → Discord Rich Presence. No extra credentials or integration are required.
Current Steam Store headers are preferred; online artwork URLs are cached for
24 hours, misses for five minutes, and refreshed on later presence updates.
PlayStation requires an exact full-game page match and may miss catalog titles.

For Hearthstone, place your image at `<config>/www/discord_game/hearthstone.webp`.
Other titles use lowercase canonical names with hyphens; webp/png/jpg/jpeg are
supported. Files are user-managed and must not contain private content because
HA serves `www` publicly. Missing artwork degrades cleanly. See the README for
details and migration from retired artwork credentials.
