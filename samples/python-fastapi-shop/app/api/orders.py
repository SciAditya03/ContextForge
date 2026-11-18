from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.order import OrderCreate, OrderOut
from app.services.orders import OutOfStock, order_report, place_order

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=OrderOut, status_code=201)
def create_order(payload: OrderCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    try:
        return place_order(db, user.id, payload)
    except OutOfStock as exc:
        raise HTTPException(status_code=409, detail=f"Out of stock: {exc}")


@router.get("/report")
def report(status: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return [dict(r) for r in order_report(db, status)]
