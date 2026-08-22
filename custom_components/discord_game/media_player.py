import logging

from homeassistant import config_entries, core
from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.components.media_player.const import MediaType
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN
from .sensor import DiscordAsyncMemberState

_LOGGER = logging.getLogger(__name__)

ENTITY_ID_FORMAT = "media_player.discord_game_{}"


async def async_setup_entry(
    hass: core.HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities,
) -> None:
    """Set up Discord Game media player entities from a config entry."""
    watchers: dict = hass.data[DOMAIN][config_entry.entry_id].get("watchers", {})
    media_players = []
    for watcher in watchers.values():
        mp = DiscordGameMediaPlayer(watcher)
        watcher.extra_entities.append(mp)
        media_players.append(mp)
    if media_players:
        async_add_entities(media_players)


class DiscordGameMediaPlayer(MediaPlayerEntity):
    """Media player entity representing the game a Discord user is currently playing."""

    def __init__(self, watcher: DiscordAsyncMemberState) -> None:
        self._watcher = watcher
        self.entity_id = ENTITY_ID_FORMAT.format(watcher.userid)

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def unique_id(self) -> str:
        return ENTITY_ID_FORMAT.format(self._watcher.userid)

    @property
    def name(self) -> str:
        return f"{self._watcher.member} Game"

    @property
    def state(self) -> MediaPlayerState:
        user_state = self._watcher._state
        if user_state in ("offline", "unknown"):
            return MediaPlayerState.OFF
        if self._watcher.game:
            return MediaPlayerState.PLAYING
        return MediaPlayerState.IDLE

    @property
    def media_title(self) -> str | None:
        return self._watcher.game or None

    @property
    def media_content_type(self) -> str:
        return MediaType.GAME

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        return MediaPlayerEntityFeature(0)

    @property
    def media_image_url(self) -> str | None:
        return self._watcher.game_image_url

    @property
    def media_image_remotely_accessible(self) -> bool:
        return True

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, str(self._watcher.userid))},
            name=self._watcher.member,
        )
