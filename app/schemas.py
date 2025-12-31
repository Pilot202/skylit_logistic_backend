from pydantic import BaseModel
from typing import Optional
from enum import Enum


class ActionType(str, Enum):
    SHIP = "SHIP"
    ADD = "ADD"
    CHECK = "CHECK"


class ParsedMessage(BaseModel):
    action: ActionType
    seller: Optional[str]
    sku: Optional[str]
    qty: Optional[int]
    location: Optional[str]


class ProductOut(BaseModel):
    id: int
    seller_id: int
    sku: str
    product_name: Optional[str]
    current_stock: int

    class Config:
        orm_mode = True
