"""Support for oref alerts geo location events."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import homeassistant.util.dt as dt_util
from haversine import haversine
from homeassistant.components.geo_location import ATTR_SOURCE, GeolocationEvent
from homeassistant.const import (
    ATTR_DATE,
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    Platform,
    UnitOfLength,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

from .const import (
    DATA_COORDINATOR,
    DOMAIN,
    IST,
    LOCATION_ID_SUFFIX,
    OREF_ALERT_UNIQUE_ID,
)
from .metadata.area_info import AREA_INFO

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import OrefAlertDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Initialize config entry."""
    OrefAlertLocationEventManager(hass, config_entry, async_add_entities)


class OrefAlertLocationEvent(GeolocationEvent):
    """Represents an oref alert."""

    _attr_should_poll = False
    _attr_source = DOMAIN
    _attr_has_entity_name = True
    _entity_component_unrecorded_attributes = frozenset(
        {
            ATTR_SOURCE,
            ATTR_LATITUDE,
            ATTR_LONGITUDE,
            ATTR_DATE,
        }
    )

    def __init__(
        self,
        hass: HomeAssistant,
        area: str,
        date: datetime | None,
    ) -> None:
        """Initialize entity."""
        self._hass = hass
        self._attr_name = area
        self._attr_unique_id = (
            f"{OREF_ALERT_UNIQUE_ID}_{LOCATION_ID_SUFFIX}_"
            + slugify(AREA_INFO[area]["en"])
            + f"_{int(time.time())}"
        )
        self._attr_latitude = AREA_INFO[area]["lat"]
        self._attr_longitude = AREA_INFO[area]["long"]
        self._attr_unit_of_measurement = UnitOfLength.KILOMETERS
        self._attr_distance = haversine(
            (hass.config.latitude, hass.config.longitude),
            (self._attr_latitude, self._attr_longitude),
        )
        self._attr_extra_state_attributes = {ATTR_DATE: date}

    @property
    def suggested_object_id(self) -> str | None:
        """Return input for object id."""
        return self._attr_unique_id

    def async_remove_self(self) -> None:
        """Remove this entity."""
        self._hass.async_create_task(self.async_remove(force_remove=True))


class OrefAlertLocationEventManager:
    """Add and remove location event entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
    ) -> None:
        """Initialize object with defaults."""
        self._location_events: dict[str, OrefAlertLocationEvent] = {}
        self._hass = hass
        self._config_entry = config_entry
        self._async_add_entities = async_add_entities
        self._coordinator: OrefAlertDataUpdateCoordinator = hass.data[DOMAIN][
            config_entry.entry_id
        ][DATA_COORDINATOR]
        self._async_clean_start()
        self._coordinator.async_add_listener(self._async_update)
        self._async_update()

    def _async_clean_start(self) -> None:
        """Remove all geo_location entities for a clean start."""
        entity_registry = er.async_get(self._hass)
        entries = er.async_entries_for_config_entry(
            entity_registry, self._config_entry.entry_id
        )
        for entry in entries or []:
            if entry.domain == Platform.GEO_LOCATION:
                entity_registry.async_remove(entry.entity_id)

    def _alert_date(self, area: str) -> datetime | None:
        """Return the alert time as a datetime object."""
        for alert in self._coordinator.data.active_alerts:
            if alert["data"] == area:
                if (
                    alert_date := dt_util.parse_datetime(alert["alertDate"])
                ) is not None:
                    return alert_date.replace(tzinfo=IST)
                return None
        return None

    @callback
    async def _cleanup_entities(self) -> None:
        """Remove entities."""
        await asyncio.sleep(10)  # Wait for a stable state.
        entity_registry = er.async_get(self._hass)
        active = {alert["data"] for alert in self._coordinator.data.active_alerts}
        areas_to_delete = set(self._location_events.keys()) - active
        for area in areas_to_delete:
            if (entity := self._location_events.pop(area, None)) is not None:
                entity.async_remove_self()
                entity_registry.async_remove(entity.entity_id)

    @callback
    def _async_update(self) -> None:
        """Add and/or remove entities according to the new active alerts list."""
        active = {alert["data"] for alert in self._coordinator.data.active_alerts}
        exists = set(self._location_events.keys())

        to_add = {
            area: OrefAlertLocationEvent(self._hass, area, self._alert_date(area))
            for area in active - exists
            if area in AREA_INFO
        }
        self._location_events.update(to_add)
        self._async_add_entities(to_add.values())

        if len(exists - active):
            self._hass.async_create_task(self._cleanup_entities())
