"""
API routes package for TTS service.

Contains route modules for TTS operations and health checks.
"""

from app.api.routes.health import router as health_router
from app.api.routes.tts import router as tts_router

__all__ = [
    "health_router",
    "tts_router",
]
