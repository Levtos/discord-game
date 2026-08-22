# Discord Game — Home Assistant Integration

Repository: <https://github.com/Levtos/discord-game>

Track Discord users' online status and currently played games directly in Home Assistant. For each monitored user the integration creates:

- **Status sensor** — online / idle / dnd / offline
- **Game sensor** — currently played game, or *No Game* when idle
- **Avatar sensor** — profile picture URL
- **Username sensor** — global Discord display name
- **Media player entity** — reflects the active game as a playback source (state: playing / idle / off)

All entities are grouped under one device per user. The user's avatar is used as the entity picture throughout.

This repository is the independently maintained Levtos variant of the Discord Game Home Assistant integration. The `v1.0.0` release starts the standalone Levtos distribution line after the GitLab migration and fork-history archival.

> Special thanks to the developers and contributors who originally conceived and built the foundation this integration is based on.

---

## Setup

### 1 — Create a Discord bot

1. Go to <https://discord.com/developers/applications>
2. Click **New Application**, give it a name and confirm
3. Open the **Installation** tab and set the install link to *None*
4. Open the **Bot** tab and click **Add Bot**
5. Disable **Public Bot**
6. Under **Privileged Gateway Intents** enable all three intents (Presence, Server Members, Message Content)
7. Click **Save Changes**
8. Under **Token** click **Reset Token**, copy and store it securely — you will need it during integration setup

### 2 — Invite the bot to your server

1. Open the **General Information** tab and copy the **Client ID**
2. Open this URL in your browser (replace `[CLIENT_ID]`):
   ```
   https://discord.com/api/oauth2/authorize?client_id=[CLIENT_ID]&scope=bot&permissions=0
   ```
3. Select your server and click **Authorize**

The bot must be a member of the server where the users you want to track are active.

### 3 — Add the integration in Home Assistant

1. Go to **Settings → Devices & Services → Add Integration** and search for *Discord Game*
2. Paste your bot token
3. Select the avatar image format (`webp` recommended; use `png` for Safari / iOS)
4. On the next screen select the users to track and optionally channels for reaction tracking
5. Confirm — one device per user will appear with all sensors and the media player entity

---

## Notes

- **Safari / iOS:** Set image format to `png` — Safari does not support `webp`
- **Game artwork:** The game sensor and media player use the large image from Discord Rich Presence, with the small image as fallback. Games without a Discord-provided asset have no picture.
- **Channel reactions:** Selecting a channel creates a sensor that shows the display name of the last user who added a reaction — useful for simple interaction tracking
- **Shared token:** The bot token is compatible with Home Assistant's built-in Discord notification integration, so both functions can run under the same bot
