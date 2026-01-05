import os
import json
import re
import logging

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are an inventory control AI.
Convert messages into JSON only.
Schema and respond in a professional tone:
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
        model = genai.GenerativeModel("gemini-2.5-flash")
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


def generate_reply(product_sku: str, ai_data: dict, current_stock: int, success: bool = True, reason: str = None) -> str:
    """Use Gemini to generate a user-facing reply message. Falls back to simple templates.

    product_sku: SKU string
    ai_data: parsed dict from `parse_message`
    current_stock: resulting current stock
    success: whether the operation succeeded
    reason: optional failure reason text
    """
    try:
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        model = genai.GenerativeModel("gemini-2.5-flash")
        prompt = (
            f"You are an inventory assistant. The user performed: {ai_data}. "
            f"The SKU is {product_sku}. The current stock is {current_stock}. "
            f"The operation {'succeeded' if success else 'failed'}"
        )
        if reason:
            prompt += f" because: {reason}"
        prompt += ". Reply in a single concise WhatsApp-friendly sentence."
        response = model.generate_content([prompt])
        reply_text = getattr(response, "text", None) or str(response)
        # return the first non-empty line
        for line in reply_text.splitlines():
            if line.strip():
                return line.strip()
        return reply_text.strip()
    except Exception:
        logger.exception("Gemini generate_reply failed, using fallback message")
        # Fallback templates
        if not success:
            return reason or "⚠️ Operation failed."
        action = ai_data.get("action")
        if action == "ADD":
            return f"✅ ADD completed. New stock for {product_sku}: {current_stock}"
        if action == "SHIP":
            return f"✅ SHIP completed. New stock for {product_sku}: {current_stock}"
        return f"ℹ️ Current stock for {product_sku}: {current_stock}"
