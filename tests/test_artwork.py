import asyncio
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace


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


class _FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def json(self, **kwargs):
        return self._payload


class _FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if "storesearch" in url:
            return _FakeResponse(200, self.responses["search"])
        return _FakeResponse(*self.responses["details"])


def test_steam_resolver_returns_header_and_caches_result():
    session = _FakeSession(
        {
            "search": {
                "items": [
                    {
                        "id": 2357570,
                        "name": "Overwatch©",
                        "tiny_image": "https://cdn.example/overwatch-small.jpg",
                    }
                ]
            },
            "details": (
                200,
                {
                    "2357570": {
                        "data": {
                            "header_image": "https://cdn.example/overwatch-header.jpg"
                        }
                    }
                },
            ),
        }
    )
    resolver = _ARTWORK.SteamArtworkResolver(session)

    assert asyncio.run(resolver.async_resolve("Overwatch")) == (
        "https://cdn.example/overwatch-header.jpg"
    )
    assert asyncio.run(resolver.async_resolve("OVERWATCH")) == (
        "https://cdn.example/overwatch-header.jpg"
    )
    assert len(session.calls) == 2


def test_steam_resolver_uses_search_thumbnail_when_details_fail():
    session = _FakeSession(
        {
            "search": {
                "items": [
                    {
                        "id": 123,
                        "name": "Example Game",
                        "tiny_image": "https://cdn.example/example.jpg",
                    }
                ]
            },
            "details": (503, None),
        }
    )

    assert asyncio.run(_ARTWORK.SteamArtworkResolver(session).async_resolve("Example Game")) == (
        "https://cdn.example/example.jpg"
    )


def test_steam_resolver_rejects_unrelated_search_result():
    session = _FakeSession(
        {
            "search": {"items": [{"id": 123, "name": "Different Game"}]},
            "details": (200, {}),
        }
    )

    assert asyncio.run(_ARTWORK.SteamArtworkResolver(session).async_resolve("Overwatch")) is None
    assert len(session.calls) == 1
