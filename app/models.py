from sqlalchemy import Column, Integer, String, ForeignKey, Enum, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base
import enum

class StaffRole(enum.Enum):
    MANAGER = "MANAGER"
    WAREHOUSE = "WAREHOUSE"

class TransactionType(enum.Enum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"

class Seller(Base):
    __tablename__ = "sellers"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    business_id = Column(String, unique=True, nullable=False)
    contact_info = Column(String)

    products = relationship("Product", back_populates="seller")

class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    seller_id = Column(Integer, ForeignKey("sellers.id"))
    sku = Column(String, index=True)
    product_name = Column(String)
    current_stock = Column(Integer, default=0)

    seller = relationship("Seller", back_populates="products")
    transactions = relationship("Transaction", back_populates="product")

class Staff(Base):
    __tablename__ = "staff"

    id = Column(Integer, primary_key=True)
    phone_number = Column(String, unique=True)
    role = Column(Enum(StaffRole))

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    staff_id = Column(Integer, ForeignKey("staff.id"))
    type = Column(Enum(TransactionType))
    quantity = Column(Integer)
    destination = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="transactions")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)
    sender = Column(String, index=True)
    direction = Column(String)  # 'in' or 'out'
    message = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)
