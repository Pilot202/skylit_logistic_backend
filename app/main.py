import re
import logging
from fastapi import (
    FastAPI,
    Request,
    Response,
    Depends,
    BackgroundTasks
)
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from dotenv import load_dotenv

# Local imports
from .database import get_db, engine, Base as BaseModel, SessionLocal
from .models import Product, Seller, Transaction, TransactionType, Conversation
from .gemini_service import parse_message, generate_reply, chat_response
from .twilio_service import send_whatsapp

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# -------------------- CORS --------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------- STARTUP --------------------
@app.on_event("startup")
def startup_event():
    BaseModel.metadata.create_all(bind=engine)
    logger.info("Twilio WhatsApp service started")

# -------------------- HEALTH --------------------
@app.get("/__healthcheck__")
def healthcheck():
    return {"status": "ok", "service": "twilio-whatsapp"}

# -------------------- TWILIO WEBHOOK --------------------
@app.post("/webhook/twilio")
async def twilio_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    form = await request.form()
    sender = form.get("From")       # whatsapp:+234...
    body = (form.get("Body") or "").strip()

    if not sender:
        return Response("<Response/>", media_type="application/xml")

    sender_num = sender.replace("whatsapp:", "")

    # Save inbound message
    db.add(Conversation(sender=sender_num, direction="in", message=body))
    db.commit()

    # Process async (Gemini-safe)
    background_tasks.add_task(
        process_twilio_message,
        sender_num,
        body
    )

    # Immediate ACK to Twilio
    return Response("<Response/>", media_type="application/xml")

# -------------------- BACKGROUND LOGIC --------------------
def process_twilio_message(sender: str, text: str):
    db = SessionLocal()
    try:
        logger.info("Processing message from %s: %s", sender, text)

        # 1️⃣ Casual / conversational messages
        if re.search(r"\b(hi|hello|hey|good morning|good afternoon|good evening)\b", text, re.I):
            reply = chat_response(text)
            send_and_log(db, sender, reply)
            return

        # 2️⃣ Inventory parsing via Gemini
        ai_data = parse_message(text)

        # Guard against empty SKU
        if not ai_data.get("sku"):
            reply = "⚠️ I couldn’t identify the product SKU. Please try again."
            send_and_log(db, sender, reply)
            return

        # Inventory lookup
        product = None
        if ai_data.get("seller"):
            product = (
                db.query(Product)
                .join(Seller)
                .filter(
                    Seller.name == ai_data["seller"],
                    Product.sku == ai_data["sku"]
                )
                .first()
            )
        else:
            # SKU-only fallback
            product = (
                db.query(Product)
                .filter(Product.sku == ai_data["sku"])
                .first()
            )

        if not product:
            reply = generate_reply(
                ai_data["sku"],
                ai_data,
                0,
                success=False,
                reason="Product not found"
            )
            send_and_log(db, sender, reply)
            return

        # 3️⃣ Apply inventory action
        if ai_data["action"] == "ADD":
            product.current_stock += ai_data["qty"]

        elif ai_data["action"] == "SHIP":
            if product.current_stock < ai_data["qty"]:
                reply = generate_reply(
                    product.sku,
                    ai_data,
                    product.current_stock,
                    success=False,
                    reason="Insufficient stock"
                )
                send_and_log(db, sender, reply)
                return

            product.current_stock -= ai_data["qty"]
            db.add(Transaction(
                product_id=product.id,
                type=TransactionType.OUTBOUND,
                quantity=ai_data["qty"],
                destination=ai_data.get("location")
            ))

        # 4️⃣ Reply
        reply = generate_reply(
            product.sku,
            ai_data,
            product.current_stock,
            success=True
        )

        db.commit()
        send_and_log(db, sender, reply)

    except Exception as e:
        logger.exception("Twilio processing error: %s", e)
        send_and_log(db, sender, "⚠️ An internal error occurred. Please try again.")
    finally:
        db.close()

# -------------------- SEND + LOG --------------------
def send_and_log(db: Session, to_number: str, message: str):
    msg = send_whatsapp(to_number, message)
    logger.info("Sent WhatsApp message SID=%s", msg.sid)

    db.add(Conversation(
        sender=to_number,
        direction="out",
        message=message
    ))
    db.commit()
