"""
Inventory Service - Database operations for inventory management
Handles products, sellers, transactions, and stock management
"""

import logging
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import or_
from datetime import datetime

from .models import Product, Seller, Transaction, TransactionType, Staff
from .database import SessionLocal

logger = logging.getLogger(__name__)


# -------------------------------------------------
# Product Operations
# -------------------------------------------------

def get_product_by_sku(db: Session, sku: str, seller_id: Optional[int] = None) -> Optional[Product]:
    """Get product by SKU, optionally filtered by seller"""
    query = db.query(Product).filter(Product.sku == sku)
    if seller_id:
        query = query.filter(Product.seller_id == seller_id)
    return query.first()


def get_product_by_id(db: Session, product_id: int) -> Optional[Product]:
    """Get product by ID"""
    return db.query(Product).filter(Product.id == product_id).first()


def get_all_products(db: Session, seller_id: Optional[int] = None) -> List[Product]:
    """Get all products, optionally filtered by seller"""
    query = db.query(Product)
    if seller_id:
        query = query.filter(Product.seller_id == seller_id)
    return query.all()


def search_products(db: Session, search_term: str) -> List[Product]:
    """Search products by name or SKU (case-insensitive)"""
    search_pattern = f"%{search_term.lower()}%"
    return db.query(Product).filter(
        or_(
            Product.product_name.ilike(search_pattern),
            Product.sku.ilike(search_pattern)
        )
    ).all()


