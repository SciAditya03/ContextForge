from pydantic import BaseModel


class OrderLine(BaseModel):
    product_id: int
    quantity: int


class OrderCreate(BaseModel):
    items: list[OrderLine]


class OrderOut(BaseModel):
    id: int
    status: str
    total: float
