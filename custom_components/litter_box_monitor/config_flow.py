"""Config, reconfigure and options flows for Litter Box Monitor."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, selector
import voluptuous as vol

from .const import (
    CONF_BAG_DOOR,
    CONF_CLEANING_TIMEOUT,
    CONF_FAULT_EVENTS,
    CONF_FAULT_MONITORING,
    CONF_HISTORY_RETENTION,
    CONF_INITIAL_BAG_DOOR_OPENED,
    CONF_INITIALIZE_BAG_DOOR_NOW,
    CONF_MAIN_DOOR,
    CONF_MAINTENANCE_THRESHOLD,
    CONF_MAINTENANCE_TRACKING,
    CONF_STATISTICS,
    DEFAULT_BAG_DOOR,
    DEFAULT_MAIN_DOOR,
    DEFAULT_NAME,
    DEFAULT_OPTIONS,
    DOMAIN,
    MAX_HISTORY_RETENTION,
    MIN_HISTORY_RETENTION,
)
from .coordinator import parse_timestamp

_BINARY_SENSOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=BINARY_SENSOR_DOMAIN)
)
_BOOL = selector.BooleanSelector()


def _number(minimum: int, maximum: int, unit: str) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=1,
            unit_of_measurement=unit,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


_TIMEOUT = vol.All(_number(1, 120, "min"), vol.Coerce(int))
_THRESHOLD = vol.All(_number(0, 365, "days"), vol.Coerce(int))
_RETENTION = vol.All(
    _number(MIN_HISTORY_RETENTION, MAX_HISTORY_RETENTION, "days"), vol.Coerce(int)
)


def _entity_error(hass: HomeAssistant, entity_id: str) -> str | None:
    """Validate that an entity is an existing binary sensor."""
    if entity_id.split(".", 1)[0] != BINARY_SENSOR_DOMAIN:
        return "not_binary_sensor"
    if (
        hass.states.get(entity_id) is None
        and er.async_get(hass).async_get(entity_id) is None
    ):
        return "entity_not_found"
    return None


def _validate_inputs(
    hass: HomeAssistant, user_input: dict[str, Any], maintenance: bool
) -> dict[str, str]:
    errors: dict[str, str] = {}
    main = user_input[CONF_MAIN_DOOR]
    bag = user_input.get(CONF_BAG_DOOR)
    if error := _entity_error(hass, main):
        errors[CONF_MAIN_DOOR] = error
    if bag:
        if error := _entity_error(hass, bag):
            errors[CONF_BAG_DOOR] = error
        elif bag == main:
            errors[CONF_BAG_DOOR] = "same_entity"
    elif maintenance:
        errors[CONF_BAG_DOOR] = "bag_door_required"
    return errors


def _default_entity(hass: HomeAssistant, entity_id: str) -> str | None:
    return entity_id if hass.states.get(entity_id) is not None else None


def _inputs_schema(
    defaults: dict[str, Any], include_name: bool = True
) -> dict[vol.Marker, Any]:
    schema: dict[vol.Marker, Any] = {}
    if include_name:
        schema[
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME))
        ] = selector.TextSelector()
    main = defaults.get(CONF_MAIN_DOOR)
    bag = defaults.get(CONF_BAG_DOOR)
    schema[vol.Required(CONF_MAIN_DOOR, description={"suggested_value": main})] = (
        _BINARY_SENSOR
    )
    schema[vol.Optional(CONF_BAG_DOOR, description={"suggested_value": bag})] = (
        _BINARY_SENSOR
    )
    return schema


_BEHAVIOUR_KEYS = (
    CONF_CLEANING_TIMEOUT,
    CONF_FAULT_MONITORING,
    CONF_MAINTENANCE_TRACKING,
    CONF_STATISTICS,
    CONF_FAULT_EVENTS,
)


def _behaviour_schema(options: dict[str, Any]) -> dict[vol.Marker, Any]:
    return {
        vol.Required(
            CONF_CLEANING_TIMEOUT, default=options[CONF_CLEANING_TIMEOUT]
        ): _TIMEOUT,
        vol.Required(
            CONF_FAULT_MONITORING, default=options[CONF_FAULT_MONITORING]
        ): _BOOL,
        vol.Required(
            CONF_MAINTENANCE_TRACKING, default=options[CONF_MAINTENANCE_TRACKING]
        ): _BOOL,
        vol.Required(CONF_STATISTICS, default=options[CONF_STATISTICS]): _BOOL,
        vol.Required(CONF_FAULT_EVENTS, default=options[CONF_FAULT_EVENTS]): _BOOL,
    }


class LitterBoxConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        self._data: dict[str, Any] = {}
        self._options: dict[str, Any] = {}
        self._title = DEFAULT_NAME

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> LitterBoxOptionsFlow:
        """Return the options flow."""
        return LitterBoxOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select inputs and core behaviour."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_inputs(
                self.hass, user_input, user_input[CONF_MAINTENANCE_TRACKING]
            )
            if not errors:
                self._async_abort_entries_match(
                    {CONF_MAIN_DOOR: user_input[CONF_MAIN_DOOR]}
                )
                self._title = user_input[CONF_NAME].strip() or DEFAULT_NAME
                self._data = {CONF_MAIN_DOOR: user_input[CONF_MAIN_DOOR]}
                if bag := user_input.get(CONF_BAG_DOOR):
                    self._data[CONF_BAG_DOOR] = bag
                self._options = {
                    **DEFAULT_OPTIONS,
                    **{k: user_input[k] for k in _BEHAVIOUR_KEYS},
                }
                if self._options[CONF_MAINTENANCE_TRACKING]:
                    return await self.async_step_maintenance()
                return self._create()

        defaults = user_input or {
            CONF_MAIN_DOOR: _default_entity(self.hass, DEFAULT_MAIN_DOOR),
            CONF_BAG_DOOR: _default_entity(self.hass, DEFAULT_BAG_DOOR),
        }
        schema = vol.Schema(
            {**_inputs_schema(defaults), **_behaviour_schema(DEFAULT_OPTIONS)}
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    async def async_step_maintenance(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Maintenance reminder and optional initial bag door timestamp."""
        errors: dict[str, str] = {}
        if user_input is not None:
            raw = (user_input.get(CONF_INITIAL_BAG_DOOR_OPENED) or "").strip()
            now_flag = user_input.get(CONF_INITIALIZE_BAG_DOOR_NOW, False)
            if raw and now_flag:
                errors["base"] = "conflicting_initialization"
            elif raw:
                try:
                    parse_timestamp(raw)
                except ValueError:
                    errors[CONF_INITIAL_BAG_DOOR_OPENED] = "invalid_timestamp"
            if not errors:
                self._options[CONF_MAINTENANCE_THRESHOLD] = user_input[
                    CONF_MAINTENANCE_THRESHOLD
                ]
                if raw:
                    self._data[CONF_INITIAL_BAG_DOOR_OPENED] = raw
                elif now_flag:
                    self._data[CONF_INITIALIZE_BAG_DOOR_NOW] = True
                return self._create()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MAINTENANCE_THRESHOLD,
                    default=DEFAULT_OPTIONS[CONF_MAINTENANCE_THRESHOLD],
                ): _THRESHOLD,
                vol.Optional(CONF_INITIAL_BAG_DOOR_OPENED): selector.TextSelector(),
                vol.Optional(CONF_INITIALIZE_BAG_DOOR_NOW, default=False): _BOOL,
            }
        )
        return self.async_show_form(
            step_id="maintenance",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    @callback
    def _create(self) -> ConfigFlowResult:
        return self.async_create_entry(
            title=self._title, data=self._data, options=self._options
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the input sensors; stored history is kept."""
        entry = self._get_reconfigure_entry()
        maintenance = {**DEFAULT_OPTIONS, **entry.options}[CONF_MAINTENANCE_TRACKING]
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_inputs(self.hass, user_input, maintenance)
            if not errors:
                main = user_input[CONF_MAIN_DOOR]
                for other in self._async_current_entries(include_ignore=False):
                    if (
                        other.entry_id != entry.entry_id
                        and other.data.get(CONF_MAIN_DOOR) == main
                    ):
                        return self.async_abort(reason="already_configured")
                data = {**entry.data, CONF_MAIN_DOOR: main}
                data.pop(CONF_BAG_DOOR, None)
                if bag := user_input.get(CONF_BAG_DOOR):
                    data[CONF_BAG_DOOR] = bag
                return self.async_update_reload_and_abort(
                    entry,
                    title=user_input[CONF_NAME].strip() or entry.title,
                    data=data,
                )
        defaults = user_input or {CONF_NAME: entry.title, **entry.data}
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(_inputs_schema(defaults)),
            errors=errors,
        )


class LitterBoxOptionsFlow(OptionsFlowWithReload):
    """Tune behaviour without touching stored history."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_MAINTENANCE_TRACKING] and not self.config_entry.data.get(
                CONF_BAG_DOOR
            ):
                errors[CONF_MAINTENANCE_TRACKING] = "bag_door_required"
            else:
                return self.async_create_entry(
                    data={**self.config_entry.options, **user_input}
                )

        options = {**DEFAULT_OPTIONS, **self.config_entry.options}
        schema = vol.Schema(
            {
                **_behaviour_schema(options),
                vol.Required(
                    CONF_MAINTENANCE_THRESHOLD,
                    default=options[CONF_MAINTENANCE_THRESHOLD],
                ): _THRESHOLD,
                vol.Required(
                    CONF_HISTORY_RETENTION, default=options[CONF_HISTORY_RETENTION]
                ): _RETENTION,
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )
