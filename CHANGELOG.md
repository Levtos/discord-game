# Changelog

## 1.0.1

- Exposes Discord Rich Presence artwork on the game sensor and media player.
- Prefers the large activity image and falls back to the small image when available.
- Keeps artwork empty for activities without Discord-provided assets; no external game database or credentials are added.

## 1.0.0

- Starts the independent Levtos distribution line at <https://github.com/Levtos/discord-game>.
- Keeps the Home Assistant integration domain `discord_game` unchanged for compatibility.
- Preserves the original MIT license and upstream attribution.
- Archives earlier fork/upstream version tags under `archive/upstream/*` in GitLab before mirroring to the new GitHub distribution repository.
