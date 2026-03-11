"""
API module for TTS service.

Contains route definitions for all API endpoints.
"""

from fastapi import APIRouter

from app.api.routes import health, tts

# Create main API router
api_router = APIRouter()

# Include sub-routers
api_router.include_router(health.router)
api_router.include_router(tts.router)

__all__ = [
    "api_router",
    "health",
    "tts",
]
