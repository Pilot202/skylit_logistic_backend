import os
from twilio.rest import Client

_account = os.getenv('TWILIO_ACCOUNT_SID')
_token = os.getenv('TWILIO_AUTH_TOKEN')
_from = os.getenv('TWILIO_WHATSAPP_FROM')  # example: "whatsapp:+1415XXXXXXX"

_client = None
if _account and _token:
    _client = Client(_account, _token)


def send_whatsapp(to: str, message: str):
    """Send a WhatsApp message via Twilio. `to` should be in E.164 form without the "whatsapp:" prefix."""
    if not _client:
        raise RuntimeError("Twilio client not configured. Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN.")
    if not _from:
        raise RuntimeError("TWILIO_WHATSAPP_FROM not set in env (e.g. 'whatsapp:+1415xxxxxxx').")
    to_full = f"whatsapp:{to}" if not str(to).startswith('whatsapp:') else to
    return _client.messages.create(body=message, from_=_from, to=to_full)
