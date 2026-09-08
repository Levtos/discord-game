# ADR 0001: Discord Game owns game artwork resolution

- Status: accepted; provider decision amended 2026-09-08
- Original decision: 2026-08-23
- Issue: https://github.com/Levtos/discord-game/issues/5
- Superseding scope: https://github.com/Levtos/discord-game/issues/5#issuecomment-5590899728

## Decision

Discord supplies the detected game title. Discord Game resolves one canonical
`game_image_url` shared by the game sensor and media player, in this order:

1. Steam public Store API: exact normalized full-game title or a small explicit
   alias/verified app-ID mapping.
2. Public PlayStation game product metadata, without authentication.
3. A user-owned local image under `<config>/www/discord_game/`.
4. Discord Rich Presence large/small asset.
5. No artwork.

This replaces the earlier IGDB → SteamGridDB → Battle.net → Steam decision.
Those providers and their credential UI are removed. Config-entry version 2
drops the retired keys from both data and options while retaining Discord
credentials, members, channels and feature options. No other HA integration,
PSNAWP installation or additional credentials are required.

## Steam identity and current artwork

Normalization removes trademark marks, normalizes Unicode/case and punctuation.
Aliases are explicit: Overwatch / Overwatch 2 / Overwatch2 → app 2357570;
Anno 117 / Anno 117: Pax Romana → app 3274580. Unknown titles use storesearch.
Only one exact normalized app match is accepted. Appdetails must confirm
success, matching app ID, matching canonical name and `type=game`.
DLC, demos, music, bundles, ambiguous matches and prefix-only results fail closed.
A confirmed app ID is reused for later metadata refreshes during this runtime.

Prefer `header_image`, then `capsule_image`, then `capsule_imagev5`.
Keep the returned URL and its version/query unchanged. Do not synthesize static
library-CDN URLs or prefer library assets.

Public API evidence captured 2026-09-08:

| App | Name/type | Header field | Other fields |
| --- | --- | --- | --- |
| 2357570 | Overwatch® / game | `header_alt_assets_22.jpg?t=1788890347` | capsule uses alt_assets_22; both library fields absent |
| 3274580 | Anno 117: Pax Romana / game | `header_alt_assets_4.jpg?t=1788366062` | capsule uses alt_assets_4; both library fields absent |

Sources: [Overwatch appdetails](https://store.steampowered.com/api/appdetails?appids=2357570&l=english&cc=de),
[Anno appdetails](https://store.steampowered.com/api/appdetails?appids=3274580&l=english&cc=de).
The search also returned expansions/campaign products; this is why a prefix
match and an unverified search thumbnail are insufficient.

These responses establish that the header follows the current Store alternate
asset set. They do not prove which season an artist depicted or guarantee that
Valve/publishers update every field simultaneously. The header is the practical
current Store image, not a claim to a separate Hero API.

## PlayStation access decision

Reference reviewed: HA Core dev commit
`368adbe0fbb47c3c6f16351ba82b16888c6ed493`,
[helpers.py](https://github.com/home-assistant/core/blob/368adbe0fbb47c3c6f16351ba82b16888c6ed493/homeassistant/components/playstation_network/helpers.py),
[media_player.py](https://github.com/home-assistant/core/blob/368adbe0fbb47c3c6f16351ba82b16888c6ed493/homeassistant/components/playstation_network/media_player.py),
[manifest](https://github.com/home-assistant/core/blob/368adbe0fbb47c3c6f16351ba82b16888c6ed493/homeassistant/components/playstation_network/manifest.json).

HA uses PSNAWP 3.0.3; its presence data prefers `conceptIconUrl` and then
`npTitleIconUrl`. The media player projects that session image. This is
authenticated presence, not an exposed general title-search service.
The reviewed setup/runtime coordinators provide no public credential-sharing
or general search contract for another integration.

[PSNAWP search](https://psnawp.readthedocs.io/en/latest/generated/psnawp_api.psnawp.html)
supports `SearchDomain.FULL_GAMES`, separate from add-ons, through its
authenticated client. Game/title details require title identifiers; they are
not a keyless replacement for title search. Reaching into another integration's
runtime_data or config-entry secrets is rejected.

The public Store search page returned no server-rendered results. A small
anonymous query against its browser GraphQL endpoint returned HTTP 400,
`Query not whitelisted`. Depending on changing frontend persisted-query hashes
would introduce another private API contract.

The smaller alternative implemented in this release uses
`https://www.playstation.com/en-us/games/<slug>/`: only published JSON-LD
`Product` records with an exact normalized title, `category=Full Game`, and
an `image.api.playstation.com` image qualify. Layout selectors, executing
JavaScript and generic og:image scraping are unnecessary. Slugs are normalized
titles with a small explicit punctuation exception for Demon's Souls.
Conflicting images, missing metadata, changed titles, HTTP failures and timeouts
are misses, never guessed artwork.

Public unauthenticated evidence on 2026-09-08:
[Bloodborne](https://www.playstation.com/en-us/games/bloodborne/),
[Demon's Souls](https://www.playstation.com/en-us/games/demons-souls/) and
[Astro Bot](https://www.playstation.com/en-us/games/astro-bot/) returned HTTP 200,
exact Product names, Full Game categories and Sony image URLs. A nonexistent
slug returned 404.

This is a bounded direct catalog lookup, not exhaustive PSN Store search.
Titles without a matching public page/slug can miss even when sold on PSN.
Sony can change the published metadata. This explicit limitation is preferable
to private cross-integration coupling; local and Discord fallbacks remain usable.

## Cache, lifecycle and local files

- Online URL results: 24-hour positive cache, five-minute negative cache,
  bounded to 256 titles. Confirmed app-ID cache is also bounded to 256.
  No downloaded image snapshot, disk cache or long-lived token exists.
- Expiration is checked on the next presence lookup; there is no periodic
  background poll while Discord sends no events. Restart clears online caches.
- Identical canonical titles share one lookup, even if a waiting task is
  cancelled. Each provider has a ten-second total timeout; errors stay isolated.
- Presence publishes game/status immediately; artwork finishes in a background
  task. Every result checks its activity generation. Game end clears the image
  immediately; unload invalidates generations and cancels artwork work.
- Local files use canonical lowercase titles, punctuation/spaces as hyphens,
  with webp → png → jpg → jpeg extension preference. Example:
  `<config>/www/discord_game/hearthstone.webp` becomes
  `/local/discord_game/hearthstone.webp?v=<mtime>`.
- File checks run in the HA executor, restrict resolved files to that directory,
  and are repeated even on an online-cache miss. Adding/removing/replacing a
  local image is detected on the next presence lookup. Missing files degrade.
- No copyrighted artwork is distributed in this repository. Users provide
  images they are entitled to use; HA's /local directory is publicly served.

## Technical and live gates

Mocked provider and actual lifecycle-module tests establish technical behavior.
They do not establish HA frontend rendering or game-specific live acceptance.
Installation, reload, restart, Overwatch/Anno/Hearthstone display, game changes,
game end and clean logs remain Benni's gate. Issue #10 tracks the independent
HACS restored-update-entity investigation; no update entity belongs to this
integration's sensor/media-player platforms.
