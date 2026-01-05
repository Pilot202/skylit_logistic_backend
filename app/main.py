from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from xml.sax.saxutils import escape
from sqlalchemy.orm import Session
from .database import get_db
from .models import *
from .gemini_service import parse_message, generate_reply
from .whatsapp_service import send_whatsapp_message
import requests
from fastapi import WebSocket, WebSocketDisconnect
from typing import List
import asyncio
import os
from dotenv import load_dotenv


load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # change later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_ID = os.getenv("PHONE_ID")
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")

print("WHATSAPP VERIFY TOKEN:", VERIFY_TOKEN)

@app.get("/__healthcheck__")
def healthcheck():
    return {"status": "APP.MAIN.PY IS RUNNING"}

# ---------------- WEBHOOK VERIFICATION ----------------

@app.post('/webhook/twilio')
async def twilio_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        form = await request.form()
        sender = form.get('From')  # Example: "whatsapp:+2348012345678"
        body = form.get('Body')
        
        if not sender:
            return PlainTextResponse('missing sender', status_code=400)

        # Get the clean number for your Database
        sender_num = sender.split(':', 1)[1] if ":" in sender else sender

        # Process message with AI
        ai_data = parse_message(body or '')

        # ... (Your Database Logic for Product/Stock remains here) ...

        # Final Reply Text
        reply = "Your generated reply here..." 

        # 1. Save to Database
        try:
            db.add(Conversation(sender=sender_num, direction="out", message=reply))
            db.commit()
        except Exception:
            db.rollback()

        # 2. THE FIX: Return TwiML XML. 
        # Twilio reads this and sends the WhatsApp message for you.
        xml_reply = f"""<?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Message>{escape(reply)}</Message>
        </Response>"""
        
        return Response(content=xml_reply, media_type="application/xml")

    except Exception as e:
        print("Twilio webhook error:", e)
        # Even on error, return a valid (empty) TwiML so Twilio doesn't show an error
        return Response(content="<Response></Response>", media_type="application/xml")


@app.get("/webhook/twilio")
async def verify_twilio(request: Request):
    """Simple GET endpoint for Twilio webhook sanity checks (returns 200 OK)."""
    return PlainTextResponse("ok", status_code=200)
# ---------------- WEBHOOK MESSAGE ----------------
@app.post("/webhook/whatsapp")
def whatsapp_webhook(payload: dict, db: Session = Depends(get_db)):
    print("Incoming WhatsApp payload")

    try:
        message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
        sender = message["from"]
        text = message["text"]["body"]

        ai_data = parse_message(text)

        # Save incoming message
        try:
            db.add(Conversation(sender=sender, direction="in", message=text))
            db.commit()
        except Exception:
            db.rollback()

        product = db.query(Product).join(Seller).filter(
            Seller.name == ai_data["seller"],
            Product.sku == ai_data["sku"]
        ).first()

        if not product:
            reply = generate_reply(ai_data.get("sku", ""), ai_data, 0, success=False, reason="Product not found.")
            send_whatsapp_message(sender, reply)
            try:
                db.add(Conversation(sender=sender, direction="out", message=reply))
                db.commit()
            except Exception:
                db.rollback()
            return {"status": "error"}

        if ai_data["action"] == "ADD":
            product.current_stock += ai_data["qty"]
            reply = generate_reply(product.sku, ai_data, product.current_stock, success=True)

        elif ai_data["action"] == "SHIP":
            if product.current_stock < ai_data["qty"]:
                reply = generate_reply(product.sku, ai_data, product.current_stock, success=False, reason="Insufficient stock.")
                send_whatsapp_message(sender, reply)
                try:
                    db.add(Conversation(sender=sender, direction="out", message=reply))
                    db.commit()
                except Exception:
                    db.rollback()
                return {"status": "error"}

            product.current_stock -= ai_data["qty"]
            db.add(Transaction(
                product_id=product.id,
                type=TransactionType.OUTBOUND,
                quantity=ai_data["qty"],
                destination=ai_data["location"]
            ))
            reply = generate_reply(product.sku, ai_data, product.current_stock, success=True)

        else:
            # CHECK or unknown: respond with current stock
            reply = generate_reply(product.sku, ai_data, product.current_stock, success=True)

        db.commit()
        asyncio.create_task(manager.broadcast({
        "sku": product.sku,
        "stock": product.current_stock,
        "seller": product.seller.name,
        "action": ai_data["action"]
    }))

        # Send reply and record it
        send_whatsapp_message(sender, reply)
        try:
            db.add(Conversation(sender=sender, direction="out", message=reply))
            db.commit()
        except Exception:
            db.rollback()

        return {"status": "ok"}

    except Exception as e:
        print("Webhook error:", e)
        return {"status": "error"}


