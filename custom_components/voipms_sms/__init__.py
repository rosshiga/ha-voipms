import logging
import aiohttp
import asyncio
import base64
import os
import mimetypes
import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant.core import HomeAssistant
from homeassistant.components.webhook import async_register, async_unregister
from homeassistant.helpers.discovery import async_load_platform

from .webhook import generate_webhook_id, generate_secret_key, handle_webhook

_LOGGER = logging.getLogger(__name__)

DOMAIN = "voipms_sms"
DATA_KEY = "voipms_sms_data"

# Define configuration schema
CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required("account_user"): cv.string,
        vol.Required("api_password"): cv.string,
        vol.Required("did"): cv.string,
    })
}, extra=vol.ALLOW_EXTRA)

REST_ENDPOINT = "https://voip.ms/api/v1/rest.php"


async def get_base64_data(image_path):
    def encode():
        mime_type, _ = mimetypes.guess_type(image_path)
        if not mime_type:
            mime_type = 'application/octet-stream'
        with open(image_path, 'rb') as f:
            encoded = base64.b64encode(f.read()).decode()
        return f"data:{mime_type};base64,{encoded}"
    return await asyncio.to_thread(encode)


async def async_setup_entry(hass: HomeAssistant, entry):
    """Set up VoIP.ms SMS from a config entry."""
    return await async_setup(hass, {DOMAIN: entry.data})


async def send_sms(hass, user, password, sender_did, call):
    """Send SMS using VoIP.ms API."""
    recipient = call.data.get("recipient")
    message = call.data.get("message")

    if not recipient or not message:
        _LOGGER.error("Recipient or message missing.")
        return

    params = {
        "api_username": user,
        "api_password": password,
        "did": sender_did,
        "dst": recipient,
        "method": "sendSMS",
        "message": message,
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(REST_ENDPOINT, params=params) as response:
            result = await response.text()
            if response.status == 200:
                _LOGGER.info("voipms_sms: SMS sent successfully: %s", result)
            else:
                _LOGGER.error("voipms_sms: Failed to send SMS. Status: %s, Response: %s", response.status, result)


async def send_mms(hass, user, password, sender_did, call):
    """Send MMS using VoIP.ms API."""
    recipient = call.data.get("recipient")
    message = call.data.get("message")
    image_path = call.data.get("image_path")

    if not recipient or not message or not image_path:
        _LOGGER.error("voipms_sms: Required parameter missing (Recipient or message or image path)")
        return

    if not os.path.exists(image_path):
        _LOGGER.error("voipms_sms: Image file not found: %s", image_path)
        return

    media_data = await get_base64_data(image_path)

    form_data = {
        'api_username': str(user), 
        'api_password': str(password),
        'did': str(sender_did),
        'dst': str(recipient),
        'message': str(message),
        'method': str('sendMMS'),
        'media1': str(media_data)
    }

    async with aiohttp.ClientSession() as session:
        with aiohttp.MultipartWriter("form-data") as mp:
            for key, value in form_data.items():
                part = mp.append(value)
                part.set_content_disposition('form-data', name=key)

        async with session.post(REST_ENDPOINT, data=mp) as response:
            response_text = await response.text()
            if response.status == 200:
                _LOGGER.info("voipms_sms: MMS sent successfully: %s", response_text)
            else:
                _LOGGER.error("voipms_sms: Failed to send MMS. Status: %s, Response: %s", response.status, response_text)


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the VoIP.ms SMS integration."""
    conf = config.get(DOMAIN, {})
    user = conf.get("account_user")
    password = conf.get("api_password")
    did = conf.get("did")

    if not user or not password or not did:
        _LOGGER.error("Missing required configuration fields.")
        return False

    # Initialize data storage
    hass.data.setdefault(DATA_KEY, {
        "webhooks": {},
        "secret_keys": {},
        "did": did,
    })
    hass.data.setdefault("voipms_sms_sensors", {})

    # Generate or retrieve secret key for this DID
    if did not in hass.data[DATA_KEY]["secret_keys"]:
        hass.data[DATA_KEY]["secret_keys"][did] = generate_secret_key()
    
    secret_key = hass.data[DATA_KEY]["secret_keys"][did]
    webhook_id = generate_webhook_id(did, secret_key)
    
    # Store webhook info
    hass.data[DATA_KEY]["webhooks"][did] = webhook_id
    
    # Register webhook
    async_register(
        hass,
        DOMAIN,
        f"VoIP.ms SMS Webhook for {did}",
        webhook_id,
        lambda hass, wid, req: handle_webhook(hass, wid, req),
    )
    
    _LOGGER.info(
        "voipms_sms: Registered webhook for %s with ID: %s",
        did,
        webhook_id
    )

    # Load sensor platform for this DID
    hass.async_create_task(
        async_load_platform(
            hass,
            "sensor",
            DOMAIN,
            {"phone_number": did, "webhook_id": webhook_id},
            config,
        )
    )

    # Register SMS/MMS sending services
    async def handle_send_sms(call):
        await send_sms(hass, user, password, did, call)

    async def handle_send_mms(call):
        await send_mms(hass, user, password, did, call)

    async def handle_get_webhook_url(call):
        """Service to get webhook URL for the configured DID."""
        webhook_id = hass.data[DATA_KEY]["webhooks"].get(did)
        
        if not webhook_id:
            _LOGGER.error("voipms_sms: No webhook found for DID: %s", did)
            return
        
        base_url = hass.config.external_url or hass.config.internal_url or "http://your-ha-instance:8123"
        webhook_url = f"{base_url}/api/webhook/{webhook_id}"
        
        # Fire an event with the webhook URL
        hass.bus.async_fire(
            "voipms_sms_webhook_url",
            {"phone_number": did, "webhook_url": webhook_url}
        )
        _LOGGER.info("voipms_sms: Webhook URL for %s: %s", did, webhook_url)

    hass.services.async_register(DOMAIN, "send_sms", handle_send_sms)
    hass.services.async_register(DOMAIN, "send_mms", handle_send_mms)
    hass.services.async_register(DOMAIN, "get_webhook_url", handle_get_webhook_url)

    _LOGGER.info("voipms_sms: VoIP.ms SMS/MMS services registered successfully.")
    return True


async def async_unload_entry(hass: HomeAssistant, entry):
    """Unload VoIP.ms SMS config entry."""
    # Unregister webhooks
    for phone_number, webhook_id in hass.data.get(DATA_KEY, {}).get("webhooks", {}).items():
        try:
            async_unregister(hass, webhook_id)
            _LOGGER.info("voipms_sms: Unregistered webhook for %s", phone_number)
        except Exception as e:
            _LOGGER.warning("voipms_sms: Failed to unregister webhook: %s", e)
    
    return True
