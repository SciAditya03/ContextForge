from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, orders, products

app = FastAPI(title="Shop API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(auth.router)
app.include_router(products.router, prefix="/api")
app.include_router(orders.router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}
