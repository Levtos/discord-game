# Discord Game — Home Assistant Integration

Track Discord users' online status and currently played games in Home Assistant. For each monitored user the integration creates a status sensor, a game sensor, an avatar sensor, a username sensor and a media player entity, all grouped under one device per user.

The bot token is compatible with Home Assistant's built-in Discord notification integration, so both can share a single bot.

## Setup

1. Create a Discord application at <https://discord.com/developers/applications>, add a bot, disable **Public Bot**, enable all three **Privileged Gateway Intents** (Presence, Server Members, Message Content), and copy the bot token.
2. Invite the bot to your server using
   `https://discord.com/api/oauth2/authorize?client_id=[CLIENT_ID]&scope=bot&permissions=0`
3. In Home Assistant: **Settings → Devices & Services → Add Integration → Discord Game**, paste the token, pick an avatar image format (`webp` recommended; use `png` for Safari / iOS), then select the users (and optionally channels) to track.

Full instructions: <https://github.com/Levtos/discord_game>
