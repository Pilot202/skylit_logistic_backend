import os
import logging
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

# Configure Gemini API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = None

if GEMINI_API_KEY:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        logger.error(f"Failed to initialize Gemini Client: {e}")
else:
    logger.warning("GEMINI_API_KEY not set. Gemini calls will fail.")

# System prompt to guide the AI
SYSTEM_PROMPT = """
You are an intelligent logistics assistant for Skylit Logistics, helping manage warehouse inventory via WhatsApp.

**Your Capabilities:**
1. CHECK STOCK: Answer questions about current inventory levels
2. ADD STOCK: Help add new inventory (inbound shipments)
3. SHIP STOCK: Process outbound shipments and reduce inventory
4. GENERAL QUERIES: Answer questions about the system or provide help

**Instructions:**
- You have access to real-time inventory data provided in the context below
- Be conversational, friendly, and professional
- Use emojis appropriately (📦 for inventory, ✅ for success, ❌ for errors, 🚚 for shipping)
- When users ask about stock, provide clear information with product names, SKUs, quantities, and sellers
- When users want to add stock, confirm the action with details
- When users want to ship items, verify availability first
- If a product is not found, suggest similar products if available or ask for clarification
- Keep responses concise and WhatsApp-friendly (avoid long paragraphs)
- If the query is unclear, ask clarifying questions

**Response Format:**
- For stock checks: List products with quantities and sellers
- For additions: Confirm what was added and new total
- For shipments: Confirm what was shipped, destination, and remaining stock
- For errors: Explain the issue clearly and suggest next steps
"""

async def parse_message(text: str, inventory_summary: str = None) -> str:
    """
    Parse user message and return a structured intelligent response.
    Uses real-time inventory data from the database.
    Async to prevent blocking the event loop.
    """
    try:
        if not client:
            return fallback_response(text)

        # Use inventory summary from database
        if not inventory_summary:
            inventory_summary = "No inventory data available."

        # Combine prompt and user text
        full_prompt = f"{SYSTEM_PROMPT}\n\n{inventory_summary}\n\nUser Message: {text}"

        # Use async generate_content
        response = await client.aio.models.generate_content(
            model="gemini-1.5-flash-latest",
            contents=full_prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,
                max_output_tokens=300
            )
        )
        
        return response.text.strip()
        
    except Exception as e:
        logger.error(f"Gemini parse failed, using fallback: {e}")
        return fallback_response(text)

async def classify_intent(text: str, inventory_summary: str = None) -> dict:
    """
    Classify user intent and extract parameters
    Returns dict with intent type and extracted parameters
    """
    try:
        if not client:
            return {"intent": "UNKNOWN", "params": {}}

        classification_prompt = f"""
Analyze this user message and classify the intent. Return ONLY a JSON object with this structure:
{{
    "intent": "CHECK_STOCK" | "ADD_STOCK" | "SHIP_STOCK" | "GENERAL",
    "sku": "product SKU if mentioned",
    "quantity": number if mentioned,
    "seller": "seller name if mentioned",
    "destination": "destination if mentioned for shipping"
}}

Current Inventory:
{inventory_summary or "No inventory data"}

User Message: {text}
"""

        response = await client.aio.models.generate_content(
            model="gemini-1.5-flash-latest",
            contents=classification_prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=150
            )
        )
        
        # Try to parse JSON response
        import json
        result_text = response.text.strip()
        # Remove markdown code blocks if present
        if result_text.startswith("```"):
            result_text = result_text.split("```")[1]
            if result_text.startswith("json"):
                result_text = result_text[4:]
        
        return json.loads(result_text.strip())
        
    except Exception as e:
        logger.error(f"Intent classification failed: {e}")
        return {"intent": "UNKNOWN", "params": {}}


async def chat_response(prompt: str) -> str:
    """
    General chat response using Gemini.
    """
    try:
        if not client:
            return fallback_response(prompt)
            
        full_prompt = f"{SYSTEM_PROMPT}\nUser Message: {prompt}"

        response = await client.aio.models.generate_content(
            model="gemini-1.5-flash-latest",
            contents=full_prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,
                max_output_tokens=250
            )
        )
        return response.text.strip()
        
    except Exception as e:
        logger.error(f"Gemini chat failed, returning fallback: {e}")
        return fallback_response(prompt)

def fallback_response(user_message: str) -> str:
    """
    Fallback response if Gemini fails or quota exceeded.
    """
    lower_msg = user_message.lower()
    if any(k in lower_msg for k in ["stock", "product", "inventory", "available"]):
        return "⚠ I couldn’t identify the product SKU or your query is unclear. Please provide product name and quantity."
    else:
        return "I’m here to assist you. Can you provide more details?"