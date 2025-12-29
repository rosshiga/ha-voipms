"""Webhook handler for VoIP.ms incoming SMS."""
import logging
import secrets
import hashlib
from aiohttp import web

from homeassistant.core import HomeAssistant
from homeassistant.components import persistent_notification
from homeassistant.components.http import HomeAssistantView

_LOGGER = logging.getLogger(__name__)

WEBHOOK_ID_PREFIX = "voipms_sms_"


def generate_webhook_id(phone_number: str, secret_key: str) -> str:
    """Generate a secure webhook ID for a phone number."""
    # Create a deterministic but secure webhook ID using phone + secret
    combined = f"{phone_number}:{secret_key}"
    hash_digest = hashlib.sha256(combined.encode()).hexdigest()[:16]
    return f"{WEBHOOK_ID_PREFIX}{phone_number}_{hash_digest}"


def generate_secret_key() -> str:
    """Generate a random secret key."""
    return secrets.token_hex(16)


async def handle_webhook(hass: HomeAssistant, webhook_id: str, request: web.Request) -> web.Response:
    """Handle incoming webhook requests."""
    try:
        data = await request.json()
        _LOGGER.debug("voipms_sms: Received webhook data: %s", data)
        
        # Validate the payload structure
        if not isinstance(data, dict):
            _LOGGER.error("voipms_sms: Invalid webhook payload - not a dict")
            return web.Response(status=400, text="Invalid payload")

        inner_data = data.get("data", {})
        event_type = inner_data.get("event_type")
        record_type = inner_data.get("record_type")
        payload = inner_data.get("payload", {})
        payload_record_type = payload.get("record_type")

        # Validate expected event/record types
        if event_type != "message.received":
            error_msg = f"Unknown event_type received: {event_type}"
            _LOGGER.warning("voipms_sms: %s", error_msg)
            await _send_notification(hass, "VoIP.ms SMS Error", error_msg)
            return web.Response(status=400, text=error_msg)

        if record_type != "event":
            error_msg = f"Unknown record_type received: {record_type}"
            _LOGGER.warning("voipms_sms: %s", error_msg)
            await _send_notification(hass, "VoIP.ms SMS Error", error_msg)
            return web.Response(status=400, text=error_msg)

        if payload_record_type != "message":
            error_msg = f"Unknown payload record_type received: {payload_record_type}"
            _LOGGER.warning("voipms_sms: %s", error_msg)
            await _send_notification(hass, "VoIP.ms SMS Error", error_msg)
            return web.Response(status=400, text=error_msg)

        # Extract the "to" phone number to find the right sensor
        to_numbers = payload.get("to", [])
        if not to_numbers:
            error_msg = "No destination phone number in payload"
            _LOGGER.error("voipms_sms: %s", error_msg)
            return web.Response(status=400, text=error_msg)

        # Find matching sensor and update it
        sensors = hass.data.get("voipms_sms_sensors", {})
        updated = False
        
        for to_entry in to_numbers:
            phone = to_entry.get("phone_number", "").lstrip("+").lstrip("1")
            # Try to match with or without country code
            for stored_phone, sensor in sensors.items():
                stored_clean = stored_phone.lstrip("+").lstrip("1")
                if phone == stored_clean or phone.endswith(stored_clean) or stored_clean.endswith(phone):
                    sensor.update_from_webhook(data)
                    updated = True
                    break

        if not updated:
            _LOGGER.warning(
                "voipms_sms: No sensor found for phone numbers: %s",
                [t.get("phone_number") for t in to_numbers]
            )

        return web.Response(status=200, text="OK")

    except Exception as e:
        error_msg = f"Error processing webhook: {str(e)}"
        _LOGGER.error("voipms_sms: %s", error_msg)
        await _send_notification(hass, "VoIP.ms SMS Error", error_msg)
        return web.Response(status=500, text=error_msg)


async def _send_notification(hass: HomeAssistant, title: str, message: str) -> None:
    """Send a persistent notification."""
    persistent_notification.async_create(
        hass,
        message,
        title,
        "voipms_sms_error"
    )

