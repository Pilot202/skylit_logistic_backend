import os
import json
import re
import logging

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are an inventory control AI.
Convert messages into JSON only.
Schema:
{
  "action": "ADD | SHIP | CHECK",
  "seller": "string",
  "sku": "string",
  "qty": number,
  "location": "string"
}
"""

def _fallback_parse(text: str) -> dict:
  # Very small heuristic parser for development / offline use
  qty_match = re.search(r"(\d+)", text)
  sku_match = re.search(r"SKU[:#]?\s*([A-Za-z0-9-]+)", text, re.IGNORECASE)
  action = "CHECK"
  if re.search(r"\b(add|received|restock)\b", text, re.IGNORECASE):
    action = "ADD"
  elif re.search(r"\b(ship|shipped|send|dispatched)\b", text, re.IGNORECASE):
    action = "SHIP"

  return {
    "action": action,
    "seller": "",
    "sku": (sku_match.group(1) if sku_match else text.strip()),
    "qty": int(qty_match.group(1)) if qty_match else 0,
    "location": ""
  }

def parse_message(text: str) -> dict:
  # Lazy import of the Gemini client to avoid import-time failures
  try:
    import google.generativeai as genai
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel("gemini-1.5-flash")
    response = model.generate_content([SYSTEM_PROMPT, f"Message: {text}"])
    response_text = getattr(response, "text", None) or str(response)
    # Try direct JSON parse first, then attempt to extract first JSON object
    try:
      return json.loads(response_text)
    except Exception:
      try:
        m = re.search(r"(\{.*\})", response_text, re.DOTALL)
        if m:
          return json.loads(m.group(1))
      except Exception as e:
        logger.exception("Failed to extract JSON from Gemini response: %s", e)
    # Fall back to heuristic parser
    return _fallback_parse(text)
  except Exception:
    logger.exception("Gemini parse failed, using fallback parser")
    return _fallback_parse(text)
