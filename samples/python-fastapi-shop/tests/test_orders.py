from app.schemas.order import OrderCreate, OrderLine


def test_order_schema():
    o = OrderCreate(items=[OrderLine(product_id=1, quantity=2)])
    assert o.items[0].quantity == 2
