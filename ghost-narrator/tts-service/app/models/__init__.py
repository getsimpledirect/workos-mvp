"""
Pydantic models for TTS service.

Contains request/response schemas for API endpoints.
"""

from app.models.schemas import (
    ErrorResponse,
    GenerateRequest,
    GenerateResponse,
    HealthResponse,
    JobListResponse,
    StatusResponse,
)

__all__ = [
    "ErrorResponse",
    "GenerateRequest",
    "GenerateResponse",
    "HealthResponse",
    "JobListResponse",
    "StatusResponse",
]
