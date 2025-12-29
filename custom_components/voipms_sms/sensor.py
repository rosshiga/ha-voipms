"""Sensor platform for VoIP.ms SMS incoming messages."""
import logging
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the VoIP.ms SMS sensor platform."""
    if discovery_info is None:
        return

    phone_number = discovery_info.get("phone_number")
    webhook_id = discovery_info.get("webhook_id")
    
    if not phone_number or not webhook_id:
        _LOGGER.error("Missing phone_number or webhook_id in discovery_info")
        return

    sensor = VoIPMSIncomingSMSSensor(hass, phone_number, webhook_id)
    async_add_entities([sensor], True)
    
    # Store sensor reference in hass.data for webhook updates
    hass.data.setdefault("voipms_sms_sensors", {})[phone_number] = sensor


class VoIPMSIncomingSMSSensor(SensorEntity):
    """Sensor for incoming SMS messages on a specific phone number."""

    def __init__(self, hass: HomeAssistant, phone_number: str, webhook_id: str) -> None:
        """Initialize the sensor."""
        self._hass = hass
        self._phone_number = phone_number
        self._webhook_id = webhook_id
        self._attr_name = f"VoIP.ms SMS {phone_number}"
        self._attr_unique_id = f"voipms_sms_incoming_{phone_number}"
        self._state = "No messages"
        self._from = None
        self._message = None
        self._last_updated = None
        self._message_id = None

    @property
    def state(self) -> str:
        """Return the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return sensor attributes."""
        base_url = self._hass.config.external_url or self._hass.config.internal_url or "http://your-ha-instance:8123"
        webhook_url = f"{base_url}/api/webhook/{self._webhook_id}"
        
        return {
            "from": self._from,
            "message": self._message,
            "last_updated": self._last_updated,
            "message_id": self._message_id,
            "phone_number": self._phone_number,
            "webhook_url": webhook_url,
        }

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:message-text-outline"

    @callback
    def update_from_webhook(self, data: dict) -> None:
        """Update sensor from incoming webhook data."""
        try:
            payload = data.get("data", {}).get("payload", {})
            
            self._from = payload.get("from", {}).get("phone_number")
            self._message = payload.get("text")
            self._message_id = payload.get("id")
            self._last_updated = datetime.now().isoformat()
            self._state = f"Message from {self._from}" if self._from else "New message"
            
            self.async_write_ha_state()
            _LOGGER.info(
                "voipms_sms: Received SMS on %s from %s: %s",
                self._phone_number,
                self._from,
                self._message
            )
        except Exception as e:
            _LOGGER.error("voipms_sms: Error updating sensor from webhook: %s", e)

