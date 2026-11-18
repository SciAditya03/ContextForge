from sqlalchemy.orm import Session

from app.models.order import Order, OrderItem
from app.models.product import Product
from app.schemas.order import OrderCreate
from app.services.payments import charge


class OutOfStock(Exception):
    pass


def place_order(db: Session, user_id: int, data: OrderCreate) -> Order:
    total = 0
    for line in data.items:
        product = db.query(Product).filter(Product.id == line.product_id).first()
        if product.stock < line.quantity:
            raise OutOfStock(product.name)
        product.stock -= line.quantity
        total += float(product.price) * line.quantity
    order = Order(user_id=user_id, total=total)
    db.add(order)
    db.flush()
    for line in data.items:
        db.add(OrderItem(order_id=order.id, product_id=line.product_id, quantity=line.quantity))
    if not charge(order.id, total):
        order.status = "payment_failed"
    else:
        order.status = "paid"
    db.commit()
    return order


def order_report(db: Session, status: str):
    return db.execute(f"SELECT id, total FROM orders WHERE status = '{status}'").fetchall()
