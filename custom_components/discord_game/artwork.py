"""Resolve game artwork from Discord Rich Presence and public game metadata."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode


_LOGGER = logging.getLogger(__name__)

STEAM_STORE_SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
STEAM_APP_DETAILS_URL = "https://store.steampowered.com/api/appdetails"
STEAM_REQUEST_TIMEOUT = 5.0


_EXTERNAL_IMAGE_WITH_SIZE = re.compile(
    r"^https://cdn\.discordapp\.com/app-assets/\d+/mp:external/([^/]+)/(https/.+_\d+\.(?:png|jpg|jpeg|webp))$"
)
_EXTERNAL_IMAGE = re.compile(
    r"^https://cdn\.discordapp\.com/app-assets/\d+/mp:external/([^/]+)/(https/.+\.(?:png|jpg|jpeg|webp))$"
)


def normalize_discord_image_url(url: str | None) -> str | None:
    """Return an HA-fetchable URL for a nextcord Discord asset URL."""
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return None
    if "mp:external" not in url:
        return url

    match = _EXTERNAL_IMAGE_WITH_SIZE.match(url)
    if match:
        return f"https://media.discordapp.net/external/{match.group(1)}/{match.group(2)}"

    match = _EXTERNAL_IMAGE.match(url)
    if match:
        return f"https://media.discordapp.net/external/{match.group(1)}/{match.group(2)}"

    return url


def activity_image_url(activity: Any) -> str | None:
    """Return the best image exposed by a Discord activity."""
    for attribute in ("large_image_url", "small_image_url"):
        image_url = normalize_discord_image_url(getattr(activity, attribute, None))
        if image_url:
            return image_url
    return None


def normalize_game_title(title: str | None) -> str:
    """Normalize a game title for conservative provider matching."""
    if not isinstance(title, str):
        return ""
    title = re.sub(r"[\u00a9\u00ae\u2122]", "", title.casefold())
    return re.sub(r"[^\w]+", " ", title, flags=re.UNICODE).strip()


def _steam_title_score(query: str, candidate: str) -> int:
    """Score a Steam result without accepting an unrelated title."""
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


def _select_steam_result(game_name: str, items: Any) -> Mapping[str, Any] | None:
    """Select the safest sufficiently matching Steam search result."""
    if not isinstance(items, list):
        return None

    matches = [
        (score, item)
        for item in items
        if isinstance(item, Mapping)
        for score in [_steam_title_score(game_name, str(item.get("name", "")))]
        if score >= 0
    ]
    if not matches:
        return None
    return max(matches, key=lambda match: match[0])[1]


def _http_url(value: Any) -> str | None:
    """Return an HTTP(S) URL from untrusted provider data."""
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value
    return None


class SteamArtworkResolver:
    """Resolve and cache game artwork through the public Steam Store API."""

    def __init__(self, session: Any, timeout: float = STEAM_REQUEST_TIMEOUT) -> None:
        self._session = session
        self._timeout = timeout
        self._cache: dict[str, str | None] = {}
        self._inflight: dict[str, asyncio.Task[str | None]] = {}

    async def async_resolve(self, game_name: str | None) -> str | None:
        """Return cached artwork or resolve it once for a normalized title."""
        cache_key = normalize_game_title(game_name)
        if not cache_key:
            return None
        if cache_key in self._cache:
            return self._cache[cache_key]

        task = self._inflight.get(cache_key)
        if task is None:
            task = asyncio.create_task(self._async_fetch(game_name or ""))
            self._inflight[cache_key] = task

        try:
            result = await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.debug("Steam artwork lookup failed for %s", cache_key, exc_info=True)
            result = None
        finally:
            if self._inflight.get(cache_key) is task:
                self._inflight.pop(cache_key, None)

        self._cache[cache_key] = result
        return result

    async def _async_fetch(self, game_name: str) -> str | None:
        search_payload = await self._async_get_json(
            STEAM_STORE_SEARCH_URL,
            {"term": game_name, "l": "english", "cc": "de"},
        )
        if not isinstance(search_payload, Mapping):
            return None

        result = _select_steam_result(game_name, search_payload.get("items"))
        if result is None:
            return None

        fallback_url = _http_url(result.get("tiny_image"))
        app_id = result.get("id")
        if not isinstance(app_id, (int, str)) or not str(app_id).isdigit():
            return fallback_url

        details_payload = await self._async_get_json(
            STEAM_APP_DETAILS_URL,
            {"appids": str(app_id), "l": "english"},
        )
        if isinstance(details_payload, Mapping):
            app_details = details_payload.get(str(app_id))
            if isinstance(app_details, Mapping):
                data = app_details.get("data")
                if isinstance(data, Mapping):
                    for field in (
                        "library_capsule",
                        "library_capsulev5",
                        "header_image",
                        "capsule_image",
                    ):
                        image_url = _http_url(data.get(field))
                        if image_url:
                            return image_url

        return fallback_url

    async def _async_get_json(self, url: str, params: Mapping[str, str]) -> Any:
        query_url = f"{url}?{urlencode(params)}"
        async with self._session.get(query_url, timeout=self._timeout) as response:
            if response.status != 200:
                return None
            return await response.json(content_type=None)
