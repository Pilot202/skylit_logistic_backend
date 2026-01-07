"""
Intent Parser - Pattern matching for common operations
Reduces Gemini API calls by using regex for simple commands
"""

import re
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def extract_sku_from_text(text: str) -> Optional[str]:
    """
    Extract SKU from text using common patterns
    Looks for: SKU: XXX, product codes, or product names
    """
    # Pattern 1: Explicit SKU mention (e.g., "SKU: PHN-CHG-001" or "sku PHN-CHG-001")
    sku_pattern = r'sku[:\s]+([A-Z0-9\-]+)'
    match = re.search(sku_pattern, text, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    # Pattern 2: Product code format (e.g., "PHN-CHG-001")
    code_pattern = r'\b([A-Z]{3}-[A-Z]{3}-\d{3})\b'
    match = re.search(code_pattern, text, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    # Pattern 3: Common product names (map to SKUs)
    product_mappings = {
        r'phone\s*charger': 'PHN-CHG-001',
        r'usb\s*cable': 'USB-CBL-001',
        r'hdmi\s*cable': 'HDM-CBL-001',
        r'laptop\s*bag': 'LAP-BAG-001',
        r'wireless\s*mouse': 'MSE-WRL-001',
        r'mechanical\s*keyboard': 'KBD-MEC-001',
    }
    
    for pattern, sku in product_mappings.items():
        if re.search(pattern, text, re.IGNORECASE):
            return sku
    
    return None


def extract_quantity(text: str) -> Optional[int]:
    """Extract quantity from text"""
    # Pattern: number followed by optional "units" or before product name
    patterns = [
        r'(\d+)\s*units?',
        r'add\s+(\d+)',
        r'ship\s+(\d+)',
        r'(\d+)\s+(?:of|x)',
        r'quantity[:\s]+(\d+)',
        r'unit[:\s]+(\d+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
    
    # Fallback: find any number in the text
    numbers = re.findall(r'\b(\d+)\b', text)
    if numbers:
        return int(numbers[0])
    
    return None


def extract_seller(text: str) -> Optional[str]:
    """Extract seller name from text"""
    patterns = [
        r'seller[:\s]+([A-Za-z\s]+?)(?:\s|$)',
        r'from\s+([A-Za-z\s]+?)(?:\s|$)',
        r'by\s+([A-Za-z\s]+?)(?:\s|$)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            seller = match.group(1).strip()
            # Remove common trailing words
            seller = re.sub(r'\s+(to|at|in)$', '', seller, flags=re.IGNORECASE)
            return seller
    
    return None


def extract_destination(text: str) -> Optional[str]:
    """Extract destination from text"""
    patterns = [
        r'to\s+([A-Za-z0-9\s]+?)(?:\s|$)',
        r'destination[:\s]+([A-Za-z0-9\s]+?)(?:\s|$)',
        r'warehouse\s+([A-Za-z0-9]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    
    return "warehouse"  # Default destination


def parse_intent_from_text(text: str) -> Dict[str, Any]:
    """
    Parse user intent using pattern matching
    Returns dict with intent and extracted parameters
    """
    text_lower = text.lower()
    
    # Intent: ADD_STOCK
    add_patterns = [
        r'\badd\b',
        r'\brestock\b',
        r'\binbound\b',
        r'\breceive[d]?\b',
        r'\bnew\s+stock\b',
    ]
    
    if any(re.search(pattern, text_lower) for pattern in add_patterns):
        return {
            "intent": "ADD_STOCK",
            "sku": extract_sku_from_text(text),
            "quantity": extract_quantity(text),
            "seller": extract_seller(text),
            "confidence": "high"
        }
    
    # Intent: SHIP_STOCK
    ship_patterns = [
        r'\bship\b',
        r'\bsend\b',
        r'\boutbound\b',
        r'\bdispatch\b',
        r'\bremove\b',
        r'\btake\s+out\b',
    ]
    
    if any(re.search(pattern, text_lower) for pattern in ship_patterns):
        return {
            "intent": "SHIP_STOCK",
            "sku": extract_sku_from_text(text),
            "quantity": extract_quantity(text),
            "destination": extract_destination(text),
            "confidence": "high"
        }
    
    # Intent: CHECK_STOCK
    check_patterns = [
        r'\bcheck\b',
        r'\bstock\b',
        r'\binventory\b',
        r'\bhow\s+many\b',
        r'\bavailable\b',
        r'\bwhat.*in\s+stock\b',
        r'\bshow\s+me\b',
        r'\blist\b',
    ]
    
    if any(re.search(pattern, text_lower) for pattern in check_patterns):
        return {
            "intent": "CHECK_STOCK",
            "sku": extract_sku_from_text(text),
            "confidence": "high"
        }
    
    # Intent: GENERAL (greetings, help, etc.)
    general_patterns = [
        r'\bhello\b',
        r'\bhi\b',
        r'\bhey\b',
        r'\bhelp\b',
        r'\bthanks?\b',
        r'\bbye\b',
    ]
    
    if any(re.search(pattern, text_lower) for pattern in general_patterns):
        return {
            "intent": "GENERAL",
            "confidence": "high"
        }
    
    # Unknown intent - will need Gemini
    return {
        "intent": "UNKNOWN",
        "confidence": "low"
    }


def get_general_response(text: str) -> str:
    """
    Generate simple responses for general queries without calling Gemini
    """
    text_lower = text.lower()
    
    if any(word in text_lower for word in ['hello', 'hi', 'hey']):
        return "👋 Hello! I'm your Skylit Logistics assistant. I can help you:\n• Check inventory: 'What's in stock?'\n• Add stock: 'Add 10 phone chargers from Acme'\n• Ship items: 'Ship 5 USB cables to warehouse B'\n\nHow can I help you today?"
    
    if 'help' in text_lower:
        return "📦 I can help you manage inventory:\n\n✅ Check Stock: 'Check phone chargers' or 'What's in stock?'\n✅ Add Stock: 'Add 20 USB cables from TechSupply'\n✅ Ship Items: 'Ship 15 keyboards to warehouse A'\n\nJust tell me what you need!"
    
    if any(word in text_lower for word in ['thanks', 'thank you']):
        return "You're welcome! Let me know if you need anything else. 😊"
    
    if any(word in text_lower for word in ['bye', 'goodbye']):
        return "Goodbye! Feel free to message anytime you need inventory help. 👋"
    
    return None  # Will use Gemini for other general queries
