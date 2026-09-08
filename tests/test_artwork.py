import asyncio
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

_PATH = Path(__file__).parents[1] / "custom_components/discord_game/artwork.py"
_SPEC = spec_from_file_location("discord_game_artwork", _PATH)
A = module_from_spec(_SPEC)
_SPEC.loader.exec_module(A)


class Response:
    def __init__(self, payload=None, status=200, text="", error=None):
        self.status, self.payload, self.body, self.error = status, payload, text, error

    async def __aenter__(self):
        if self.error:
            raise self.error
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self, **kwargs):
        return self.payload

    async def text(self, **kwargs):
        return self.body


class Session:
    def __init__(self, routes=()):
        self.routes, self.calls = list(routes), []

    def get(self, url, **kwargs):
        self.calls.append(url)
        assert kwargs["timeout"] > 0
        for prefix, result in self.routes:
            if url.startswith(prefix):
                return result
        return Response(status=404)


def steam(name="Example Game", app_id=42, kind="game", **images):
    return Response(
        {
            str(app_id): {
                "success": True,
                "data": {"name": name, "steam_appid": app_id, "type": kind, **images},
            }
        }
    )


def search(*names):
    return Response(
        {
            "items": [
                {"type": "app", "name": name, "id": 42 + index}
                for index, name in enumerate(names)
            ]
        }
    )


def sony(
    name="Bloodborne",
    category="Full Game",
    image="https://image.api.playstation.com/cover.png",
):
    return Response(
        text='<script type="application/ld+json">'
        + json.dumps(
            {"@type": "Product", "name": name, "category": category, "image": image}
        )
        + "</script>"
    )


@pytest.mark.parametrize(
    "title,expected",
    [
        ("OVERWATCH® 2", "overwatch"),
        ("Overwatch2", "overwatch"),
        ("Anno 117", "anno 117 pax romana"),
        ("Anno 117: Pax Romana™", "anno 117 pax romana"),
        ("  Ｈｅａｒｔｈｓｔｏｎｅ  ", "hearthstone"),
        ("Demon’s Souls", "demon s souls"),
        (None, ""),
        ("", ""),
        ("Some_Game", "some game"),
    ],
)
def test_normalization_and_aliases(title, expected):
    assert A.canonical_game_title(title) == expected


@pytest.mark.parametrize(
    "large,small,expected",
    [
        (
            "https://cdn.discordapp.com/large.png",
            "https://cdn.discordapp.com/small.png",
            "https://cdn.discordapp.com/large.png",
        ),
        (
            None,
            "https://cdn.discordapp.com/small.png",
            "https://cdn.discordapp.com/small.png",
        ),
        (
            "https://cdn.discordapp.com/app-assets/123/mp:external/hash/https/example.com/cover.png",
            None,
            "https://media.discordapp.net/external/hash/https/example.com/cover.png",
        ),
        (
            "https://cdn.discordapp.com/app-assets/123/mp:external/hash/https/example.com/cover_512.png",
            None,
            "https://media.discordapp.net/external/hash/https/example.com/cover_512.png",
        ),
        (None, None, None),
        ("javascript:bad", None, None),
    ],
)
def test_discord_assets(large, small, expected):
    assert (
        A.activity_image_url(
            SimpleNamespace(large_image_url=large, small_image_url=small)
        )
        == expected
    )


def test_steam_exact_current_header_before_library_and_capsule():
    session = Session(
        [
            (A.STEAM_STORE_SEARCH_URL, search("Example Game")),
            (
                A.STEAM_APP_DETAILS_URL,
                steam(
                    header_image="https://cdn/header_alt_assets_22.jpg?t=123",
                    library_capsule="https://cdn/static.jpg",
                    capsule_image="https://cdn/tiny.jpg",
                ),
            ),
        ]
    )
    assert asyncio.run(
        A.GameArtworkResolver(session).async_resolve("Example Game")
    ) == ("https://cdn/header_alt_assets_22.jpg?t=123")
    assert len(session.calls) == 2


