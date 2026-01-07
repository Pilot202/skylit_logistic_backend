"""
Database Initialization Script
Creates all tables and optionally seeds sample data for testing
"""

import os
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import engine, Base, SessionLocal
from app.models import Seller, Product, Staff, StaffRole
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init_db(seed_data: bool = True):
    """
    Initialize database tables and optionally seed sample data
    """
    logger.info("Creating database tables...")
    
    try:
        # Create all tables
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Database tables created successfully!")
        
        if seed_data:
            logger.info("Seeding sample data...")
            seed_sample_data()
            logger.info("✅ Sample data seeded successfully!")
        
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        raise


def seed_sample_data():
    """
    Seed the database with sample sellers, products, and staff
    """
    db = SessionLocal()
    
    try:
        # Check if data already exists
        existing_sellers = db.query(Seller).count()
        if existing_sellers > 0:
            logger.info("Database already has data. Skipping seed.")
            return
        
        # Create sample sellers
        sellers = [
            Seller(name="Acme Corp", business_id="BIZ-ACME", contact_info="acme@example.com"),
            Seller(name="TechSupply Inc", business_id="BIZ-TECH", contact_info="tech@example.com"),
            Seller(name="Global Traders", business_id="BIZ-GLOBAL", contact_info="global@example.com"),
        ]
        
        for seller in sellers:
            db.add(seller)
        
        db.commit()
        logger.info(f"Created {len(sellers)} sellers")
        
        # Create sample products
        products = [
            Product(seller_id=1, sku="PHN-CHG-001", product_name="Phone Charger", current_stock=50),
            Product(seller_id=1, sku="USB-CBL-001", product_name="USB Cable", current_stock=100),
            Product(seller_id=2, sku="HDM-CBL-001", product_name="HDMI Cable", current_stock=75),
            Product(seller_id=2, sku="LAP-BAG-001", product_name="Laptop Bag", current_stock=30),
            Product(seller_id=3, sku="MSE-WRL-001", product_name="Wireless Mouse", current_stock=60),
            Product(seller_id=3, sku="KBD-MEC-001", product_name="Mechanical Keyboard", current_stock=25),
        ]
        
        for product in products:
            db.add(product)
        
        db.commit()
        logger.info(f"Created {len(products)} products")
        
        # Create sample staff
        staff_members = [
            Staff(phone_number="+1234567890", role=StaffRole.MANAGER),
            Staff(phone_number="+0987654321", role=StaffRole.WAREHOUSE),
        ]
        
        for staff in staff_members:
            db.add(staff)
        
        db.commit()
        logger.info(f"Created {len(staff_members)} staff members")
        
        # Display summary
        logger.info("\n" + "="*50)
        logger.info("SAMPLE DATA SUMMARY")
        logger.info("="*50)
        logger.info("\nSellers:")
        for seller in sellers:
            logger.info(f"  - {seller.name} (ID: {seller.business_id})")
        
        logger.info("\nProducts:")
        for product in products:
            seller = db.query(Seller).filter(Seller.id == product.seller_id).first()
            logger.info(f"  - {product.product_name} (SKU: {product.sku})")
            logger.info(f"    Stock: {product.current_stock} | Seller: {seller.name if seller else 'Unknown'}")
        
        logger.info("\n" + "="*50)
        
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to seed data: {e}")
        raise
    
    finally:
        db.close()


def drop_all_tables():
    """
    Drop all tables (use with caution!)
    """
    logger.warning("⚠️  Dropping all tables...")
    Base.metadata.drop_all(bind=engine)
    logger.info("✅ All tables dropped")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Initialize Skylit Logistics Database")
    parser.add_argument("--no-seed", action="store_true", help="Don't seed sample data")
    parser.add_argument("--reset", action="store_true", help="Drop all tables before creating (CAUTION!)")
    
    args = parser.parse_args()
    
    if args.reset:
        confirm = input("⚠️  This will DELETE ALL DATA. Are you sure? (yes/no): ")
        if confirm.lower() == "yes":
            drop_all_tables()
        else:
            logger.info("Reset cancelled")
            sys.exit(0)
    
    init_db(seed_data=not args.no_seed)
    logger.info("\n🎉 Database initialization complete!")
