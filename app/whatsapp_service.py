import os
import requests

TOKEN = os.getenv("WHATSAPP_TOKEN")
# Support either `PHONE_NUMBER_ID` or legacy `PHONE_ID` env var
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID") or os.getenv("PHONE_ID") or os.getenv("PHONE_NUMBER_ID")

def send_whatsapp_message(recipient_number: str, message: str) -> bool:
    if not TOKEN or not PHONE_NUMBER_ID:
        return False
    url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_number,
        "type": "text",
        "text": {"body": message}
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        return resp.status_code in (200, 201)
    except Exception:
        return False
