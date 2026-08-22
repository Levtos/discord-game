import asyncio
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
import sys
import types


_MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "discord_game"
    / "artwork.py"
)
_SPEC = spec_from_file_location("discord_game_artwork", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_ARTWORK = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_ARTWORK)


def test_prefers_large_image_url():
    activity = SimpleNamespace(
        large_image_url="https://cdn.discordapp.com/app-assets/123/large.png",
        small_image_url="https://cdn.discordapp.com/app-assets/123/small.png",
    )

    assert _ARTWORK.activity_image_url(activity) == activity.large_image_url


def test_falls_back_to_small_image_url():
    activity = SimpleNamespace(
        large_image_url=None,
        small_image_url="https://cdn.discordapp.com/app-assets/123/small.png",
    )

    assert _ARTWORK.activity_image_url(activity) == activity.small_image_url


def test_normalizes_external_discord_asset_url():
    activity = SimpleNamespace(
        large_image_url=(
            "https://cdn.discordapp.com/app-assets/123/mp:external/hash/"
            "https/example.com/game-cover.png"
        ),
        small_image_url=None,
    )

    assert _ARTWORK.activity_image_url(activity) == (
        "https://media.discordapp.net/external/hash/https/example.com/game-cover.png"
    )


def test_normalizes_external_discord_asset_url_with_size():
    activity = SimpleNamespace(
        large_image_url=(
            "https://cdn.discordapp.com/app-assets/123/mp:external/hash/"
            "https/example.com/game-cover_512.png"
        ),
        small_image_url=None,
    )

    assert _ARTWORK.activity_image_url(activity) == (
        "https://media.discordapp.net/external/hash/https/example.com/game-cover_512.png"
    )


def test_returns_none_without_assets():
    assert _ARTWORK.activity_image_url(SimpleNamespace()) is None


def _install_wrapper_bridge(monkeypatch, callback):
    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = []
    media_art_wrapper = types.ModuleType("custom_components.media_art_wrapper")
    media_art_wrapper.__path__ = []
    bridge = types.ModuleType("custom_components.media_art_wrapper.game_artwork")
    bridge.async_resolve_game_artwork = callback
    monkeypatch.setitem(sys.modules, "custom_components", custom_components)
    monkeypatch.setitem(sys.modules, "custom_components.media_art_wrapper", media_art_wrapper)
    monkeypatch.setitem(sys.modules, "custom_components.media_art_wrapper.game_artwork", bridge)


def test_wrapper_resolver_delegates_to_game_provider_bridge(monkeypatch):
    calls = []

    async def resolve(hass, session, title, *, source_entity_id):
        calls.append((hass, session, title, source_entity_id))
        return "https://cdn.example/hearthstone-cover.jpg"

    _install_wrapper_bridge(monkeypatch, resolve)
    hass = object()
    session = object()
    resolver = _ARTWORK.MediaArtworkWrapperResolver(hass, session)

    assert asyncio.run(
        resolver.async_resolve(
            "Hearthstone",
            source_entity_id="media_player.discord_game_123",
        )
    ) == "https://cdn.example/hearthstone-cover.jpg"
    assert asyncio.run(
        resolver.async_resolve(
            "HEARTHSTONE",
            source_entity_id="media_player.discord_game_123",
        )
    ) == "https://cdn.example/hearthstone-cover.jpg"
    assert calls == [(hass, session, "Hearthstone", "media_player.discord_game_123")]


def test_wrapper_resolver_returns_none_when_optional_wrapper_is_missing(monkeypatch):
    monkeypatch.delitem(sys.modules, "custom_components.media_art_wrapper.game_artwork", raising=False)
    monkeypatch.delitem(sys.modules, "custom_components.media_art_wrapper", raising=False)
    monkeypatch.delitem(sys.modules, "custom_components", raising=False)

    assert asyncio.run(_ARTWORK.MediaArtworkWrapperResolver(object(), object()).async_resolve("Hearthstone")) is None
