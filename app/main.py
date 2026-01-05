import os
import asyncio
from typing import List
from xml.sax.saxutils import escape
import logging
import re

from fastapi import FastAPI, Depends, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from dotenv import load_dotenv

# Local imports
from .database import get_db, engine, Base as BaseModel
from .models import *
from .gemini_service import parse_message, generate_reply, chat_response
from .whatsapp_service import send_whatsapp_message  # Used for Meta flow
from .twilio_service import send_whatsapp as send_whatsapp_via_twilio

load_dotenv()

logger = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Config
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_ID = os.getenv("PHONE_ID")
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")

# ---------------- CONNECTION MANAGER ----------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for ws in self.active_connections:
            try:
                await ws.send_json(message)
            except:
                pass

manager = ConnectionManager()


@app.on_event("startup")
def startup_event():
    try:
        BaseModel.metadata.create_all(bind=engine)
    except Exception as e:
        print("DB create_all failed:", e)

# ---------------- HEALTH & VERIFICATION ----------------

@app.get("/__healthcheck__")
def healthcheck():
    return {"status": "APP.MAIN.PY IS RUNNING"}

@app.get("/webhook/whatsapp")
async def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(challenge or "", status_code=200)
    raise HTTPException(status_code=403)

@app.get("/webhook/twilio")
async def verify_twilio():
    return PlainTextResponse("ok", status_code=200)

# ---------------- META (FACEBOOK) WEBHOOK ----------------

@app.post("/webhook/whatsapp")
def whatsapp_webhook(payload: dict, db: Session = Depends(get_db)):
    try:
        message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
        sender = message["from"]
        text = message["text"]["body"]

        ai_data = parse_message(text)

        # Save incoming
        db.add(Conversation(sender=sender, direction="in", message=text))
        db.commit()

        # If message looks like a casual / conversational message, use Gemini chat
        casual_greeting = re.search(r"\b(hi|hello|hey|good morning|good afternoon|good evening)\b", text or '', re.I)
        if (ai_data.get("action") == "CHECK" and ai_data.get("qty", 0) == 0 and not ai_data.get("seller") and ai_data.get("sku", "").strip() == text.strip()) or casual_greeting:
            reply = chat_response(text)
            logger.info("WhatsApp casual reply: %s -> %s", sender, reply)
            send_whatsapp_message(sender, reply)
            db.add(Conversation(sender=sender, direction="out", message=reply))
            db.commit()
            return {"status": "ok"}

        product = db.query(Product).join(Seller).filter(
            Seller.name == ai_data["seller"],
            Product.sku == ai_data["sku"]
        ).first()

        if not product:
            reply = generate_reply(ai_data.get("sku", ""), ai_data, 0, success=False, reason="Product not found.")
        else:
            if ai_data["action"] == "ADD":
                product.current_stock += ai_data["qty"]
            elif ai_data["action"] == "SHIP":
                if product.current_stock < ai_data["qty"]:
                    reply = generate_reply(product.sku, ai_data, product.current_stock, success=False, reason="Insufficient stock.")
                    send_whatsapp_message(sender, reply)
                    return {"status": "error"}
                product.current_stock -= ai_data["qty"]
                db.add(Transaction(product_id=product.id, type=TransactionType.OUTBOUND, quantity=ai_data["qty"], destination=ai_data["location"]))
            
            reply = generate_reply(product.sku, ai_data, product.current_stock, success=True)
            db.commit()
            asyncio.create_task(manager.broadcast({"sku": product.sku, "stock": product.current_stock, "seller": product.seller.name, "action": ai_data["action"]}))

        send_whatsapp_message(sender, reply)
        print("Meta reply ->", sender, reply)
        db.add(Conversation(sender=sender, direction="out", message=reply))
        db.commit()
        return {"status": "ok"}
    except Exception as e:
        print("Meta Webhook error:", e)
        return {"status": "error"}

# ---------------- TWILIO WEBHOOK ----------------

