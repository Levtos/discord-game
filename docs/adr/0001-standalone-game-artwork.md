# ADR 0001: Discord Game owns game artwork resolution

- Status: accepted
- Date: 2026-08-23
- Issue: https://github.com/Levtos/discord-game/issues/5

## Decision

`discord-game` resolves game artwork within its own integration. It does not
import, configure, or require Media Art Wrapper.

The ordered provider chain is:

1. IGDB, when Twitch client credentials are configured.
2. SteamGridDB, when an API key is configured.
3. Battle.net public game pages for known Blizzard titles, without a key.
4. Steam's public store API, without a key.
5. Discord Rich Presence artwork as the final fallback.

The resolver caches normalized titles, coalesces concurrent requests, isolates
provider failures, and exposes one shared image URL to the game sensor and media
player. Home Assistant installation and live acceptance remain a separate gate.

## Reason

Media Art Wrapper is no longer an active runtime component because its primary
music use case is available natively in Music Assistant. Requiring that
integration only for Discord game covers would create an unnecessary deployment
dependency and would leave artwork unavailable on installations where the
wrapper is intentionally absent.