@app.post('/webhook/twilio')
async def twilio_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle incoming Twilio WhatsApp webhook (form-encoded).
    Twilio sends fields like `From` and `Body` in form data.
    """
    try:
        form = await request.form()
        sender = form.get('From')
        body = form.get('Body')
        if not sender:
            return PlainTextResponse('missing sender', status_code=400)
        # Twilio uses prefix 'whatsapp:' in From
        if sender.startswith('whatsapp:'):
            sender_num = sender.split(':', 1)[1]
        else:
            sender_num = sender

        ai_data = parse_message(body or '')

        # Save incoming message
        try:
            db.add(Conversation(sender=sender_num, direction="in", message=body or ''))
            db.commit()
        except Exception:
            db.rollback()

        # Find product and act similar to Meta webhook flow
        product = db.query(Product).join(Seller).filter(
            Seller.name == ai_data["seller"],
            Product.sku == ai_data["sku"]
        ).first()

        if not product:
            reply = generate_reply(ai_data.get("sku", ""), ai_data, 0, success=False, reason="Product not found.")
            # send via Twilio (best-effort) and also return TwiML so Twilio will reply immediately
            try:
                from .twilio_service import send_whatsapp
                send_whatsapp(sender_num, reply)
            except Exception:
                pass
            try:
                db.add(Conversation(sender=sender_num, direction="out", message=reply))
                db.commit()
            except Exception:
                db.rollback()
            xml = "<?xml version='1.0' encoding='UTF-8'?><Response><Message>" + escape(reply) + "</Message></Response>"
            return Response(content=xml, media_type="application/xml")

        if ai_data["action"] == "ADD":
            product.current_stock += ai_data["qty"]
            reply = f"✅ ADD completed. New stock for {product.sku}: {product.current_stock}"

        elif ai_data["action"] == "SHIP":
            if product.current_stock < ai_data["qty"]:
                reply = generate_reply(product.sku, ai_data, product.current_stock, success=False, reason="Insufficient stock.")
                try:
                    from .twilio_service import send_whatsapp
                    send_whatsapp(sender_num, reply)
                except Exception:
                    pass
                try:
                    db.add(Conversation(sender=sender_num, direction="out", message=reply))
                    db.commit()
                except Exception:
                    db.rollback()
                xml = "<?xml version='1.0' encoding='UTF-8'?><Response><Message>" + escape(reply) + "</Message></Response>"
                return Response(content=xml, media_type="application/xml")

            product.current_stock -= ai_data["qty"]
            db.add(Transaction(
                product_id=product.id,
                type=TransactionType.OUTBOUND,
                quantity=ai_data["qty"],
                destination=ai_data["location"]
            ))
            reply = generate_reply(product.sku, ai_data, product.current_stock, success=True)

        else:
            reply = generate_reply(product.sku, ai_data, product.current_stock, success=True)

        db.commit()
        asyncio.create_task(manager.broadcast({
            "sku": product.sku,
            "stock": product.current_stock,
            "seller": product.seller.name,
            "action": ai_data["action"]
        }))

        # Send reply and record it (best-effort). Also return TwiML response so Twilio replies immediately.
        try:
            from .twilio_service import send_whatsapp
            send_whatsapp(sender_num, reply)
        except Exception:
            pass
        try:
            db.add(Conversation(sender=sender_num, direction="out", message=reply))
            db.commit()
        except Exception:
            db.rollback()

        xml = "<?xml version='1.0' encoding='UTF-8'?><Response><Message>" + escape(reply) + "</Message></Response>"
        return Response(content=xml, media_type="application/xml")

    except Exception as e:
        print("Twilio webhook error:", e)
        return {"status": "error"}

def send_whatsapp(to: str, message: str):
    url = f"https://graph.facebook.com/v19.0/{PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }
    requests.post(url, headers=headers, json=payload)

@app.get("/db-test")
def db_test(db: Session = Depends(get_db)):
    return {"status": "connected"}




from fastapi import WebSocket, WebSocketDisconnect
from typing import List
import asyncio

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
            await ws.send_json(message)

manager = ConnectionManager()


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
    return [
        {
            "seller": p.seller.name,
            "sku": p.sku,
            "product_name": p.product_name,
            "stock": p.current_stock
        }
        for p in products
    ]


@app.post('/admin/test-broadcast')
def test_broadcast(payload: dict):
    """Trigger a test broadcast to connected dashboard websockets.
    payload example: {"sku":"WID-A","stock":12,"seller":"Acme","action":"ADD"}
    """
    asyncio.create_task(manager.broadcast(payload))
    return {"status": "broadcasted", "payload": payload}