@pytest.mark.parametrize(
    "title,store_name,app_id",
    [
        ("Overwatch 2", "Overwatch®", 2357570),
        ("Anno 117", "Anno 117: Pax Romana", 3274580),
    ],
)
def test_known_alias_skips_search(title, store_name, app_id):
    session = Session(
        [
            (
                A.STEAM_APP_DETAILS_URL,
                steam(store_name, app_id, header_image="https://cdn/current.jpg"),
            )
        ]
    )
    assert (
        asyncio.run(A.GameArtworkResolver(session).async_resolve(title))
        == "https://cdn/current.jpg"
    )
    assert len(session.calls) == 1
    assert parse_qs(urlsplit(session.calls[0]).query)["appids"] == [str(app_id)]


@pytest.mark.parametrize(
    "candidate",
    [
        "Example Game Soundtrack",
        "Example Game Demo",
        "Example Game DLC",
        "Example Game 2",
        "Another Example Game",
        "Example",
        "Example Game Deluxe Edition",
    ],
)
def test_rejects_inexact_search(candidate):
    session = Session([(A.STEAM_STORE_SEARCH_URL, search(candidate))])
    assert (
        asyncio.run(A.GameArtworkResolver(session).async_resolve("Example Game"))
        is None
    )
    assert not any(url.startswith(A.STEAM_APP_DETAILS_URL) for url in session.calls)


@pytest.mark.parametrize("kind", ["dlc", "demo", "music", None])
def test_rejects_exact_title_non_game_details(kind):
    session = Session(
        [
            (A.STEAM_STORE_SEARCH_URL, search("Example Game")),
            (
                A.STEAM_APP_DETAILS_URL,
                steam(kind=kind, header_image="https://cdn/bad.jpg"),
            ),
        ]
    )
    assert (
        asyncio.run(A.GameArtworkResolver(session).async_resolve("Example Game"))
        is None
    )


def test_ambiguous_exact_matches_are_rejected():
    session = Session(
        [(A.STEAM_STORE_SEARCH_URL, search("Example Game", "Example Game"))]
    )
    assert (
        asyncio.run(A.GameArtworkResolver(session).async_resolve("Example Game"))
        is None
    )


@pytest.mark.parametrize(
    "response",
    [
        steam("Wrong Game", header_image="https://cdn/bad.jpg"),
        Response(
            {"42": {"success": False, "data": {"header_image": "https://cdn/bad.jpg"}}}
        ),
        Response({"42": {"success": True, "data": []}}),
    ],
)
def test_unreliable_details_degrade(response):
    session = Session(
        [
            (A.STEAM_STORE_SEARCH_URL, search("Example Game")),
            (A.STEAM_APP_DETAILS_URL, response),
        ]
    )
    assert (
        asyncio.run(A.GameArtworkResolver(session).async_resolve("Example Game"))
        is None
    )


def test_steam_miss_to_playstation():
    session = Session(
        [
            (A.STEAM_STORE_SEARCH_URL, search("Bloodborne Soundtrack")),
            (
                "https://www.playstation.com/en-us/games/bloodborne/",
                sony("Bloodborne™"),
            ),
        ]
    )
    assert asyncio.run(A.GameArtworkResolver(session).async_resolve("Bloodborne")) == (
        "https://image.api.playstation.com/cover.png"
    )


def test_steam_no_image_to_playstation():
    session = Session(
        [
            (A.STEAM_STORE_SEARCH_URL, search("Bloodborne")),
            (A.STEAM_APP_DETAILS_URL, steam("Bloodborne")),
            ("https://www.playstation.com/", sony()),
        ]
    )
    assert asyncio.run(A.GameArtworkResolver(session).async_resolve("Bloodborne")) == (
        "https://image.api.playstation.com/cover.png"
    )


