# ruff: noqa: E402

import logging
import warnings
from typing import Any, Dict, Optional

import homeassistant.helpers.config_validation as cv

# Older nextcord builds used 'return' in 'finally' blocks. Python 3.14 emits
# that as a SyntaxWarning during import, before normal logging can classify it.
warnings.filterwarnings(
    "ignore",
    message=r"'return' in a 'finally' block",
    category=SyntaxWarning,
)

import nextcord
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_ACCESS_TOKEN
from homeassistant.core import callback
from homeassistant.helpers import selector
from nextcord import LoginFailure

from .const import (
    CONF_CHANNELS,
    CONF_ENABLE_REACTIONS,
    CONF_ENABLE_SUB_SENSORS,
    CONF_ENABLE_VOICE,
    CONF_IMAGE_FORMAT,
    CONF_IGDB_CLIENT_ID,
    CONF_IGDB_CLIENT_SECRET,
    CONF_LEAN_INTENTS,
    CONF_MEMBERS,
    CONF_STEAMGRIDDB_API_KEY,
    DEFAULT_ENABLE_REACTIONS,
    DEFAULT_ENABLE_SUB_SENSORS,
    DEFAULT_ENABLE_VOICE,
    DEFAULT_LEAN_INTENTS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

IMAGE_FORMAT_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=["png", "webp", "jpeg", "jpg"],
        multiple=False,
        mode=selector.SelectSelectorMode.DROPDOWN,
    ),
)

AUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ACCESS_TOKEN): cv.string,
        vol.Required(CONF_IMAGE_FORMAT, default="webp"): IMAGE_FORMAT_SELECTOR,
    }
)


async def _fetch_guild_data(token: str) -> tuple[dict, dict]:
    """Log in to Discord, fetch members and channels of all guilds, then close."""
    client = nextcord.Client(intents=nextcord.Intents.all())
    try:
        await client.login(token)
        members: dict = {}
        channels: dict = {}
        async for guild in _aiter_guilds(client):
            async for member in guild.fetch_members():
                members[member.name] = member
            for channel in await guild.fetch_channels():
                channels[channel.name] = channel
        _LOGGER.debug("Found %d members, %d channels", len(members), len(channels))
        return members, channels
    finally:
        await client.close()


async def _aiter_guilds(client: nextcord.Client):
    async for guild in client.fetch_guilds():
        yield guild


class DiscordGameConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    data: Optional[Dict[str, Any]]

    def __init__(self):
        self.members: dict = {}
        self.channels: dict = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> "DiscordGameOptionsFlow":
        return DiscordGameOptionsFlow(config_entry)

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None):
        errors: Dict[str, str] = {}
        if user_input is not None:
            try:
                self.members, self.channels = await _fetch_guild_data(user_input[CONF_ACCESS_TOKEN])
            except LoginFailure:
                errors["base"] = "auth"
            if not errors:
                self.data = dict(user_input)
                self.data[CONF_MEMBERS] = []
                self.data[CONF_CHANNELS] = []
                return await self.async_step_members()

        return self.async_show_form(step_id="user", data_schema=AUTH_SCHEMA, errors=errors)

    async def async_step_members(self, user_input: Optional[Dict[str, Any]] = None):
        schema = vol.Schema(
            {
                vol.Optional(CONF_MEMBERS): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=list(self.members.keys()),
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    ),
                ),
                vol.Optional(CONF_CHANNELS): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=list(self.channels.keys()),
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    ),
                ),
            }
        )

        if user_input is not None:
            for user in user_input.get(CONF_MEMBERS, []):
                self.data[CONF_MEMBERS].append(self.members[user].id)
            for channel in user_input.get(CONF_CHANNELS, []):
                self.data[CONF_CHANNELS].append(self.channels[channel].id)
            return self.async_create_entry(title="Discord Game", data=self.data)

        return self.async_show_form(step_id="members", data_schema=schema)


