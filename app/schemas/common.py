"""Common Pydantic schemas and standard error envelopes."""

from typing import Any, Optional
from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Detailed error object within the standardized error envelope."""

    code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable error explanation")
    request_id: Optional[str] = Field(
        None, description="Unique trace request ID"
    )
    details: Any = Field(
        default_factory=dict, description="Additional contextual metadata or field validation details"
    )


class ErrorResponse(BaseModel):
    """Normalized top-level error response envelope required across all API endpoints."""

    error: ErrorDetail
