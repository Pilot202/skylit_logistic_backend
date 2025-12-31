import json
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import models
import importlib


TEST_DATABASE_URL = "sqlite:///:memory:"


def setup_in_memory_db():
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return TestingSessionLocal


def test_whatsapp_webhook_add_action(monkeypatch):
    TestingSessionLocal = setup_in_memory_db()

    # Import the FastAPI app after setting up the test DB to avoid global DB bindings
    main = importlib.import_module('app.main')
    app = main.app

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[main.get_db] = override_get_db

    # Prepare test data
    db = TestingSessionLocal()
    seller = models.Seller(name="Acme", business_id="BIZ-1")
    db.add(seller)
    db.commit()
    db.refresh(seller)
    product = models.Product(seller_id=seller.id, sku="ABC-123", product_name="Widget", current_stock=5)
    db.add(product)
    db.commit()

    # Mock parse_message to return an ADD action
    def fake_parse(text):
        return {"action": "ADD", "seller": "Acme", "sku": "ABC-123", "qty": 3, "location": ""}

    monkeypatch.setattr("app.main.parse_message", fake_parse)

    client = TestClient(app)

    payload = {
        "entry": [{
            "changes": [{
                "value": {"messages": [{"from": "12345", "text": {"body": "Restock 3 of SKU: ABC-123"}}]}
            }]
        }]
    }

    r = client.post("/webhook/whatsapp", json=payload)
    assert r.status_code == 200
    assert r.json().get("status") == "ok"

    # Verify stock updated
    db2 = TestingSessionLocal()
    prod = db2.query(models.Product).filter(models.Product.sku == "ABC-123").first()
    assert prod.current_stock == 8
