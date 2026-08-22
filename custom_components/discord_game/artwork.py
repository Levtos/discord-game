"""Resolve game artwork without requiring another Home Assistant integration."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import logging
import re
import time
from typing import Any
from urllib.parse import quote, urlencode


_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10.0
POSITIVE_CACHE_TTL = 86_400.0
NEGATIVE_CACHE_TTL = 300.0

TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
IGDB_GAMES_URL = "https://api.igdb.com/v4/games"
IGDB_COVERS_URL = "https://api.igdb.com/v4/covers"
STEAMGRIDDB_SEARCH_URL = "https://www.steamgriddb.com/api/v2/search/autocomplete/{term}"
STEAMGRIDDB_GRIDS_URL = "https://www.steamgriddb.com/api/v2/grids/game/{game_id}"
STEAM_STORE_SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
STEAM_APP_DETAILS_URL = "https://store.steampowered.com/api/appdetails"

_EXTERNAL_IMAGE_WITH_SIZE = re.compile(
    r"^https://cdn\.discordapp\.com/app-assets/\d+/mp:external/([^/]+)/(https/.+_\d+\.(?:png|jpg|jpeg|webp))$"
)
_EXTERNAL_IMAGE = re.compile(
    r"^https://cdn\.discordapp\.com/app-assets/\d+/mp:external/([^/]+)/(https/.+\.(?:png|jpg|jpeg|webp))$"
)
_OG_IMAGE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']'
    r'|<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    re.IGNORECASE,
)

_BLIZZARD_GAME_PAGES = {
    "overwatch": "https://overwatch.blizzard.com/en-us/",
    "overwatch 2": "https://overwatch.blizzard.com/en-us/",
    "hearthstone": "https://hearthstone.blizzard.com/en-us/",
    "world of warcraft": "https://worldofwarcraft.blizzard.com/en-us/",
    "world of warcraft classic": "https://worldofwarcraft.blizzard.com/en-us/",
    "wow": "https://worldofwarcraft.blizzard.com/en-us/",
    "wow classic": "https://worldofwarcraft.blizzard.com/en-us/",
    "diablo iv": "https://diablo4.blizzard.com/en-us/",
    "diablo 4": "https://diablo4.blizzard.com/en-us/",
    "diablo iii": "https://diablo3.blizzard.com/en-us/",
    "diablo 3": "https://diablo3.blizzard.com/en-us/",
    "diablo ii resurrected": "https://diablo2.blizzard.com/en-us/",
    "diablo 2 resurrected": "https://diablo2.blizzard.com/en-us/",
    "diablo immortal": "https://diabloimmortal.blizzard.com/en-us/",
    "starcraft": "https://starcraft.blizzard.com/en-us/",
    "starcraft ii": "https://starcraft2.blizzard.com/en-us/",
    "starcraft 2": "https://starcraft2.blizzard.com/en-us/",
    "heroes of the storm": "https://heroesofthestorm.blizzard.com/en-us/",
    "hots": "https://heroesofthestorm.blizzard.com/en-us/",
    "warcraft iii": "https://warcraft3.blizzard.com/en-us/",
    "warcraft 3": "https://warcraft3.blizzard.com/en-us/",
}


def normalize_discord_image_url(url: str | None) -> str | None:
    """Return an HA-fetchable URL for a nextcord Discord asset URL."""
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return None
    if "mp:external" not in url:
        return url

    match = _EXTERNAL_IMAGE_WITH_SIZE.match(url)
    if match:
        return (
            f"https://media.discordapp.net/external/{match.group(1)}/{match.group(2)}"
        )

    match = _EXTERNAL_IMAGE.match(url)
    if match:
        return (
            f"https://media.discordapp.net/external/{match.group(1)}/{match.group(2)}"
        )

    return url


def activity_image_url(activity: Any) -> str | None:
    """Return the best image exposed by a Discord activity."""
    for attribute in ("large_image_url", "small_image_url"):
        image_url = normalize_discord_image_url(getattr(activity, attribute, None))
        if image_url:
            return image_url
    return None


def normalize_game_title(title: str | None) -> str:
    """Normalize a game title for provider matching and cache keys."""
    if not isinstance(title, str):
        return ""
    title = re.sub(r"[\u00a9\u00ae\u2122]", "", title.casefold())
    return re.sub(r"[^\w]+", " ", title, flags=re.UNICODE).strip()


def _title_score(query: str, candidate: str) -> int:
    """Score a provider result without accepting an unrelated title."""
    query_key = normalize_game_title(query)
    candidate_key = normalize_game_title(candidate)
    if not query_key or not candidate_key:
        return -1
    if candidate_key == query_key:
        return 100
    if candidate_key.startswith(f"{query_key} "):
        return 90
    if query_key.startswith(f"{candidate_key} "):
        return 80
    if query_key in candidate_key or candidate_key in query_key:
        return 60
    return -1


def _select_result(game_name: str, items: Any) -> Mapping[str, Any] | None:
    """Select the safest sufficiently matching provider result."""
    if not isinstance(items, list):
        return None
    matches = [
        (score, item)
        for item in items
        if isinstance(item, Mapping)
        for score in [_title_score(game_name, str(item.get("name", "")))]
        if score >= 0
    ]
    return max(matches, key=lambda match: match[0])[1] if matches else None


def _http_url(value: Any) -> str | None:
    """Return an HTTP(S) URL from untrusted provider data."""
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value
    return None


class GameArtworkResolver:
    """Resolve and cache game artwork through built-in game providers."""

    def __init__(
        self,
        session: Any,
        *,
        igdb_client_id: str = "",
        igdb_client_secret: str = "",
        steamgriddb_api_key: str = "",
        timeout: float = REQUEST_TIMEOUT,
    ) -> None:
        self._session = session
        self._igdb_client_id = igdb_client_id.strip()
        self._igdb_client_secret = igdb_client_secret.strip()
        self._steamgriddb_api_key = steamgriddb_api_key.strip()
        self._timeout = timeout
        self._cache: dict[str, tuple[str | None, float]] = {}
        self._inflight: dict[str, asyncio.Task[str | None]] = {}
        self._igdb_token: tuple[str, float] | None = None

    async def async_resolve(self, game_name: str | None) -> str | None:
        """Return cached artwork or resolve it once for a normalized title."""
        cache_key = normalize_game_title(game_name)
        if not cache_key:
            return None

        now = time.monotonic()
        cached = self._cache.get(cache_key)
        if cached and cached[1] > now:
            return cached[0]

        task = self._inflight.get(cache_key)
        if task is None:
            task = asyncio.create_task(self._async_fetch(game_name or ""))
            self._inflight[cache_key] = task

        try:
            result = await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.debug("Game artwork lookup failed for %s", cache_key, exc_info=True)
            result = None
        finally:
            if self._inflight.get(cache_key) is task:
                self._inflight.pop(cache_key, None)

        ttl = POSITIVE_CACHE_TTL if result else NEGATIVE_CACHE_TTL
        self._cache[cache_key] = (result, time.monotonic() + ttl)
        return result

    async def _async_fetch(self, game_name: str) -> str | None:
        providers = []
        if self._igdb_client_id and self._igdb_client_secret:
            providers.append(("IGDB", self._async_resolve_igdb))
        if self._steamgriddb_api_key:
            providers.append(("SteamGridDB", self._async_resolve_steamgriddb))
        providers.extend(
            (
                ("Battle.net", self._async_resolve_battlenet),
                ("Steam", self._async_resolve_steam),
            )
        )

        for provider_name, provider in providers:
            try:
                image_url = _http_url(await provider(game_name))
            except Exception:
                _LOGGER.debug(
                    "%s artwork lookup failed for %r",
                    provider_name,
                    game_name,
                    exc_info=True,
                )
                continue
            if image_url:
                _LOGGER.debug(
                    "Game artwork for %r resolved by %s", game_name, provider_name
                )
                return image_url
        return None

    async def _async_resolve_igdb(self, game_name: str) -> str | None:
        token = await self._async_get_igdb_token()
        if not token:
            return None
        headers = {
            "Client-ID": self._igdb_client_id,
            "Authorization": f"Bearer {token}",
        }
        safe_title = re.sub(r'["\\;]+', " ", game_name).strip()
        games = await self._async_post_json(
            IGDB_GAMES_URL,
            headers=headers,
            data=f'search "{safe_title}"; fields id,name,cover; limit 10;',
        )
        game = _select_result(game_name, games)
        cover_id = game.get("cover") if game else None
        if not isinstance(cover_id, int):
            return None

        covers = await self._async_post_json(
            IGDB_COVERS_URL,
            headers=headers,
            data=f"fields image_id; where id = {cover_id};",
        )
        if (
            not isinstance(covers, list)
            or not covers
            or not isinstance(covers[0], Mapping)
        ):
            return None
        image_id = covers[0].get("image_id")
        if not isinstance(image_id, str) or not image_id:
            return None
        return f"https://images.igdb.com/igdb/image/upload/t_1080p/{image_id}.jpg"

    async def _async_get_igdb_token(self) -> str | None:
        now = time.monotonic()
        if self._igdb_token and self._igdb_token[1] > now + 60:
            return self._igdb_token[0]
        payload = await self._async_post_json(
            TWITCH_TOKEN_URL,
            params={
                "client_id": self._igdb_client_id,
                "client_secret": self._igdb_client_secret,
                "grant_type": "client_credentials",
            },
        )
        if not isinstance(payload, Mapping):
            return None
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            return None
        expires_in = payload.get("expires_in", 3600)
        try:
            expires_at = now + float(expires_in)
        except (TypeError, ValueError):
            expires_at = now + 3600
        self._igdb_token = (token, expires_at)
        return token

    async def _async_resolve_steamgriddb(self, game_name: str) -> str | None:
        headers = {"Authorization": f"Bearer {self._steamgriddb_api_key}"}
        search = await self._async_get_json(
            STEAMGRIDDB_SEARCH_URL.format(term=quote(game_name, safe="")),
            headers=headers,
        )
        items = (
            search.get("data")
            if isinstance(search, Mapping) and search.get("success")
            else None
        )
        game = _select_result(game_name, items)
        game_id = game.get("id") if game else None
        if not isinstance(game_id, int):
            return None

        grids_url = STEAMGRIDDB_GRIDS_URL.format(game_id=game_id)
        grids = await self._async_get_json(
            grids_url,
            headers=headers,
            params={"limit": "1", "dimensions": "600x900,660x930"},
        )
        items = (
            grids.get("data")
            if isinstance(grids, Mapping) and grids.get("success")
            else None
        )
        if not isinstance(items, list) or not items:
            grids = await self._async_get_json(
                grids_url,
                headers=headers,
                params={"limit": "1"},
            )
            items = (
                grids.get("data")
                if isinstance(grids, Mapping) and grids.get("success")
                else None
            )
        if (
            not isinstance(items, list)
            or not items
            or not isinstance(items[0], Mapping)
        ):
            return None
        return _http_url(items[0].get("url"))

    async def _async_resolve_battlenet(self, game_name: str) -> str | None:
        page_url = _BLIZZARD_GAME_PAGES.get(normalize_game_title(game_name))
        if not page_url:
            return None
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; discord-game-ha/1.0.4; "
                "+https://github.com/Levtos/discord-game)"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
        async with self._session.get(
            page_url,
            headers=headers,
            timeout=self._timeout,
            allow_redirects=True,
        ) as response:
            if response.status != 200:
                return None
            html = await response.text(encoding="utf-8", errors="ignore")
        match = _OG_IMAGE.search(html)
        return (
            _http_url((match.group(1) or match.group(2) or "").strip())
            if match
            else None
        )

    async def _async_resolve_steam(self, game_name: str) -> str | None:
        search = await self._async_get_json(
            STEAM_STORE_SEARCH_URL,
            params={"term": game_name, "l": "english", "cc": "de"},
        )
        result = _select_result(
            game_name, search.get("items") if isinstance(search, Mapping) else None
        )
        if result is None:
            return None

        fallback_url = _http_url(result.get("tiny_image"))
        app_id = result.get("id")
        if not isinstance(app_id, (int, str)) or not str(app_id).isdigit():
            return fallback_url

        details = await self._async_get_json(
            STEAM_APP_DETAILS_URL,
            params={"appids": str(app_id), "l": "english"},
        )
        app_details = details.get(str(app_id)) if isinstance(details, Mapping) else None
        data = app_details.get("data") if isinstance(app_details, Mapping) else None
        if isinstance(data, Mapping):
            for field in (
                "library_capsule",
                "library_capsulev5",
                "header_image",
                "capsule_image",
            ):
                if image_url := _http_url(data.get(field)):
                    return image_url
        return fallback_url

    async def _async_get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        query_url = f"{url}?{urlencode(params)}" if params else url
        async with self._session.get(
            query_url,
            headers=headers,
            timeout=self._timeout,
        ) as response:
            if response.status != 200:
                return None
            return await response.json(content_type=None)

    async def _async_post_json(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        data: str | None = None,
    ) -> Any:
        async with self._session.post(
            url,
            params=params,
            headers=headers,
            data=data,
            timeout=self._timeout,
        ) as response:
            if response.status != 200:
                return None
            return await response.json(content_type=None)
