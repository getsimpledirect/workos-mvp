"""
Voice-Cloning Text-to-Speech REST API.

Built on Coqui XTTS-v2 + FastAPI.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from app import __version__
from app.api.routes import health, tts
from app.config import GCS_BUCKET_NAME, MAX_WORKERS, REDIS_URL
from app.core.tts_engine import initialize_tts_engine
from app.services.job_store import get_job_store, initialize_job_store
from app.services.notification import close_http_client, initialize_http_client
from app.services.storage import cleanup_gcs_client, initialize_gcs_client
from app.services.synthesis import initialize_executor, shutdown_executor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("tts-service")


TAGS_METADATA = [
    {
        "name": "TTS",
        "description": "Text-to-Speech synthesis and job management.",
    },
    {
        "name": "Health",
        "description": "Health checks and readiness probes.",
    },
]

API_DESCRIPTION = """
Voice-cloning Text-to-Speech API powered by **XTTS-v2** for Ghost CMS.

## Features

- Voice cloning from reference audio
- Long-form text support (up to 100,000 characters)
- Google Cloud Storage integration
- Async job processing with status tracking

## Workflow

1. **POST** `/tts/generate` — Submit text, receive `job_id`
2. **GET** `/tts/status/{job_id}` — Poll until status is `completed`
3. **GET** `/tts/download/{job_id}` — Download the audio file
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for startup and shutdown."""
    logger.info("Starting TTS service...")

    try:
        initialize_tts_engine()
        logger.info("TTS engine initialized")
    except Exception as exc:
        logger.error(f"Failed to initialize TTS engine: {exc}")
        raise

    try:
        await initialize_job_store(REDIS_URL)
        logger.info("Job store initialized")
    except Exception as exc:
        logger.error(f"Failed to initialize job store: {exc}")
        raise

    if GCS_BUCKET_NAME:
        try:
            initialize_gcs_client()
            logger.info("GCS client initialized")
        except Exception as exc:
            logger.warning(f"GCS client initialization failed (non-fatal): {exc}")

    try:
        initialize_executor(MAX_WORKERS)
        logger.info(f"Thread pool executor initialized with {MAX_WORKERS} workers")
    except Exception as exc:
        logger.error(f"Failed to initialize executor: {exc}")
        raise

    try:
        initialize_http_client()
        logger.info("HTTP client initialized")
    except Exception as exc:
        logger.warning(f"HTTP client initialization failed (non-fatal): {exc}")

    logger.info("TTS service startup complete")

    yield

    logger.info("Shutting down TTS service...")

    try:
        job_store = get_job_store()
        await job_store.close()
        logger.info("Job store closed")
    except Exception as exc:
        logger.error(f"Error closing job store: {exc}")

    try:
        shutdown_executor(wait=True, cancel_futures=True)
        logger.info("Thread pool executor shut down")
    except Exception as exc:
        logger.error(f"Error shutting down executor: {exc}")

    try:
        await close_http_client()
        logger.info("HTTP client closed")
    except Exception as exc:
        logger.error(f"Error closing HTTP client: {exc}")

    try:
        cleanup_gcs_client()
        logger.info("GCS client cleaned up")
    except Exception as exc:
        logger.error(f"Error cleaning up GCS client: {exc}")

    logger.info("TTS service shutdown complete")


app = FastAPI(
    title="Ghost Narrator TTS API",
    summary="Voice-cloning Text-to-Speech service for Ghost CMS",
    description=API_DESCRIPTION,
    version=__version__,
    lifespan=lifespan,
    openapi_tags=TAGS_METADATA,
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT",
    },
)

app.include_router(health.router)
app.include_router(tts.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8020,
        reload=False,
        log_level="info",
    )
