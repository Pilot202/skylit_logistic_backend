from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from .database import get_db
from .models import *
from .gemini_service import parse_message
from .whatsapp_service import send_whatsapp_message
import requests
from fastapi import WebSocket, WebSocketDisconnect
from typing import List
import asyncio
import os
from dotenv import load_dotenv
from pyngrok import ngrok

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

@app.get("/webhook/whatsapp")
async def verify_webhook(request: Request):
    params = request.query_params

    # Support BOTH Meta & Swagger formats
    mode = params.get("hub.mode") or params.get("hub_mode")
    token = params.get("hub.verify_token") or params.get("hub_verify_token")
    challenge = params.get("hub.challenge") or params.get("hub_challenge")

    print("MODE:", mode)
    print("EXPECTED TOKEN:", VERIFY_TOKEN)
    print("RECEIVED TOKEN:", token)

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(challenge or "", status_code=200)

    raise HTTPException(status_code=403)
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
            reply = "❌ Product not found."
            send_whatsapp_message(sender, reply)
            try:
                db.add(Conversation(sender=sender, direction="out", message=reply))
                db.commit()
            except Exception:
                db.rollback()
            return {"status": "error"}

        if ai_data["action"] == "ADD":
            product.current_stock += ai_data["qty"]
            reply = f"✅ ADD completed. New stock for {product.sku}: {product.current_stock}"

        elif ai_data["action"] == "SHIP":
            if product.current_stock < ai_data["qty"]:
                reply = "⚠️ Insufficient stock."
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
            reply = f"✅ SHIP completed. New stock for {product.sku}: {product.current_stock}"

        else:
            # CHECK or unknown: respond with current stock
            reply = f"ℹ️ Current stock for {product.sku}: {product.current_stock}"

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





