"""Resolve artwork URLs exposed by Discord Rich Presence activities."""

from __future__ import annotations

import re
from typing import Any


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
