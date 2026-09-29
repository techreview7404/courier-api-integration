"""Order API routes re-exported from v1 endpoints for simplified import access."""

from app.api.v1.endpoints.orders import router

__all__ = ["router"]
