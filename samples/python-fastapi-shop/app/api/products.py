from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.product import Product

router = APIRouter(prefix="/products", tags=["products"])


@router.get("")
def list_products(db: Session = Depends(get_db)):
    return db.query(Product).all()


@router.get("/{product_id}")
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    return {"id": product.id, "name": product.name, "price": float(product.price)}


@router.delete("/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db)):
    db.query(Product).filter(Product.id == product_id).delete()
    db.commit()
    return {"deleted": product_id}
