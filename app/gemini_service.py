import os
import warnings
import json
import re
import logging

logger = logging.getLogger(__name__)

# Suppress known FutureWarning from deprecated google.generativeai package when present
warnings.filterwarnings(
    "ignore",
    category=FutureWarning,
    message="All support for the `google.generativeai` package has ended.*",
)

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
        # Try newer package first if available; fall back to deprecated package.
        genai = None
        try:
            import google.genai as genai_new
            genai = genai_new
        except Exception:
            try:
                import google.generativeai as genai_old
                genai = genai_old
            except Exception:
                genai = None

        if genai is None:
            raise RuntimeError("No Gemini client installed")

        # Configure API key (both libs use a configure pattern for our usage)
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
            except Exception:
                # Some versions may not have configure; ignore
                pass

        # Use whichever API surface is available; try model.generate_content first
        if hasattr(genai, "GenerativeModel"):
            model = genai.GenerativeModel("gemini-2.5-flash")
            response = model.generate_content([SYSTEM_PROMPT, f"Message: {text}"])
            response_text = getattr(response, "text", None) or str(response)
        else:
            # Fallback: attempt a generic generate_content call
            response = genai.generate_content([SYSTEM_PROMPT, f"Message: {text}"])
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
    except Exception as e:
        logger.exception("Gemini parse failed, using fallback parser: %s", e)
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


def chat_response(text: str) -> str:
    """Generate a short conversational reply for general messages using Gemini.
    Falls back to a simple friendly message when the model is unavailable.
    """
    try:
        genai = None
        try:
            import google.genai as genai_new
            genai = genai_new
        except Exception:
            try:
                import google.generativeai as genai_old
                genai = genai_old
            except Exception:
                genai = None

        if genai is None:
            raise RuntimeError("No Gemini client installed")

        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
            except Exception:
                pass

        prompt = f"You are a helpful assistant. Reply concisely and politely to: {text}"

        if hasattr(genai, "GenerativeModel"):
            model = genai.GenerativeModel("gemini-2.5-flash")
            response = model.generate_content([prompt])
            reply_text = getattr(response, "text", None) or str(response)
        else:
            response = genai.generate_content([prompt])
            reply_text = getattr(response, "text", None) or str(response)

        for line in reply_text.splitlines():
            if line.strip():
                return line.strip()
        return reply_text.strip()
    except Exception:
        logger.exception("Gemini chat failed, returning fallback reply")
        return "Hello! How can I help you today?"
