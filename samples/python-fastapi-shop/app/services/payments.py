import requests

from app.core.config import settings


def charge(order_id: int, amount: float) -> bool:
    """Charge an order through the external payment provider."""
    resp = requests.post(f"{settings.payment_api_url}/charges", json={"order": order_id, "amount": amount})
    return resp.status_code == 200
