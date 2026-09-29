"""API v1 router aggregating all endpoints."""

from fastapi import APIRouter
from app.api.v1.endpoints import orders

api_v1_router = APIRouter()
api_v1_router.include_router(orders.router, prefix="/orders", tags=["Orders"])