@app.post('/webhook/twilio')
async def twilio_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        form = await request.form()
        sender = form.get('From')  # whatsapp:+number
        body = form.get('Body')
        
        if not sender:
            return Response(content="<Response></Response>", media_type="application/xml")

        # Strip 'whatsapp:' for database storage
        sender_num = sender.split(':', 1)[1] if ":" in sender else sender
        ai_data = parse_message(body or '')

        # Save incoming message
        db.add(Conversation(sender=sender_num, direction="in", message=body or ''))
        db.commit()

        # If message looks like a casual / conversational message, use Gemini chat
        casual_greeting = re.search(r"\b(hi|hello|hey|good morning|good afternoon|good evening)\b", (body or ''), re.I)
        if (ai_data.get("action") == "CHECK" and ai_data.get("qty", 0) == 0 and not ai_data.get("seller") and ai_data.get("sku", "").strip() == (body or '').strip()) or casual_greeting:
            reply = chat_response(body or '')
            print("Twilio reply ->", sender_num, reply)
            db.add(Conversation(sender=sender_num, direction="out", message=reply))
            db.commit()
            xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Message>{escape(reply)}</Message>
        </Response>"""
            print("Returning TwiML:\n", xml_content)
            return Response(content=xml_content, media_type="application/xml")

        product = db.query(Product).join(Seller).filter(
            Seller.name == ai_data["seller"],
            Product.sku == ai_data["sku"]
        ).first()

        if not product:
            reply = generate_reply(ai_data.get("sku", ""), ai_data, 0, success=False, reason="Product not found.")
        else:
            if ai_data["action"] == "ADD":
                product.current_stock += ai_data["qty"]
            elif ai_data["action"] == "SHIP":
                if product.current_stock < ai_data["qty"]:
                    reply = generate_reply(product.sku, ai_data, product.current_stock, success=False, reason="Insufficient stock.")
                else:
                    product.current_stock -= ai_data["qty"]
                    db.add(Transaction(product_id=product.id, type=TransactionType.OUTBOUND, quantity=ai_data["qty"], destination=ai_data["location"]))
                    reply = generate_reply(product.sku, ai_data, product.current_stock, success=True)
            else:
                reply = generate_reply(product.sku, ai_data, product.current_stock, success=True)
            
            db.commit()
            asyncio.create_task(manager.broadcast({"sku": product.sku, "stock": product.current_stock, "seller": product.seller.name, "action": ai_data["action"]}))

        # Save outgoing record
        db.add(Conversation(sender=sender_num, direction="out", message=reply))
        db.commit()

        # If running a local test (curl/ngrok) it's useful to ask the app
        # to directly call Twilio's REST API so the sender actually receives
        # the message even when Twilio isn't the one invoking the webhook.
        if os.getenv("FORCE_TWILIO_SEND") == "1":
            try:
                send_result = send_whatsapp_via_twilio(sender_num, reply)
                print("Sent via Twilio REST ->", getattr(send_result, 'sid', send_result))
            except Exception as e:
                print("Failed send via Twilio REST:", e)

        # SUCCESS: Return TwiML XML. Twilio uses this to reply to the user.
        # This is better than calling an external function.
        xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Message>{escape(reply)}</Message>
        </Response>"""
        return Response(content=xml_content, media_type="application/xml")

    except Exception as e:
        print("Twilio webhook error:", e)
        return Response(content="<Response></Response>", media_type="application/xml")

# ---------------- OTHER ROUTES ----------------

@app.websocket("/ws/dashboard")
async def dashboard_ws(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/admin/inventory")
def get_inventory(db: Session = Depends(get_db)):
    products = db.query(Product).join(Seller).all()
    return [{"seller": p.seller.name, "sku": p.sku, "product_name": p.product_name, "stock": p.current_stock} for p in products]

@app.post('/admin/test-broadcast')
def test_broadcast(payload: dict):
    asyncio.create_task(manager.broadcast(payload))
    return {"status": "broadcasted"}