class DiscordGameOptionsFlow(config_entries.OptionsFlow):
    """Options menu: feature toggles, member/channel re-selection, token transfer."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        # NOTE: do not assign self.config_entry — in HA 2024.12+ it is a
        # read-only property injected by the framework. Writing it raises
        # AttributeError, which surfaces in the UI as a 500 when opening
        # the options dialog.
        self._members: dict = {}
        self._channels: dict = {}

    async def async_step_init(self, user_input: Optional[Dict[str, Any]] = None):
        return self.async_show_menu(
            step_id="init",
            menu_options=["features", "artwork", "members", "transfer"],
        )

    async def async_step_features(self, user_input: Optional[Dict[str, Any]] = None):
        current = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            options = dict(self.config_entry.options)
            options.update(user_input)
            return self.async_create_entry(title="", data=options)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ENABLE_REACTIONS,
                    default=current.get(CONF_ENABLE_REACTIONS, DEFAULT_ENABLE_REACTIONS),
                ): bool,
                vol.Required(
                    CONF_ENABLE_VOICE,
                    default=current.get(CONF_ENABLE_VOICE, DEFAULT_ENABLE_VOICE),
                ): bool,
                vol.Required(
                    CONF_ENABLE_SUB_SENSORS,
                    default=current.get(CONF_ENABLE_SUB_SENSORS, DEFAULT_ENABLE_SUB_SENSORS),
                ): bool,
                vol.Required(
                    CONF_LEAN_INTENTS,
                    default=current.get(CONF_LEAN_INTENTS, DEFAULT_LEAN_INTENTS),
                ): bool,
                vol.Required(
                    CONF_IMAGE_FORMAT,
                    default=current.get(CONF_IMAGE_FORMAT, "webp"),
                ): IMAGE_FORMAT_SELECTOR,
            }
        )
        return self.async_show_form(step_id="features", data_schema=schema)

    async def async_step_artwork(self, user_input: Optional[Dict[str, Any]] = None):
        """Configure optional game-database credentials."""
        current = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            options = dict(self.config_entry.options)
            options.update(user_input)
            return self.async_create_entry(title="", data=options)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_IGDB_CLIENT_ID,
                    default=current.get(CONF_IGDB_CLIENT_ID, ""),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                ),
                vol.Optional(
                    CONF_IGDB_CLIENT_SECRET,
                    default=current.get(CONF_IGDB_CLIENT_SECRET, ""),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
                vol.Optional(
                    CONF_STEAMGRIDDB_API_KEY,
                    default=current.get(CONF_STEAMGRIDDB_API_KEY, ""),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(step_id="artwork", data_schema=schema)

    async def async_step_members(self, user_input: Optional[Dict[str, Any]] = None):
        errors: Dict[str, str] = {}
        token = self.config_entry.data[CONF_ACCESS_TOKEN]
        if not self._members:
            try:
                self._members, self._channels = await _fetch_guild_data(token)
            except LoginFailure:
                errors["base"] = "auth"
                return self.async_abort(reason="auth")

        current_member_ids = set(self.config_entry.data.get(CONF_MEMBERS, []))
        current_channel_ids = set(self.config_entry.data.get(CONF_CHANNELS, []))
        preselected_members = [n for n, m in self._members.items() if m.id in current_member_ids]
        preselected_channels = [n for n, c in self._channels.items() if c.id in current_channel_ids]

        if user_input is not None:
            new_data = dict(self.config_entry.data)
            new_data[CONF_MEMBERS] = [self._members[n].id for n in user_input.get(CONF_MEMBERS, [])]
            new_data[CONF_CHANNELS] = [self._channels[n].id for n in user_input.get(CONF_CHANNELS, [])]
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            return self.async_create_entry(title="", data=self.config_entry.options)

        schema = vol.Schema(
            {
                vol.Optional(CONF_MEMBERS, default=preselected_members): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=list(self._members.keys()),
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    ),
                ),
                vol.Optional(CONF_CHANNELS, default=preselected_channels): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=list(self._channels.keys()),
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    ),
                ),
            }
        )
        return self.async_show_form(step_id="members", data_schema=schema, errors=errors)

    async def async_step_transfer(self, user_input: Optional[Dict[str, Any]] = None):
        """Token transfer: display the current token; on confirm, remove this entry."""
        token = self.config_entry.data.get(CONF_ACCESS_TOKEN, "")

        if user_input is not None:
            if user_input.get("confirm_remove"):
                self.hass.async_create_task(
                    self.hass.config_entries.async_remove(self.config_entry.entry_id)
                )
                return self.async_abort(reason="transferred")
            return self.async_abort(reason="transfer_cancelled")

        schema = vol.Schema(
            {
                vol.Required("displayed_token", default=token): cv.string,
                vol.Required("confirm_remove", default=False): bool,
            }
        )
        return self.async_show_form(step_id="transfer", data_schema=schema)
