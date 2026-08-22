import asyncio
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace


_MODULE_PATH = (
    Path(__file__).parents[1] / "custom_components" / "discord_game" / "artwork.py"
)
_SPEC = spec_from_file_location("discord_game_artwork", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_ARTWORK = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_ARTWORK)


class FakeResponse:
    def __init__(self, *, status=200, payload=None, text=""):
        self.status = status
        self._payload = payload
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self, **kwargs):
        return self._payload

    async def text(self, **kwargs):
        return self._text


class FakeSession:
    def __init__(self, *, get_routes=(), post_routes=()):
        self.get_routes = list(get_routes)
        self.post_routes = list(post_routes)
        self.calls = []

    def _response(self, method, url):
        self.calls.append((method, url))
        routes = self.get_routes if method == "GET" else self.post_routes
        for prefix, response in routes:
            if url.startswith(prefix):
                return response
        return FakeResponse(status=404)

    def get(self, url, **kwargs):
        return self._response("GET", url)

    def post(self, url, **kwargs):
        return self._response("POST", url)


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


def test_hearthstone_resolves_from_battlenet_without_credentials():
    image_url = "https://cdn.example/hearthstone-cover.jpg"
    session = FakeSession(
        get_routes=[
            (
                "https://hearthstone.blizzard.com/en-us/",
                FakeResponse(text=f'<meta property="og:image" content="{image_url}">'),
            )
        ]
    )

    result = asyncio.run(
        _ARTWORK.GameArtworkResolver(session).async_resolve("Hearthstone")
    )

    assert result == image_url
    assert session.calls == [("GET", "https://hearthstone.blizzard.com/en-us/")]


def test_overwatch_alias_resolves_from_battlenet_without_credentials():
    image_url = "https://cdn.example/overwatch-cover.jpg"
    session = FakeSession(
        get_routes=[
            (
                "https://overwatch.blizzard.com/en-us/",
                FakeResponse(text=f'<meta content="{image_url}" property="og:image">'),
            )
        ]
    )

    result = asyncio.run(
        _ARTWORK.GameArtworkResolver(session).async_resolve("Overwatch")
    )

    assert result == image_url


def test_igdb_is_preferred_when_credentials_are_configured():
    session = FakeSession(
        post_routes=[
            (
                _ARTWORK.TWITCH_TOKEN_URL,
                FakeResponse(payload={"access_token": "token", "expires_in": 3600}),
            ),
            (
                _ARTWORK.IGDB_GAMES_URL,
                FakeResponse(payload=[{"id": 1, "name": "Hearthstone", "cover": 77}]),
            ),
            (
                _ARTWORK.IGDB_COVERS_URL,
                FakeResponse(payload=[{"image_id": "cover-id"}]),
            ),
        ]
    )
    resolver = _ARTWORK.GameArtworkResolver(
        session,
        igdb_client_id="client",
        igdb_client_secret="secret",
    )

    result = asyncio.run(resolver.async_resolve("Hearthstone"))

    assert result == "https://images.igdb.com/igdb/image/upload/t_1080p/cover-id.jpg"
    assert all(method == "POST" for method, _url in session.calls)


def test_steamgriddb_is_used_when_configured_and_igdb_is_not():
    image_url = "https://cdn.example/grid.png"
    session = FakeSession(
        get_routes=[
            (
                _ARTWORK.STEAMGRIDDB_SEARCH_URL.split("{term}")[0],
                FakeResponse(
                    payload={"success": True, "data": [{"id": 12, "name": "Some Game"}]}
                ),
            ),
            (
                _ARTWORK.STEAMGRIDDB_GRIDS_URL.split("{game_id}")[0],
                FakeResponse(payload={"success": True, "data": [{"url": image_url}]}),
            ),
        ]
    )
    resolver = _ARTWORK.GameArtworkResolver(session, steamgriddb_api_key="sgdb-key")

    assert asyncio.run(resolver.async_resolve("Some Game")) == image_url


def test_non_blizzard_game_falls_back_to_public_steam_api():
    image_url = "https://cdn.example/library.jpg"
    session = FakeSession(
        get_routes=[
            (
                _ARTWORK.STEAM_STORE_SEARCH_URL,
                FakeResponse(
                    payload={
                        "items": [
                            {
                                "id": 42,
                                "name": "Example Game",
                                "tiny_image": "https://cdn.example/tiny.jpg",
                            }
                        ]
                    }
                ),
            ),
            (
                _ARTWORK.STEAM_APP_DETAILS_URL,
                FakeResponse(
                    payload={
                        "42": {
                            "success": True,
                            "data": {"library_capsule": image_url},
                        }
                    }
                ),
            ),
        ]
    )

    assert (
        asyncio.run(_ARTWORK.GameArtworkResolver(session).async_resolve("Example Game"))
        == image_url
    )


def test_normalized_title_cache_and_concurrent_requests_share_one_lookup():
    resolver = _ARTWORK.GameArtworkResolver(FakeSession())
    calls = []

    async def fake_fetch(title):
        calls.append(title)
        await asyncio.sleep(0)
        return "https://cdn.example/cover.jpg"

    resolver._async_fetch = fake_fetch

    async def run():
        first, second = await asyncio.gather(
            resolver.async_resolve("Hearthstone"),
            resolver.async_resolve("HEARTHSTONE™"),
        )
        third = await resolver.async_resolve("hearthstone")
        return first, second, third

    assert asyncio.run(run()) == (
        "https://cdn.example/cover.jpg",
        "https://cdn.example/cover.jpg",
        "https://cdn.example/cover.jpg",
    )
    assert calls == ["Hearthstone"]


def test_provider_failures_are_isolated_and_negative_result_is_cached():
    session = FakeSession(
        get_routes=[
            ("https://hearthstone.blizzard.com/en-us/", FakeResponse(status=503)),
            (_ARTWORK.STEAM_STORE_SEARCH_URL, FakeResponse(status=503)),
        ]
    )
    resolver = _ARTWORK.GameArtworkResolver(session)

    assert asyncio.run(resolver.async_resolve("Hearthstone")) is None
    assert asyncio.run(resolver.async_resolve("HEARTHSTONE")) is None
    assert len(session.calls) == 2


def test_resolver_has_no_media_art_wrapper_runtime_dependency():
    assert "media_art_wrapper" not in _MODULE_PATH.read_text(encoding="utf-8")
