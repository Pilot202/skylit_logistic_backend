# app/main.py

import os
import logging
import asyncio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from .twilio_service import send_whatsapp
from .gemini_service import parse_message, classify_intent
from .database import SessionLocal
from .models import Conversation
from . import inventory_service
from . import intent_parser

# -------------------------------------------------
# Setup
# -------------------------------------------------

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app.main")

app = FastAPI(title="Skylit WhatsApp Bot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------
# Helpers
# -------------------------------------------------

def log_conversation(
    db: Session | None,
    sender: str,
    direction: str,
    message: str,
):
    """Safely log messages (never crash bot)."""
    if not db:
        return

    try:
        db.add(
            Conversation(
                sender=sender,
                direction=direction,
                message=message,
            )
        )
        db.commit()
    except Exception as e:
        logger.error(f"DB log failed: {e}")
        db.rollback()


async def handle_message(sender: str, text: str):
    """
    Optimized pipeline with pattern matching fallback:
    1. Try pattern matching first (no API calls)
    2. Execute stock operations if intent is clear
    3. Only call Gemini for complex/unclear queries
    This reduces API calls by ~80%
    """

    db = None
    try:
        db = SessionLocal()
    except Exception as e:
        logger.warning(f"DB unavailable: {e}")

    logger.info(f"Incoming message from {sender}: {text}")
    log_conversation(db, sender, "in", text)

    # ---- Get real-time inventory ----
    inventory_summary = "No inventory data available."
    if db:
        try:
            inventory_summary = inventory_service.get_inventory_summary(db)
        except Exception as e:
            logger.error(f"Failed to get inventory: {e}")

    # ---- Step 1: Try pattern matching first (NO API CALL) ----
    intent_data = intent_parser.parse_intent_from_text(text)
    intent = intent_data.get("intent", "UNKNOWN")
    confidence = intent_data.get("confidence", "low")
    
    logger.info(f"Pattern matching result: {intent} (confidence: {confidence})")

    # ---- Step 2: Execute stock operations if intent is clear ----
    operation_result = None
    reply = ""

    if db and intent in ["ADD_STOCK", "SHIP_STOCK", "CHECK_STOCK"] and confidence == "high":
        try:
            if intent == "ADD_STOCK":
                sku = intent_data.get("sku")
                quantity = intent_data.get("quantity")
                seller = intent_data.get("seller")
                
                if sku and quantity and quantity > 0:
                    operation_result = inventory_service.add_stock(
                        db, sku=sku, quantity=quantity, seller_name=seller
                    )
                    logger.info(f"✅ Added stock via pattern matching: {operation_result}")
                    reply = operation_result.get("message", "")
                else:
                    reply = "⚠️ Please specify both product and quantity. Example: 'Add 10 phone chargers from Acme'"
            
            elif intent == "SHIP_STOCK":
                sku = intent_data.get("sku")
                quantity = intent_data.get("quantity")
                destination = intent_data.get("destination", "warehouse")
                
                if sku and quantity and quantity > 0:
                    operation_result = inventory_service.remove_stock(
                        db, sku=sku, quantity=quantity, destination=destination
                    )
                    logger.info(f"✅ Shipped stock via pattern matching: {operation_result}")
                    reply = operation_result.get("message", "")
                else:
                    reply = "⚠️ Please specify both product and quantity. Example: 'Ship 5 USB cables to warehouse B'"
            
            elif intent == "CHECK_STOCK":
                sku = intent_data.get("sku")
                operation_result = inventory_service.check_stock(db, sku=sku)
                logger.info(f"✅ Checked stock via pattern matching: {operation_result}")
                reply = operation_result.get("message", "")
        
        except Exception as e:
            logger.error(f"Stock operation failed: {e}")
            reply = f"❌ Operation failed: {str(e)}"

    # ---- Step 3: Handle GENERAL queries with simple responses (NO API CALL) ----
    elif intent == "GENERAL" and confidence == "high":
        simple_reply = intent_parser.get_general_response(text)
        if simple_reply:
            reply = simple_reply
            logger.info("✅ Responded with simple general response (no API call)")
        else:
            # Complex general query - use Gemini
            try:
                logger.info("🤖 Using Gemini for complex general query")
                reply = await parse_message(text, inventory_summary)
            except Exception as e:
                logger.error(f"Gemini failure: {e}")
                reply = "I'm here to help! You can ask me to check stock, add inventory, or ship items. What would you like to do?"

    # ---- Step 4: Unknown/complex queries - use Gemini (ONLY WHEN NECESSARY) ----
    else:
        try:
            logger.info("🤖 Pattern matching unclear, using Gemini for classification")
            # Only now do we call Gemini
            gemini_intent = await classify_intent(text, inventory_summary)
            intent = gemini_intent.get("intent", "GENERAL")
            params = gemini_intent.get("params", {}) if isinstance(gemini_intent, dict) else {}
            
            # Execute operation based on Gemini's classification
            if db and intent in ["ADD_STOCK", "SHIP_STOCK", "CHECK_STOCK"]:
                if intent == "ADD_STOCK":
                    sku = params.get("sku") or params.get("product_name", "")
                    quantity = params.get("quantity", 0)
                    seller = params.get("seller")
                    
                    if sku and quantity > 0:
                        operation_result = inventory_service.add_stock(
                            db, sku=sku, quantity=quantity, seller_name=seller
                        )
                        reply = operation_result.get("message", "")
                
                elif intent == "SHIP_STOCK":
                    sku = params.get("sku") or params.get("product_name", "")
                    quantity = params.get("quantity", 0)
                    destination = params.get("destination", "warehouse")
                    
                    if sku and quantity > 0:
                        operation_result = inventory_service.remove_stock(
                            db, sku=sku, quantity=quantity, destination=destination
                        )
                        reply = operation_result.get("message", "")
                
                elif intent == "CHECK_STOCK":
                    sku = params.get("sku")
                    operation_result = inventory_service.check_stock(db, sku=sku)
                    reply = operation_result.get("message", "")
            
            # If no operation or need response, use Gemini
            if not reply:
                reply = await parse_message(text, inventory_summary)
        
        except Exception as e:
            logger.error(f"Gemini failure: {e}")
            reply = "⚠️ I'm having trouble understanding. Please try:\n• 'Check stock'\n• 'Add 10 phone chargers'\n• 'Ship 5 USB cables to warehouse A'"

    # ---- Send WhatsApp ----
    try:
        send_whatsapp(sender, reply)
        logger.info(f"Sent reply to {sender}: {reply}")
    except Exception as e:
        logger.error(f"Twilio send failed: {e}")

    log_conversation(db, sender, "out", reply)

    if db:
        db.close()


# -------------------------------------------------
# Routes
# -------------------------------------------------

@app.post("/webhook/twilio")
async def twilio_webhook(request: Request):
    """
    Twilio WhatsApp webhook
    """
    form = await request.form()
    sender = form.get("From")
    body = form.get("Body")

    if not sender or not body:
        return "Ignored", 200

    # Run async so Twilio gets immediate ACK
    asyncio.create_task(handle_message(sender, body))

    return "OK", 200


@app.get("/")
def health():
    return {"status": "Skylit WhatsApp Bot running"}
