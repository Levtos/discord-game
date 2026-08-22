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
