# Changelog

## 1.0.3

- Reuses the Media Art Wrapper's gaming provider chain instead of maintaining a Steam-only resolver in Discord Game.
- Database artwork is preferred for game titles; Discord Rich Presence artwork remains a fallback.
- The integration continues to work without Media Art Wrapper and leaves artwork empty when no source resolves.

## 1.0.2

- Adds a cached Steam Store artwork fallback for playing activities without Discord Rich Presence assets.
- Keeps Discord-provided artwork as the preferred source and requires no new credentials.
- Leaves artwork empty when the title cannot be matched safely or the provider is unavailable.

## 1.0.1

- Exposes Discord Rich Presence artwork on the game sensor and media player.
- Prefers the large activity image and falls back to the small image when available.
- Keeps artwork empty for activities without Discord-provided assets; no external game database or credentials are added.

## 1.0.0

- Starts the independent Levtos distribution line at <https://github.com/Levtos/discord-game>.
- Keeps the Home Assistant integration domain `discord_game` unchanged for compatibility.
- Preserves the original MIT license and upstream attribution.
- Archives earlier fork/upstream version tags under `archive/upstream/*` in GitLab before mirroring to the new GitHub distribution repository.
