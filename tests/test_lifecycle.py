"""Exercise actual setup/event/migration code with minimal HA/Discord boundary doubles."""

import asyncio
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

ROOT = Path(__file__).parents[1] / "custom_components/discord_game"


@pytest.fixture
def modules(monkeypatch):
    def stub(name, **attrs):
        module = ModuleType(name)
        module.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    class Entity:
        hass = None

        def async_schedule_update_ha_state(self, force):
            assert force is False

    class Bot:
        def __init__(self, **kwargs):
            self.events = {}

        async def login(self, token):
            pass

        async def fetch_user(self, uid):
            return SimpleNamespace(id=uid, name="user", global_name="User")

        def event(self, func):
            self.events[func.__name__] = func
            return func

    nextcord = stub(
        "nextcord",
        Client=Bot,
        Intents=SimpleNamespace(
            all=lambda: SimpleNamespace(), none=lambda: SimpleNamespace()
        ),
        ActivityType=SimpleNamespace(playing="playing"),
        Member=object,
        User=object,
        RawReactionActionEvent=object,
        VoiceState=object,
    )
    stub("nextcord.abc", GuildChannel=object)
    stub(
        "validators",
        url=lambda value: isinstance(value, str) and value.startswith("http"),
    )
    config_entries = stub("homeassistant.config_entries", ConfigEntry=object)
    core = stub("homeassistant.core", HomeAssistant=object)
    stub("homeassistant", config_entries=config_entries, core=core)
    stub(
        "homeassistant.const",
        Platform=SimpleNamespace(SENSOR="sensor", MEDIA_PLAYER="media_player"),
        CONF_ACCESS_TOKEN="access_token",
        EVENT_HOMEASSISTANT_STOP="stop",
    )
    cv = stub(
        "homeassistant.helpers.config_validation",
        config_entry_only_config_schema=lambda _: {},
    )
    stub("homeassistant.helpers", config_validation=cv)
    stub("homeassistant.helpers.entity", DeviceInfo=dict)
    stub(
        "homeassistant.helpers.aiohttp_client",
        async_get_clientsession=lambda _: object(),
    )
    stub("homeassistant.components")
    stub("homeassistant.components.sensor", SensorEntity=Entity)
    stub(
        "homeassistant.components.media_player",
        MediaPlayerEntity=Entity,
        MediaPlayerEntityFeature=int,
        MediaPlayerState=SimpleNamespace(OFF="off", IDLE="idle", PLAYING="playing"),
    )
    stub(
        "homeassistant.components.media_player.const",
        MediaType=SimpleNamespace(GAME="game"),
    )

    def load(name, file, package=False):
        spec = spec_from_file_location(
            name,
            ROOT / file,
            submodule_search_locations=[str(ROOT)] if package else None,
        )
        module = module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    # Track imported relative modules for monkeypatch cleanup.
    stub("discord_game", __path__=[str(ROOT)])
    load("discord_game.const", "const.py")
    artwork = load("discord_game.artwork", "artwork.py")
    init = load("discord_game", "__init__.py", True)
    sensor = load("discord_game.sensor", "sensor.py")
    media = load("discord_game.media_player", "media_player.py")
    return SimpleNamespace(
        init=init, sensor=sensor, media=media, artwork=artwork, nextcord=nextcord
    )


@pytest.mark.parametrize("version", [1, 2, 3])
def test_migration_old_credentials_preserves_discord_settings(modules, version):
    retired = {
        "igdb_client_id": "old-id",
        "igdb_client_secret": "old-secret",
        "steamgriddb_api_key": "old-key",
    }
    entry = SimpleNamespace(
        version=version,
        data={"access_token": "discord", "members": [1], **retired},
        options={"enable_voice": False, **retired},
    )
    update = Mock()
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update))
    result = asyncio.run(modules.init.async_migrate_entry(hass, entry))
    assert result is (version <= 2)
    if version == 1:
        update.assert_called_once_with(
            entry,
            data={"access_token": "discord", "members": [1]},
            options={"enable_voice": False},
            version=2,
        )
    else:
        update.assert_not_called()


def test_setup_unload_and_options_reload_use_config_entry(modules):
    entry = SimpleNamespace(
        entry_id="actual-entry",
        data={"access_token": "discord"},
        add_update_listener=Mock(return_value=Mock()),
    )
    manager = SimpleNamespace(
        async_forward_entry_setups=AsyncMock(),
        async_unload_platforms=AsyncMock(return_value=True),
        async_reload=AsyncMock(),
    )
    hass = SimpleNamespace(data={}, config_entries=manager)

    async def run():
        assert await modules.init.async_setup_entry(hass, entry)
        assert manager.async_forward_entry_setups.call_args_list[0].args == (
            entry,
            ["sensor"],
        )
        assert manager.async_forward_entry_setups.call_args_list[1].args == (
            entry,
            ["media_player"],
        )
        await modules.init.async_options_updated(hass, entry)
        manager.async_reload.assert_awaited_once_with("actual-entry")
        assert await modules.init.async_unload_entry(hass, entry)
        assert "actual-entry" not in hass.data["discord_game"]

    asyncio.run(run())


