"""Persistent storage for DWWT Manager."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION
from .models import PersistentState


class DwwtStore:
    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict] = Store(hass, STORAGE_VERSION, STORAGE_KEY.format(entry_id=entry_id))

    async def load(self) -> PersistentState:
        return PersistentState.from_storage(await self._store.async_load())

    async def save(self, state: PersistentState) -> None:
        await self._store.async_save(state.as_storage())
