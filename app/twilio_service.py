import os
from twilio.rest import Client
import json
from dotenv import load_dotenv

load_dotenv()


_account = os.getenv('TWILIO_ACCOUNT_SID')
_token = os.getenv('TWILIO_AUTH_TOKEN')
_from = os.getenv('TWILIO_WHATSAPP_FROM')  

_client = None
if _account and _token:
    _client = Client(_account, _token)


def send_whatsapp(to: str, message: str = None, content_sid: str = None, content_variables: dict | None = None):
    """Send a WhatsApp message via Twilio.

    - If `content_sid` is provided, send using Twilio Content API parameters
      (`content_sid` and optional `content_variables`) which is useful for
      template/message-content usage.
    - Otherwise falls back to sending a plain `body` message.

    `to` may be either in full form (`whatsapp:+123...`) or just the number.
    Returns the Twilio message resource.
    """
    if not _client:
        raise RuntimeError("Twilio client not configured. Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN.")
    if not _from:
        raise RuntimeError("TWILIO_WHATSAPP_FROM not set in env (e.g. 'whatsapp:+1415xxxxxxx').")

    to_full = f"whatsapp:{to}" if not str(to).startswith('whatsapp:') else to

    # If a content SID is provided, prefer that signature (supports content_variables)
    if content_sid:
        kwargs = {
            'from_': _from,
            'to': to_full,
            'content_sid': content_sid,
        }
        if content_variables:
            # Twilio expects a JSON string for content_variables
            kwargs['content_variables'] = json.dumps(content_variables)
        return _client.messages.create(**kwargs)

    # Fallback to simple body messaging
    return _client.messages.create(body=message, from_=_from, to=to_full)
