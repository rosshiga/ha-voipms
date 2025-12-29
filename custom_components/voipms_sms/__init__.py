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


async def _setup_voipms_sms(hass: HomeAssistant, user: str, password: str, did: str, config: dict = None):
    """Shared setup logic for both YAML and config entry setups."""
    if not user or not password or not did:
        _LOGGER.error("Missing required configuration fields: user=%s, password=%s, did=%s", 
                     bool(user), bool(password), bool(did))
        return False

    # Initialize data storage
    hass.data.setdefault(DATA_KEY, {
        "webhooks": {},
        "secret_keys": {},
        "entries": {},
        "yaml_config": None,
    })
    hass.data.setdefault("voipms_sms_sensors", {})
    
    # Store YAML config data if provided (for backward compatibility)
    if config:
        hass.data[DATA_KEY]["yaml_config"] = {
            "account_user": user,
            "api_password": password,
            "did": did,
        }

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

    # Check if sensor already exists for this DID to avoid duplicates
    sensors = hass.data.get("voipms_sms_sensors", {})
    if did not in sensors:
        # Load sensor platform for this DID
        discovery_info = {"phone_number": did, "webhook_id": webhook_id}
        hass.async_create_task(
            async_load_platform(
                hass,
                "sensor",
                DOMAIN,
                discovery_info,
                config or {},
            )
        )
    else:
        _LOGGER.debug("voipms_sms: Sensor already exists for DID %s, skipping creation", did)

    return True


async def async_setup_entry(hass: HomeAssistant, entry):
    """Set up VoIP.ms SMS from a config entry."""
    # Store entry data
    hass.data.setdefault(DATA_KEY, {
        "webhooks": {},
        "secret_keys": {},
        "entries": {},
    })
    
    # Extract configuration from entry
    user = entry.data.get("account_user")
    password = entry.data.get("api_password")
    did = entry.data.get("did")
    
    if not user or not password or not did:
        _LOGGER.error("Config entry missing required fields: account_user=%s, api_password=%s, did=%s",
                     bool(user), bool(password), bool(did))
        return False
    
    # Store entry data
    hass.data[DATA_KEY]["entries"][entry.entry_id] = entry.data
    
    # Set up this entry using shared setup logic
    result = await _setup_voipms_sms(hass, user, password, did)
    
    # Register services only once (on first entry)
    if len(hass.data[DATA_KEY]["entries"]) == 1:
        _register_services(hass)
    
    return result


def _validate_phone_number(phone: str) -> bool:
    """Validate phone number format."""
    if not phone:
        return False
    # Remove common formatting characters
    cleaned = phone.replace("+", "").replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
    # Should be numeric and at least 10 digits
    return cleaned.isdigit() and len(cleaned) >= 10


async def send_sms(hass, user, password, sender_did, call):
    """Send SMS using VoIP.ms API."""
    recipient = call.data.get("recipient")
    message = call.data.get("message")

    if not recipient or not message:
        _LOGGER.error("Recipient or message missing.")
        return
    
    # Validate phone number
    if not _validate_phone_number(recipient):
        _LOGGER.error("Invalid recipient phone number format")
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
                _LOGGER.info("voipms_sms: SMS sent successfully")
            else:
                # Don't log full response as it may contain sensitive data
                _LOGGER.error("voipms_sms: Failed to send SMS. Status: %s", response.status)


def _validate_image_path(image_path: str) -> bool:
    """Validate image path to prevent path traversal attacks."""
    if not image_path:
        return False
    
    # Require absolute paths for security
    if not os.path.isabs(image_path):
        return False
    
    # Normalize the path to prevent directory traversal
    normalized = os.path.normpath(image_path)
    absolute_normalized = os.path.abspath(normalized)
    
    # Ensure normalization didn't introduce path traversal
    if normalized != absolute_normalized or ".." in normalized:
        return False
    
    # Additional check: ensure path doesn't contain dangerous patterns
    dangerous_patterns = ["../", "..\\", "~", "/etc/", "/root/", "C:\\Windows\\"]
    normalized_lower = normalized.lower()
    for pattern in dangerous_patterns:
        if pattern.lower() in normalized_lower:
            return False
    
    return True


