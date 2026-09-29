"""FastAPI main application entrypoint and factory."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.endpoints import orders
from app.api.v1.router import api_v1_router
from app.config import settings
from app.database import init_db
from app.middleware.errors import RequestIdMiddleware, register_exception_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager for startup and shutdown hooks."""
    # Initialize SQLite database and tables on startup
    init_db()
    yield


def create_app() -> FastAPI:
    """FastAPI application factory."""
    application = FastAPI(
        title=settings.APP_NAME,
        debug=settings.DEBUG,
        lifespan=lifespan,
    )

    # Add Request ID middleware
    application.add_middleware(RequestIdMiddleware)

    # Configure CORS
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register global exception handlers for unified error envelope
    register_exception_handlers(application)

    # Mount API v1 router
    application.include_router(api_v1_router, prefix="/api/v1")
    # Also mount direct /orders router for path flexibility
    application.include_router(orders.router, prefix="/orders", tags=["Orders"])

    # Health check endpoints
    @application.get("/health", tags=["Health"])
    async def health():
        """Root health check endpoint."""
        return {"status": "ok", "app": settings.APP_NAME}

    @application.get("/api/v1/health", tags=["Health"])
    async def api_v1_health():
        """API v1 health check endpoint."""
        return {"status": "ok", "app": settings.APP_NAME}

    return application


app = create_app()