def test_presence_is_immediate_switch_stop_failure_and_unload(
    modules, monkeypatch, tmp_path
):
    async def run():
        tasks, unloads, bots = [], [], []
        bot_class = modules.nextcord.Client

        def make_bot(**kwargs):
            bot = bot_class(**kwargs)
            bots.append(bot)
            return bot

        monkeypatch.setattr(modules.nextcord, "Client", make_bot)
        requests = {}

        class Resolver:
            def __init__(self, session, **kwargs):
                self.closed = False

            async def async_resolve(self, name):
                requests[name] = asyncio.get_running_loop().create_future()
                return await requests[name]

            def close(self):
                self.closed = True

        monkeypatch.setattr(modules.sensor, "GameArtworkResolver", Resolver)

        def background(coro, name):
            task = asyncio.create_task(coro)
            tasks.append(task)
            return task

        hass = SimpleNamespace(
            loop=asyncio.get_running_loop(),
            config=SimpleNamespace(path=lambda *parts: str(tmp_path.joinpath(*parts))),
            async_add_executor_job=asyncio.to_thread,
            async_create_background_task=background,
            bus=SimpleNamespace(async_listen_once=Mock(), async_fire=Mock()),
            data={
                "discord_game": {"entry": {"access_token": "discord", "members": [1]}}
            },
        )
        entry = SimpleNamespace(
            entry_id="entry",
            options={},
            async_on_unload=unloads.append,
            async_create_background_task=lambda hass, coro, name: background(
                coro, name
            ),
        )
        entities = []
        # A resolver must not perform any provider request in setup.
        await modules.sensor.async_setup_entry(hass, entry, entities.extend)
        assert requests == {}
        players = []
        await modules.media.async_setup_entry(hass, entry, players.extend)
        watcher = hass.data["discord_game"]["entry"]["watchers"]["1"]
        sensor = watcher.sensors["game"]
        player = players[0]

        def member(name):
            activities = (
                []
                if name is None
                else [
                    SimpleNamespace(
                        name=name,
                        type="playing",
                        large_image_url="https://cdn/discord.png",
                    )
                ]
            )
            return SimpleNamespace(
                id=1, status="online", display_name="User", activities=activities
            )

        event = bots[0].events["on_presence_update"]
        await event(None, member("Old"))
        assert watcher.game == "Old"
        assert watcher.game_image_url is None
        await asyncio.sleep(0)
        await event(None, member("New"))
        assert watcher.game == player.media_title == sensor.native_value == "New"
        await asyncio.sleep(0)
        requests["New"].set_result("https://cdn/new.png")
        await asyncio.sleep(0)
        assert (
            watcher.game_image_url
            == player.media_image_url
            == sensor.entity_picture
            == "https://cdn/new.png"
        )
        requests["Old"].set_result("https://cdn/old.png")
        await asyncio.sleep(0)
        assert player.media_image_url == "https://cdn/new.png"
        await event(None, member("New"))
        assert player.media_image_url == "https://cdn/new.png"
        await asyncio.sleep(0)
        requests["New"].set_result("https://cdn/new-season.png")
        await asyncio.sleep(0)
        assert player.media_image_url == "https://cdn/new-season.png"
        await event(None, member("Ending"))
        await asyncio.sleep(0)
        await event(None, member(None))
        assert watcher.game is None and sensor.native_value == "No Game"
        assert player.media_image_url is None and sensor.entity_picture is None
        requests["Ending"].set_result("https://cdn/ending.png")
        await asyncio.sleep(0)
        assert player.media_image_url is None
        await event(None, member("Broken"))
        await asyncio.sleep(0)
        requests["Broken"].set_exception(RuntimeError("external provider"))
        await asyncio.sleep(0)
        assert watcher.game == "Broken"
        assert (
            player.media_image_url == sensor.entity_picture == "https://cdn/discord.png"
        )
        await event(None, member("Unloading"))
        await asyncio.sleep(0)
        generation = watcher._activity_generation
        unloads[0]()
        assert watcher._activity_generation == generation + 1
        await asyncio.gather(*tasks, return_exceptions=True)
        assert all(task.done() for task in tasks)

    asyncio.run(run())
