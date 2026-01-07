"""
Unit tests for inventory service
"""

import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import Seller, Product, Transaction, TransactionType
from app import inventory_service


# Create in-memory SQLite database for testing
@pytest.fixture
def db_session():
    """Create a test database session"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine)
    session = TestSessionLocal()
    
    yield session
    
    session.close()


@pytest.fixture
def sample_seller(db_session):
    """Create a sample seller"""
    seller = Seller(name="Test Seller", business_id="BIZ-TEST", contact_info="test@example.com")
    db_session.add(seller)
    db_session.commit()
    db_session.refresh(seller)
    return seller


@pytest.fixture
def sample_product(db_session, sample_seller):
    """Create a sample product"""
    product = Product(
        seller_id=sample_seller.id,
        sku="TEST-001",
        product_name="Test Product",
        current_stock=100
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product


# -------------------------------------------------
# Product Operations Tests
# -------------------------------------------------

def test_get_product_by_sku(db_session, sample_product):
    """Test getting product by SKU"""
    product = inventory_service.get_product_by_sku(db_session, "TEST-001")
    assert product is not None
    assert product.sku == "TEST-001"
    assert product.product_name == "Test Product"


def test_get_product_by_sku_not_found(db_session):
    """Test getting non-existent product"""
    product = inventory_service.get_product_by_sku(db_session, "NONEXISTENT")
    assert product is None


def test_create_product(db_session, sample_seller):
    """Test creating a new product"""
    product = inventory_service.create_product(
        db_session,
        seller_id=sample_seller.id,
        sku="NEW-001",
        product_name="New Product",
        initial_stock=50
    )
    assert product.id is not None
    assert product.sku == "NEW-001"
    assert product.current_stock == 50


def test_search_products(db_session, sample_product):
    """Test searching products by name or SKU"""
    results = inventory_service.search_products(db_session, "test")
    assert len(results) > 0
    assert results[0].product_name == "Test Product"


# -------------------------------------------------
# Seller Operations Tests
# -------------------------------------------------

def test_get_seller_by_business_id(db_session, sample_seller):
    """Test getting seller by business ID"""
    seller = inventory_service.get_seller_by_business_id(db_session, "BIZ-TEST")
    assert seller is not None
    assert seller.name == "Test Seller"


def test_create_seller(db_session):
    """Test creating a new seller"""
    seller = inventory_service.create_seller(
        db_session,
        name="New Seller",
        business_id="BIZ-NEW",
        contact_info="new@example.com"
    )
    assert seller.id is not None
    assert seller.name == "New Seller"


# -------------------------------------------------
# Stock Management Tests
# -------------------------------------------------

def test_add_stock_existing_product(db_session, sample_product):
    """Test adding stock to existing product"""
    initial_stock = sample_product.current_stock
    result = inventory_service.add_stock(db_session, sku="TEST-001", quantity=50)
    
    assert result["success"] is True
    assert "Added 50 units" in result["message"]
    assert result["new_stock"] == initial_stock + 50


def test_add_stock_new_product(db_session, sample_seller):
    """Test adding stock creates new product if not exists"""
    result = inventory_service.add_stock(
        db_session,
        sku="NEW-PRODUCT",
        quantity=25,
        seller_name="Test Seller"
    )
    
    assert result["success"] is True
    assert result["new_stock"] == 25
    
    # Verify product was created
    product = inventory_service.get_product_by_sku(db_session, "NEW-PRODUCT")
    assert product is not None


def test_remove_stock_success(db_session, sample_product):
    """Test removing stock successfully"""
    result = inventory_service.remove_stock(
        db_session,
        sku="TEST-001",
        quantity=30,
        destination="Warehouse A"
    )
    
    assert result["success"] is True
    assert "Shipped 30 units" in result["message"]
    assert result["new_stock"] == 70


def test_remove_stock_insufficient(db_session, sample_product):
    """Test removing more stock than available"""
    result = inventory_service.remove_stock(
        db_session,
        sku="TEST-001",
        quantity=200
    )
    
    assert result["success"] is False
    assert "Insufficient stock" in result["message"]


def test_remove_stock_product_not_found(db_session):
    """Test removing stock from non-existent product"""
    result = inventory_service.remove_stock(
        db_session,
        sku="NONEXISTENT",
        quantity=10
    )
    
    assert result["success"] is False
    assert "not found" in result["message"]


def test_check_stock_specific_product(db_session, sample_product):
    """Test checking stock for specific product"""
    result = inventory_service.check_stock(db_session, sku="TEST-001")
    
    assert result["success"] is True
    assert "Test Product" in result["message"]
    assert result["stock"] == 100


def test_check_stock_all_inventory(db_session, sample_product):
    """Test checking all inventory"""
    result = inventory_service.check_stock(db_session)
    
    assert result["success"] is True
    assert "Current Inventory" in result["message"]
    assert len(result["products"]) > 0


# -------------------------------------------------
# Transaction Logging Tests
# -------------------------------------------------

def test_log_transaction(db_session, sample_product):
    """Test logging a transaction"""
    transaction = inventory_service.log_transaction(
        db_session,
        product_id=sample_product.id,
        transaction_type=TransactionType.INBOUND,
        quantity=50
    )
    
    assert transaction.id is not None
    assert transaction.product_id == sample_product.id
    assert transaction.quantity == 50
    assert transaction.type == TransactionType.INBOUND


def test_get_product_transactions(db_session, sample_product):
    """Test getting product transaction history"""
    # Create some transactions
    inventory_service.log_transaction(
        db_session,
        product_id=sample_product.id,
        transaction_type=TransactionType.INBOUND,
        quantity=50
    )
    
    transactions = inventory_service.get_product_transactions(db_session, sample_product.id)
    assert len(transactions) > 0


# -------------------------------------------------
# Inventory Summary Tests
# -------------------------------------------------

def test_get_inventory_summary(db_session, sample_product):
    """Test getting inventory summary for Gemini context"""
    summary = inventory_service.get_inventory_summary(db_session)
    
    assert "Current Inventory" in summary
    assert "Test Product" in summary
    assert "TEST-001" in summary
    assert "100 units" in summary
