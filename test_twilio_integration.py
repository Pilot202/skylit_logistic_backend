#!/usr/bin/env python3
"""
Test script to verify Twilio WhatsApp integration end-to-end.
Run this AFTER the backend is started to verify webhook and sending.
"""

import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "http://localhost:8009"
TWILIO_TEST_PHONE = "+14155238886"  # Replace with a real phone in E.164 format

def test_webhook_incoming():
    """Simulate incoming WhatsApp message via Twilio webhook."""
    print("\n[TEST 1] Simulating incoming Twilio WhatsApp message...")
    url = f"{BASE_URL}/webhook/twilio"
    data = {
        "From": f"whatsapp:{TWILIO_TEST_PHONE}",
        "Body": "CHECK WID-A"
    }
    response = requests.post(url, data=data)
    print(f"  Status: {response.status_code}")
    print(f"  Response: {response.json()}")
    return response.status_code == 200

def test_broadcast():
    """Send a test broadcast to the dashboard."""
    print("\n[TEST 2] Sending test broadcast (inventory update)...")
    url = f"{BASE_URL}/admin/test-broadcast"
    payload = {
        "sku": "WID-A",
        "stock": 42,
        "seller": "Acme",
        "action": "ADD"
    }
    response = requests.post(url, json=payload)
    print(f"  Status: {response.status_code}")
    print(f"  Response: {response.json()}")
    return response.status_code == 200

def test_health():
    """Check backend health."""
    print("\n[TEST 0] Checking backend health...")
    url = f"{BASE_URL}/__healthcheck__"
    try:
        response = requests.get(url, timeout=5)
        print(f"  Status: {response.status_code}")
        print(f"  Response: {response.json()}")
        return response.status_code == 200
    except Exception as e:
        print(f"  ERROR: {e}")
        return False

def test_inventory():
    """Fetch current inventory."""
    print("\n[TEST 3] Fetching inventory...")
    url = f"{BASE_URL}/admin/inventory"
    try:
        response = requests.get(url, timeout=5)
        print(f"  Status: {response.status_code}")
        data = response.json()
        if data:
            print(f"  Sample product: {data[0]}")
        else:
            print("  No products in inventory (expected if DB is empty)")
        return response.status_code == 200
    except Exception as e:
        print(f"  ERROR: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("SKYLIT TWILIO INTEGRATION TEST")
    print("=" * 60)
    
    results = {}
    
    # Run tests in order
    results["Health"] = test_health()
    if not results["Health"]:
        print("\n❌ Backend is not running. Start it with:")
        print("   cd backend && uvicorn app.main:app --reload --port 8000")
        exit(1)
    
    results["Inventory"] = test_inventory()
    results["Broadcast"] = test_broadcast()
    results["Webhook"] = test_webhook_incoming()
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{test_name:20} {status}")
    
    all_pass = all(results.values())
    print("=" * 60)
    if all_pass:
        print("✅ All tests passed! Twilio integration is ready.")
        print("\nNext steps:")
        print("1. Start frontend: cd admin-dashboard && npm run dev")
        print("2. Open http://localhost:5173")
        print("3. Send a WhatsApp message to your Twilio sandbox number:")
        print("   - First join sandbox with the code shown in Twilio Console")
        print("   - Then send: CHECK WID-A (or similar)")
        print("4. Watch the dashboard update in real-time")
    else:
        print("❌ Some tests failed. Check the logs above.")
        exit(1)