@pytest.mark.parametrize(
    "response",
    [
        sony("Bloodborne DLC"),
        sony(category="Add-on"),
        sony(image="https://other.example/icon.png"),
        Response(text='<script type="application/ld+json">{broken}</script>'),
        Response(
            text='<meta property="og:image" content="https://image.api.playstation.com/unverified.png">'
        ),
        Response(status=503),
        Response(error=TimeoutError()),
    ],
)
def test_playstation_failure_to_local(tmp_path, response):
    (tmp_path / "bloodborne.webp").write_bytes(b"fixture")
    session = Session([("https://www.playstation.com/", response)])
    image = asyncio.run(
        A.GameArtworkResolver(session, local_directory=str(tmp_path)).async_resolve(
            "Bloodborne"
        )
    )
    assert image.startswith("/local/discord_game/bloodborne.webp?v=")


def test_sony_slug_alias():
    session = Session(
        [
            (
                "https://www.playstation.com/en-us/games/demons-souls/",
                sony("Demon's Souls"),
            )
        ]
    )
    assert asyncio.run(A.GameArtworkResolver(session).async_resolve("Demon’s Souls"))
    assert session.calls[-1] == "https://www.playstation.com/en-us/games/demons-souls/"


def test_hearthstone_local_added_deleted_and_replaced_during_negative_cache(tmp_path):
    resolver = A.GameArtworkResolver(Session(), local_directory=str(tmp_path))

    async def run():
        assert await resolver.async_resolve("Hearthstone") is None
        path = tmp_path / "hearthstone.webp"
        path.write_bytes(b"fixture")
        image = await resolver.async_resolve("HEARTHSTONE™")
        assert image.startswith("/local/discord_game/hearthstone.webp?v=")
        path.unlink()
        assert await resolver.async_resolve("Hearthstone") is None

    asyncio.run(run())
    assert len(resolver._session.calls) == 2


def test_local_path_traversal_does_not_escape(tmp_path):
    (tmp_path.parent / "outside.webp").write_bytes(b"fixture")
    resolver = A.GameArtworkResolver(Session(), local_directory=str(tmp_path))
    assert asyncio.run(resolver.async_resolve("../outside")) is None


def test_positive_cache_expiry_refreshes_image_but_reuses_id(monkeypatch):
    clock = [1.0]
    monkeypatch.setattr(A.time, "monotonic", lambda: clock[0])
    details = steam(header_image="https://cdn/season1.jpg")
    session = Session(
        [
            (A.STEAM_STORE_SEARCH_URL, search("Example Game")),
            (A.STEAM_APP_DETAILS_URL, details),
        ]
    )
    resolver = A.GameArtworkResolver(session)

    async def run():
        assert await resolver.async_resolve("Example Game") == "https://cdn/season1.jpg"
        details.payload["42"]["data"]["header_image"] = "https://cdn/season2.jpg"
        assert (
            await resolver.async_resolve("EXAMPLE GAME™") == "https://cdn/season1.jpg"
        )
        clock[0] += A.POSITIVE_CACHE_TTL + 1
        assert await resolver.async_resolve("Example Game") == "https://cdn/season2.jpg"

    asyncio.run(run())
    assert len(session.calls) == 3
    assert sum(url.startswith(A.STEAM_STORE_SEARCH_URL) for url in session.calls) == 1


def test_negative_cache_expires(monkeypatch):
    clock = [1.0]
    monkeypatch.setattr(A.time, "monotonic", lambda: clock[0])
    session = Session()
    resolver = A.GameArtworkResolver(session)

    async def run():
        assert await resolver.async_resolve("Missing") is None
        assert await resolver.async_resolve("MISSING") is None
        assert len(session.calls) == 2
        clock[0] += A.NEGATIVE_CACHE_TTL + 1
        assert await resolver.async_resolve("Missing") is None

    asyncio.run(run())
    assert len(session.calls) == 4


