"""Resolve game artwork from Discord Rich Presence and public game metadata."""

from __future__ import annotations

import asyncio
import importlib
import logging
import re
from typing import Any


_LOGGER = logging.getLogger(__name__)


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


class MediaArtworkWrapperResolver:
    """Reuse the Media Art Wrapper's configured game provider chain.

    The import is intentionally lazy: Discord Game remains usable when the
    optional wrapper integration is not installed, while an installed wrapper
    remains the single owner of game-provider selection and caching.
    """

    _MODULE = "custom_components.media_art_wrapper.game_artwork"

    def __init__(self, hass: Any, session: Any) -> None:
        self._hass = hass
        self._session = session
        self._cache: dict[tuple[str, str], str | None] = {}
        self._inflight: dict[tuple[str, str], asyncio.Task[str | None]] = {}

    async def async_resolve(
        self,
        game_name: str | None,
        *,
        source_entity_id: str | None = None,
    ) -> str | None:
        """Return database artwork for *game_name*, if the wrapper is available."""
        title_key = normalize_game_title(game_name)
        if not title_key:
            return None
        cache_key = (source_entity_id or "", title_key)
        if cache_key in self._cache:
            return self._cache[cache_key]

        task = self._inflight.get(cache_key)
        if task is None:
            task = asyncio.create_task(
                self._async_fetch(game_name or "", source_entity_id=source_entity_id)
            )
            self._inflight[cache_key] = task

        try:
            result = await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.debug("Media Art Wrapper game lookup failed for %s", title_key, exc_info=True)
            result = None
        finally:
            if self._inflight.get(cache_key) is task:
                self._inflight.pop(cache_key, None)

        self._cache[cache_key] = result
        return result

    async def _async_fetch(
        self,
        game_name: str,
        *,
        source_entity_id: str | None,
    ) -> str | None:
        try:
            module = importlib.import_module(self._MODULE)
        except (ImportError, ModuleNotFoundError):
            _LOGGER.debug("Media Art Wrapper is not installed; skipping game lookup")
            return None

        resolver = getattr(module, "async_resolve_game_artwork", None)
        if not callable(resolver):
            _LOGGER.debug("Media Art Wrapper has no game artwork bridge")
            return None

        return await resolver(
            self._hass,
            self._session,
            game_name,
            source_entity_id=source_entity_id,
        )