def create_product(
    db: Session,
    seller_id: int,
    sku: str,
    product_name: str,
    initial_stock: int = 0
) -> Product:
    """Create a new product"""
    product = Product(
        seller_id=seller_id,
        sku=sku,
        product_name=product_name,
        current_stock=initial_stock
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    logger.info(f"Created product: {product_name} (SKU: {sku}) with {initial_stock} units")
    return product


def update_product_stock(db: Session, product_id: int, new_stock: int) -> Optional[Product]:
    """Update product stock level directly"""
    product = get_product_by_id(db, product_id)
    if product:
        product.current_stock = new_stock
        db.commit()
        db.refresh(product)
        logger.info(f"Updated stock for {product.product_name}: {new_stock} units")
    return product


# -------------------------------------------------
# Seller Operations
# -------------------------------------------------

def get_seller_by_business_id(db: Session, business_id: str) -> Optional[Seller]:
    """Get seller by business ID"""
    return db.query(Seller).filter(Seller.business_id == business_id).first()


def get_seller_by_id(db: Session, seller_id: int) -> Optional[Seller]:
    """Get seller by ID"""
    return db.query(Seller).filter(Seller.id == seller_id).first()


def get_seller_by_name(db: Session, name: str) -> Optional[Seller]:
    """Get seller by name (case-insensitive)"""
    return db.query(Seller).filter(Seller.name.ilike(name)).first()


def get_all_sellers(db: Session) -> List[Seller]:
    """Get all sellers"""
    return db.query(Seller).all()


def create_seller(
    db: Session,
    name: str,
    business_id: str,
    contact_info: Optional[str] = None
) -> Seller:
    """Create a new seller"""
    seller = Seller(
        name=name,
        business_id=business_id,
        contact_info=contact_info
    )
    db.add(seller)
    db.commit()
    db.refresh(seller)
    logger.info(f"Created seller: {name} (Business ID: {business_id})")
    return seller


# -------------------------------------------------
# Transaction Operations
# -------------------------------------------------

def log_transaction(
    db: Session,
    product_id: int,
    transaction_type: TransactionType,
    quantity: int,
    staff_id: Optional[int] = None,
    destination: Optional[str] = None
) -> Transaction:
    """Log a transaction (inbound or outbound)"""
    transaction = Transaction(
        product_id=product_id,
        staff_id=staff_id,
        type=transaction_type,
        quantity=quantity,
        destination=destination,
        timestamp=datetime.utcnow()
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    logger.info(f"Logged {transaction_type.value} transaction: {quantity} units of product {product_id}")
    return transaction


def get_product_transactions(db: Session, product_id: int, limit: int = 50) -> List[Transaction]:
    """Get recent transactions for a product"""
    return db.query(Transaction).filter(
        Transaction.product_id == product_id
    ).order_by(Transaction.timestamp.desc()).limit(limit).all()


# -------------------------------------------------
# Stock Management
# -------------------------------------------------

def add_stock(
    db: Session,
    sku: str,
    quantity: int,
    seller_name: Optional[str] = None,
    staff_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Add stock (inbound transaction)
    Returns dict with success status and message
    """
    try:
        # Find or create seller
        seller = None
        if seller_name:
            seller = get_seller_by_name(db, seller_name)
            if not seller:
                # Create new seller with auto-generated business ID
                business_id = f"BIZ-{seller_name.upper().replace(' ', '-')}"
                seller = create_seller(db, seller_name, business_id)
        
        # Find or create product
        product = get_product_by_sku(db, sku)
        if not product:
            if not seller:
                # Create default seller if none specified
                seller = get_seller_by_name(db, "Default Seller")
                if not seller:
                    seller = create_seller(db, "Default Seller", "BIZ-DEFAULT")
            
            # Create new product
            product = create_product(
                db,
                seller_id=seller.id,
                sku=sku,
                product_name=sku.replace("-", " ").title(),
                initial_stock=0
            )
        
        # Update stock
        product.current_stock += quantity
        db.commit()
        
        # Log transaction
        log_transaction(
            db,
            product_id=product.id,
            transaction_type=TransactionType.INBOUND,
            quantity=quantity,
            staff_id=staff_id
        )
        
        return {
            "success": True,
            "message": f"✅ Added {quantity} units of {product.product_name} (SKU: {sku}). New stock: {product.current_stock}",
            "product": product,
            "new_stock": product.current_stock
        }
    
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to add stock: {e}")
        return {
            "success": False,
            "message": f"❌ Failed to add stock: {str(e)}",
            "error": str(e)
        }


def remove_stock(
    db: Session,
    sku: str,
    quantity: int,
    destination: Optional[str] = None,
    staff_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Remove stock (outbound/ship transaction)
    Returns dict with success status and message
    """
    try:
        # Find product
        product = get_product_by_sku(db, sku)
        if not product:
            return {
                "success": False,
                "message": f"❌ Product with SKU '{sku}' not found in inventory."
            }
        
        # Check if sufficient stock
        if product.current_stock < quantity:
            return {
                "success": False,
                "message": f"❌ Insufficient stock for {product.product_name}. Available: {product.current_stock}, Requested: {quantity}"
            }
        
        # Update stock
        product.current_stock -= quantity
        db.commit()
        
        # Log transaction
        log_transaction(
            db,
            product_id=product.id,
            transaction_type=TransactionType.OUTBOUND,
            quantity=quantity,
            staff_id=staff_id,
            destination=destination
        )
        
        return {
            "success": True,
            "message": f"✅ Shipped {quantity} units of {product.product_name} (SKU: {sku}) to {destination or 'destination'}. Remaining stock: {product.current_stock}",
            "product": product,
            "new_stock": product.current_stock
        }
    
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to remove stock: {e}")
        return {
            "success": False,
            "message": f"❌ Failed to remove stock: {str(e)}",
            "error": str(e)
        }


def check_stock(db: Session, sku: Optional[str] = None) -> Dict[str, Any]:
    """
    Check stock levels
    If SKU provided, return specific product info
    Otherwise return all inventory
    """
    try:
        if sku:
            product = get_product_by_sku(db, sku)
            if not product:
                return {
                    "success": False,
                    "message": f"❌ Product with SKU '{sku}' not found."
                }
            
            seller = get_seller_by_id(db, product.seller_id)
            return {
                "success": True,
                "message": f"📦 {product.product_name} (SKU: {sku})\n   Stock: {product.current_stock} units\n   Seller: {seller.name if seller else 'Unknown'}",
                "product": product,
                "stock": product.current_stock
            }
        else:
            # Return all inventory
            products = get_all_products(db)
            if not products:
                return {
                    "success": True,
                    "message": "📦 Inventory is currently empty.",
                    "products": []
                }
            
            inventory_list = []
            for product in products:
                seller = get_seller_by_id(db, product.seller_id)
                inventory_list.append({
                    "sku": product.sku,
                    "name": product.product_name,
                    "stock": product.current_stock,
                    "seller": seller.name if seller else "Unknown"
                })
            
            # Format message
            message = "📦 Current Inventory:\n"
            for item in inventory_list:
                message += f"   • {item['name']} (SKU: {item['sku']}): {item['stock']} units - Seller: {item['seller']}\n"
            
            return {
                "success": True,
                "message": message.strip(),
                "products": inventory_list
            }
    
    except Exception as e:
        logger.error(f"Failed to check stock: {e}")
        return {
            "success": False,
            "message": f"❌ Failed to check stock: {str(e)}",
            "error": str(e)
        }


# -------------------------------------------------
# Inventory Summary for Gemini Context
# -------------------------------------------------

def get_inventory_summary(db: Session) -> str:
    """
    Get formatted inventory summary for Gemini context
    Returns a string with all products and their stock levels
    """
    try:
        products = get_all_products(db)
        if not products:
            return "No products in inventory."
        
        summary = "Current Inventory:\n"
        for product in products:
            seller = get_seller_by_id(db, product.seller_id)
            seller_name = seller.name if seller else "Unknown"
            summary += f"- {product.product_name} (SKU: {product.sku}): {product.current_stock} units (Seller: {seller_name})\n"
        
        return summary.strip()
    
    except Exception as e:
        logger.error(f"Failed to get inventory summary: {e}")
        return "Unable to retrieve inventory data."