def test_coalescing_survives_cancelled_waiter():
    resolver = A.GameArtworkResolver(Session())
    calls = []

    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        async def fetch(key):
            calls.append(key)
            entered.set()
            await release.wait()
            return "https://cdn/shared.jpg"

        resolver._async_fetch = fetch
        first = asyncio.create_task(resolver.async_resolve("Overwatch 2"))
        await entered.wait()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = asyncio.create_task(resolver.async_resolve("Overwatch"))
        third = asyncio.create_task(resolver.async_resolve("OVERWATCH®"))
        release.set()
        assert await second == await third == "https://cdn/shared.jpg"
        assert not resolver._inflight

    asyncio.run(run())
    assert calls == ["overwatch"]


def test_provider_timeout_is_bounded_and_isolated(tmp_path):
    (tmp_path / "hearthstone.webp").write_bytes(b"fixture")
    resolver = A.GameArtworkResolver(
        Session(), timeout=0.01, local_directory=str(tmp_path)
    )

    async def forever(key):
        await asyncio.Event().wait()

    resolver._async_resolve_steam = forever
    resolver._async_resolve_playstation = forever
    assert asyncio.run(resolver.async_resolve("Hearthstone")).startswith("/local/")


def test_close_cancels_inflight_work():
    resolver = A.GameArtworkResolver(Session())

    async def run():
        entered = asyncio.Event()

        async def forever(key):
            entered.set()
            await asyncio.Event().wait()

        resolver._async_resolve_steam = forever
        task = asyncio.create_task(resolver.async_resolve("Example Game"))
        await entered.wait()
        resolver.close()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await resolver.async_resolve("Example Game") is None
        assert not resolver._inflight

    asyncio.run(run())


@pytest.mark.parametrize(
    "answer,asset,expected",
    [
        ("https://cdn/steam.png", "https://cdn/discord.png", "https://cdn/steam.png"),
        (
            "/local/discord_game/a.webp",
            "https://cdn/discord.png",
            "/local/discord_game/a.webp",
        ),
        (None, "https://cdn/discord.png", "https://cdn/discord.png"),
        (None, None, None),
        (
            RuntimeError("provider failed"),
            "https://cdn/discord.png",
            "https://cdn/discord.png",
        ),
    ],
)
def test_discord_last_fallback_and_failure_isolation(answer, asset, expected):
    watcher = SimpleNamespace(_activity_generation=1, game_image_url=None)
    activity = SimpleNamespace(name="Game", large_image_url=asset)
    notifications = []

    async def resolve(name):
        if isinstance(answer, Exception):
            raise answer
        return answer

    asyncio.run(
        A.async_update_activity_artwork(
            watcher,
            activity,
            SimpleNamespace(async_resolve=resolve),
            1,
            notifications.append,
        )
    )
    assert watcher.game_image_url == expected
    assert notifications == [watcher]


def test_late_answer_cannot_overwrite_new_game_or_stopped_game():
    async def run():
        release = asyncio.Event()

        async def resolve(name):
            await release.wait()
            return "https://cdn/old.png"

        watcher = SimpleNamespace(_activity_generation=1, game_image_url=None)
        notifications = []
        task = asyncio.create_task(
            A.async_update_activity_artwork(
                watcher,
                SimpleNamespace(name="Old"),
                SimpleNamespace(async_resolve=resolve),
                1,
                notifications.append,
            )
        )
        await asyncio.sleep(0)
        watcher._activity_generation = 2
        watcher.game_image_url = "https://cdn/new.png"
        release.set()
        await task
        assert watcher.game_image_url == "https://cdn/new.png"
        watcher.game_image_url = None
        await A.async_update_activity_artwork(
            watcher,
            SimpleNamespace(name="Old"),
            SimpleNamespace(async_resolve=resolve),
            1,
            notifications.append,
        )
        assert watcher.game_image_url is None
        assert notifications == []

    asyncio.run(run())
