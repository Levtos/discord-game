"""Credential-free Steam, PlayStation and local game artwork."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from html.parser import HTMLParser
import json
import logging
from pathlib import Path
import re
import time
from typing import Any
import unicodedata
from urllib.parse import quote, urlencode, urlsplit

_LOGGER = logging.getLogger(__name__)
REQUEST_TIMEOUT = 10.0
POSITIVE_CACHE_TTL = 86_400.0
NEGATIVE_CACHE_TTL = 300.0
MAX_CACHE_ENTRIES = 256
STEAM_STORE_SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
STEAM_APP_DETAILS_URL = "https://store.steampowered.com/api/appdetails"
PLAYSTATION_GAME_URL = "https://www.playstation.com/en-us/games/{slug}/"

# Verified full-game IDs; deliberately small, never fuzzy-match expansions.
_ALIASES = {
    "overwatch 2": "overwatch",
    "overwatch2": "overwatch",
    "anno 117": "anno 117 pax romana",
}
_STEAM_IDS = {"overwatch": "2357570", "anno 117 pax romana": "3274580"}
_PLAYSTATION_SLUGS = {"demon s souls": "demons-souls"}
_EXTERNAL_IMAGE = re.compile(
    r"^https://cdn\.discordapp\.com/app-assets/\d+/mp:external/([^/]+)/(https/.+\.(?:png|jpg|jpeg|webp))$"
)


def _http_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme in ("http", "https")
            and parsed.hostname
            and not parsed.username
        ):
            return value
    except ValueError:
        pass
    return None


def normalize_discord_image_url(url: str | None) -> str | None:
    """Return an HA-fetchable URL for a nextcord Discord asset."""
    if not _http_url(url):
        return None
    if match := _EXTERNAL_IMAGE.match(url):
        return (
            f"https://media.discordapp.net/external/{match.group(1)}/{match.group(2)}"
        )
    return url


def activity_image_url(activity: Any) -> str | None:
    for attribute in ("large_image_url", "small_image_url"):
        if image := normalize_discord_image_url(getattr(activity, attribute, None)):
            return image
    return None


def normalize_game_title(title: str | None) -> str:
    if not isinstance(title, str):
        return ""
    title = unicodedata.normalize("NFKC", re.sub(r"[©®™]", "", title)).casefold()
    return re.sub(r"[\W_]+", " ", title, flags=re.UNICODE).strip()


def canonical_game_title(title: str | None) -> str:
    key = normalize_game_title(title)
    return _ALIASES.get(key, key)


class _ProductParser(HTMLParser):
    """Read public JSON-LD Product metadata, independent of page layout."""

    def __init__(self):
        super().__init__()
        self.products = []
        self._parts = None

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("type") == "application/ld+json":
            self._parts = []

    def handle_data(self, data):
        if self._parts is not None:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag != "script" or self._parts is None:
            return
        try:
            self._collect(json.loads("".join(self._parts)))
        except (ValueError, RecursionError):
            pass
        self._parts = None

    def _collect(self, value):
        if isinstance(value, list):
            for item in value:
                self._collect(item)
        elif isinstance(value, Mapping):
            if value.get("@type") == "Product":
                self.products.append(value)
            if "@graph" in value:
                self._collect(value["@graph"])


class GameArtworkResolver:
    """Steam -> Sony public product metadata -> user-owned local image."""

    def __init__(
        self,
        session: Any,
        *,
        local_directory: str | None = None,
        executor: Any = None,
        timeout: float = REQUEST_TIMEOUT,
    ):
        self._session = session
        self._local_directory = local_directory
        self._executor = executor or asyncio.to_thread
        self._timeout = timeout
        self._cache = {}
        self._inflight = {}
        self._steam_ids = dict(_STEAM_IDS)
        self._closed = False

    async def async_resolve(self, game_name: str | None) -> str | None:
        key = canonical_game_title(game_name)
        if not key or self._closed:
            return None
        cached = self._cache.get(key)
        if cached and cached[1] > time.monotonic():
            return cached[0] or await self._async_local_image(key)
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(self._async_fetch_cached(key))
            self._inflight[key] = task
        image = await asyncio.shield(task)
        return image or await self._async_local_image(key)

    async def _async_fetch_cached(self, key):
        # The owner task removes itself, never a cancelled individual waiter.
        try:
            image = await self._async_fetch(key)
            ttl = POSITIVE_CACHE_TTL if image else NEGATIVE_CACHE_TTL
            if len(self._cache) >= MAX_CACHE_ENTRIES:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = (image, time.monotonic() + ttl)
            return image
        finally:
            self._inflight.pop(key, None)

    async def _async_fetch(self, key):
        for name, provider in (
            ("Steam", self._async_resolve_steam),
            ("PlayStation", self._async_resolve_playstation),
        ):
            try:
                # Timeout bounds the whole provider, including multiple requests.
                async with asyncio.timeout(self._timeout):
                    image = _http_url(await provider(key))
                if image:
                    return image
            except Exception:
                _LOGGER.debug("%s artwork unavailable for %r", name, key, exc_info=True)
        return None

    async def _async_resolve_steam(self, key):
        app_id = self._steam_ids.get(key)
        if app_id is None:
            search = await self._async_get_json(
                STEAM_STORE_SEARCH_URL, {"term": key, "l": "english", "cc": "de"}
            )
            items = search.get("items") if isinstance(search, Mapping) else None
            if not isinstance(items, list):
                return None
            ids = {
                str(item["id"])
                for item in items
                if isinstance(item, Mapping)
                and item.get("type") == "app"
                and canonical_game_title(item.get("name")) == key
                and isinstance(item.get("id"), (int, str))
                and str(item["id"]).isdigit()
            }
            if len(ids) != 1:
                return None
            app_id = ids.pop()
        for language in ("german", "english"):
            details = await self._async_get_json(
                STEAM_APP_DETAILS_URL,
                {"appids": app_id, "l": language, "cc": "de"},
            )
            app = details.get(app_id) if isinstance(details, Mapping) else None
            data = (
                app.get("data")
                if isinstance(app, Mapping) and app.get("success") is True
                else None
            )
            if (
                not isinstance(data, Mapping)
                or data.get("type") != "game"
                or str(data.get("steam_appid")) != app_id
                or canonical_game_title(data.get("name")) != key
            ):
                continue
            if len(self._steam_ids) >= MAX_CACHE_ENTRIES:
                self._steam_ids.pop(next(iter(self._steam_ids)))
            self._steam_ids[key] = app_id
            # Current Store alt_assets headers win over static library art.
            for field in ("header_image", "capsule_image", "capsule_imagev5"):
                if image := _http_url(data.get(field)):
                    return image
        self._steam_ids.pop(key, None)
        return None

    async def _async_resolve_playstation(self, key):
        slug = _PLAYSTATION_SLUGS.get(key, key.replace(" ", "-"))
        url = PLAYSTATION_GAME_URL.format(slug=quote(slug, safe="-"))
        async with self._session.get(url, timeout=self._timeout) as response:
            if response.status != 200:
                return None
            parser = _ProductParser()
            parser.feed(await response.text())
        images = set()
        for product in parser.products:
            if (
                canonical_game_title(product.get("name")) != key
                or product.get("category") != "Full Game"
            ):
                continue
            image = _http_url(product.get("image"))
            if image and urlsplit(image).hostname == "image.api.playstation.com":
                images.add(image)
        return images.pop() if len(images) == 1 else None

    async def _async_local_image(self, key):
        if not self._local_directory:
            return None
        try:
            return await self._executor(self._local_image, key)
        except Exception:
            _LOGGER.debug("Local artwork unavailable for %r", key, exc_info=True)
            return None

    def _local_image(self, key):
        directory = Path(self._local_directory).resolve()
        for suffix in ("webp", "png", "jpg", "jpeg"):
            name = f"{key.replace(' ', '-')}.{suffix}"
            path = (directory / name).resolve()
            if path.parent != directory or not path.is_file():
                continue
            return f"/local/discord_game/{quote(name)}?v={path.stat().st_mtime_ns}"
        return None

    async def _async_get_json(self, url, params):
        async with self._session.get(
            f"{url}?{urlencode(params)}", timeout=self._timeout
        ) as response:
            if response.status != 200:
                return None
            return await response.json(content_type=None)

    def close(self):
        self._closed = True
        for task in list(self._inflight.values()):
            task.cancel()


async def async_update_activity_artwork(
    watcher, activity, resolver, generation, notify
):
    """Only publish the current activity's answer; never break presence."""
    try:
        image = await resolver.async_resolve(activity.name)
    except Exception:
        _LOGGER.debug("Activity artwork lookup failed", exc_info=True)
        image = None
    if generation != watcher._activity_generation:
        return
    watcher.game_image_url = image or activity_image_url(activity)
    notify(watcher)