async def send_mms(hass, user, password, sender_did, call):
    """Send MMS using VoIP.ms API."""
    recipient = call.data.get("recipient")
    message = call.data.get("message")
    image_path = call.data.get("image_path")

    if not recipient or not message or not image_path:
        _LOGGER.error("voipms_sms: Required parameter missing (Recipient or message or image path)")
        return

    # Validate image path for security
    if not _validate_image_path(image_path):
        _LOGGER.error("voipms_sms: Invalid image path - path traversal detected or path not absolute")
        return

    if not os.path.exists(image_path):
        _LOGGER.error("voipms_sms: Image file not found")
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
                _LOGGER.info("voipms_sms: MMS sent successfully")
            else:
                # Don't log full response as it may contain sensitive data
                _LOGGER.error("voipms_sms: Failed to send MMS. Status: %s", response.status)


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the VoIP.ms SMS integration from YAML config."""
    # Only proceed if YAML config is present (not called from config entry)
    if DOMAIN not in config:
        return True  # Config entry setup will handle it
    
    conf = config.get(DOMAIN, {})
    user = conf.get("account_user")
    password = conf.get("api_password")
    did = conf.get("did")

    if not user or not password or not did:
        _LOGGER.error("Missing required configuration fields.")
        return False

    # Use shared setup logic
    result = await _setup_voipms_sms(hass, user, password, did, config)

    # Register services (for YAML config or if not already registered)
    if result and not hass.services.has_service(DOMAIN, "send_sms"):
        _register_services(hass)
    
    return result


def _get_config_data(hass: HomeAssistant):
    """Get configuration data from either config entries or YAML."""
    data_key = hass.data.get(DATA_KEY, {})
    
    # Try config entries first
    entries = data_key.get("entries", {})
    if entries:
        return next(iter(entries.values()))
    
    # Fall back to YAML config
    yaml_config = data_key.get("yaml_config")
    if yaml_config:
        return yaml_config
    
    return None


def _register_services(hass: HomeAssistant):
    """Register domain-level services that work with config entries or YAML config."""
    async def handle_send_sms(call):
        """Handle send_sms service call."""
        config_data = _get_config_data(hass)
        if not config_data:
            _LOGGER.error("voipms_sms: No configuration found. Please set up the integration.")
            return
        
        user = config_data.get("account_user")
        password = config_data.get("api_password")
        did = config_data.get("did")
        
        await send_sms(hass, user, password, did, call)

    async def handle_send_mms(call):
        """Handle send_mms service call."""
        config_data = _get_config_data(hass)
        if not config_data:
            _LOGGER.error("voipms_sms: No configuration found. Please set up the integration.")
            return
        
        user = config_data.get("account_user")
        password = config_data.get("api_password")
        did = config_data.get("did")
        
        # Validate recipient phone number
        recipient = call.data.get("recipient")
        if recipient and not _validate_phone_number(recipient):
            _LOGGER.error("Invalid recipient phone number format")
            return
        
        await send_mms(hass, user, password, did, call)

    async def handle_get_webhook_url(call):
        """Service to get webhook URL for the configured DID - displays in GUI notification."""
        from homeassistant.components import persistent_notification
        
        config_data = _get_config_data(hass)
        if not config_data:
            _LOGGER.error("voipms_sms: No configuration found. Please set up the integration.")
            persistent_notification.async_create(
                hass,
                "No configuration found. Please set up the integration.",
                title="VoIP.ms SMS",
                notification_id="voipms_sms_error"
            )
            return
        
        did = config_data.get("did")
        
        webhook_id = hass.data.get(DATA_KEY, {}).get("webhooks", {}).get(did)
        
        if not webhook_id:
            _LOGGER.error("voipms_sms: No webhook found for DID: %s", did)
            persistent_notification.async_create(
                hass,
                f"No webhook found for DID: {did}",
                title="VoIP.ms SMS",
                notification_id="voipms_sms_error"
            )
            return
        
        base_url = hass.config.external_url or hass.config.internal_url or "http://your-ha-instance:8123"
        webhook_url = f"{base_url}/api/webhook/{webhook_id}"
        
        # Show persistent notification with webhook URL
        persistent_notification.async_create(
            hass,
            f"**Webhook URL for DID {did}:**\n\n`{webhook_url}`\n\nCopy this URL and configure it in your VoIP.ms portal under SMS settings.",
            title="VoIP.ms SMS - Webhook URL",
            notification_id="voipms_sms_webhook_url"
        )
        _LOGGER.info("voipms_sms: Webhook URL displayed in notification for %s", did)

    hass.services.async_register(DOMAIN, "send_sms", handle_send_sms)
    hass.services.async_register(DOMAIN, "send_mms", handle_send_mms)
    hass.services.async_register(DOMAIN, "get_webhook_url", handle_get_webhook_url)

    _LOGGER.info("voipms_sms: VoIP.ms SMS/MMS services registered successfully.")


async def async_unload_entry(hass: HomeAssistant, entry):
    """Unload VoIP.ms SMS config entry."""
    # Remove entry data
    if DATA_KEY in hass.data and "entries" in hass.data[DATA_KEY]:
        hass.data[DATA_KEY]["entries"].pop(entry.entry_id, None)
    
    # Unregister webhook for this entry's DID
    did = entry.data.get("did")
    if did and DATA_KEY in hass.data:
        webhook_id = hass.data[DATA_KEY].get("webhooks", {}).pop(did, None)
        if webhook_id:
            try:
                async_unregister(hass, webhook_id)
                _LOGGER.info("voipms_sms: Unregistered webhook for %s", did)
            except Exception as e:
                _LOGGER.warning("voipms_sms: Failed to unregister webhook: %s", e)
        
        # Clean up secret key
        hass.data[DATA_KEY].get("secret_keys", {}).pop(did, None)
    
    return True
