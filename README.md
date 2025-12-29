# voipms_sms
Home Assistant custom integration for sending and receiving SMS (text) and MMS (photo snapshot) messages via [Voip.ms](https://voip.ms/) REST Api 

## Prerequisites
- Voip.ms account with a DID that has SMS turned on
- API configuration set in the Voip.ms portal
  - API password set
  - API enabled
  - External IP address of your HA site, or DNS domain (sender whitelist)
  - Bearer token (optional, not needed for sending)
- Home Assistant running
- For incoming SMS: Home Assistant must be accessible from the internet (for webhook callbacks)

## How to install the integration

### Manually

Create a folder structure on your HA server and deploy the three files.
Make sure that the folder name matches the service domain - voipms_sms:

```
/config/custom_components/voipms_sms/
  ├── __init__.py
  ├── manifest.json
  ├── services.yaml
```  

### Using HACS

When you are looking at the HACS page for the Voip.ms integration in Home Assistant, it displays a "Download" button at the botton.
Click on it, then proceed with the configuration steps.

### Configuration

#### GUI Setup (Recommended)

1. Go to **Settings** > **Devices & Services**
2. Click **Add Integration**
3. Search for **VoIP.ms SMS** and select it
4. Enter your configuration:
   - **Account User**: Your Voip.ms login email
   - **API Password**: Your Voip.ms API password
   - **DID**: Your 10-digit phone number (without punctuation, e.g., `1234567890`)
5. Click **Submit** to complete the setup

The integration will be configured automatically - no YAML editing required!

#### YAML Setup (Legacy)

Alternatively, you can configure via YAML by updating `configuration.yml`:

```yaml
voipms_sms:
  account_user: !secret voipms_user
  api_password: !secret voipms_password
  did: "1234567890"
```

Use your Voip.ms login email and the 10 digit DID phone number for the `did` value, without punctuation. This DID is used for both sending and receiving SMS.

Add the user and password secrets to your `secrets.yml`:

```
voipms_password: "your_voipms_api_password"
voipms_user: "your_voipms_account_user"
```

Validate your configuration:

```
ha core check
```

Restart HA:

```
ha core restart
```

## Verify

Verify that that are no errors in the log from registering the service. 
Make sure that `VoIP.ms SMS` shows up in the list of loaded integrations:

![alt text](custom-integration.png)


## Using the integration

To send a test message, navigate to `Developer Tools > Actions`, select VoIP.ms SMS: Send SMS (or Send MMS) in HA and enter your mobile phone number in the recipient field:

![alt text](developer-tools.png)

When testing MMS, make sure you enter the full local path to an existing image, e.g.
```
 image_path: /config/www/porch_snapshot.jpg
```

If you do not receive a text message, consult your logs for errors.

I use the services in flows, e.g. with Node Red as an Action node:

![alt text](node-red.png)

## Receiving Incoming SMS

This integration creates a sensor entity and webhook for your configured DID. When an SMS is received, the sensor is updated with the message details.

### Setup Incoming SMS

1. Configure your `did` in the configuration (see above)
2. Restart Home Assistant
3. Get your webhook URL by calling the `voipms_sms.get_webhook_url` service (check Developer Tools > Events for `voipms_sms_webhook_url` event)
4. Configure the webhook URL in your VoIP.ms portal under SMS settings

### Sensor Entity

A sensor entity is created for your DID: `sensor.voip_ms_sms_YOURNUMBER`

**Attributes:**
- `from`: The phone number that sent the message
- `message`: The text content of the message  
- `last_updated`: When the last message was received
- `message_id`: Unique ID of the message
- `phone_number`: The phone number this sensor tracks
- `webhook_url`: The webhook URL for this phone number (for configuring in VoIP.ms)

### Webhook Security

Your DID gets a unique, cryptographically secure webhook URL. The URL contains a hash derived from your DID and a randomly generated secret, making it impossible to guess.

### Error Handling

If an incoming webhook has an unknown event type or malformed data, a persistent notification will be shown in Home Assistant.

## FAQ

Q: Can I send to multiple phone numbers at a time, i.e. is there support for group messages?

A: No, the Voip.ms API only accepts a single recipient.


## Planned enhancements (with no target date):

- Support for multiple DIDs with service selection
