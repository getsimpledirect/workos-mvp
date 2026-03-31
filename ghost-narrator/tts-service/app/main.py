# MIT License
#
# Copyright (c) 2026 Ayush Naik
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""
Studio-Quality Text-to-Speech REST API.

Built on Fish Speech v1.5 + FastAPI.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from fastapi import FastAPI

from app import __version__
from app.api.routes import health, tts
from app.config import GCS_BUCKET_NAME, MAX_WORKERS, REDIS_URL, OUTPUT_DIR
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

# Module-level reference to the background model loader task.
# Stored here to prevent it from being garbage collected and to allow
# cancellation on shutdown.
_model_loader_task: Optional[asyncio.Task] = None


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
Studio-quality Text-to-Speech API powered by **Fish Speech v1.5** for Ghost CMS.

## Features

- High-fidelity voice cloning (Zero-shot)
- Natural prosody and breathing
- Long-form text support (up to 100,000 characters)
- Google Cloud Storage integration
- Async job processing with status tracking
- Automatic reference voice calibration
"""


async def _background_model_loader():
    """Load the TTS model in a background thread executor."""
    logger.info("Starting background model loading...")
    loop = asyncio.get_running_loop()
    try:
        # Run blocking initialization in a separate thread
        await loop.run_in_executor(None, initialize_tts_engine)
        logger.info("TTS engine initialized successfully (background)")
    except Exception as exc:
        logger.error(f"Failed to initialize TTS engine (background): {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for startup and shutdown."""
    global _model_loader_task

    logger.info("Starting TTS service...")

    # Start model loading in the background so the API comes up immediately.
    # Store the task reference to prevent GC and to allow cancellation on shutdown.
    _model_loader_task = asyncio.create_task(_background_model_loader())

    # Cleanup orphaned files from previous crashed runs
    try:
        if OUTPUT_DIR.exists():
            for item in OUTPUT_DIR.iterdir():
                try:
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                except Exception as e:
                    logger.warning(f"Failed to cleanup orphaned file {item}: {e}")
        else:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("Cleaned up orphaned files in output directory")
    except Exception as exc:
        logger.warning(f"Output directory cleanup failed: {exc}")

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

    logger.info("TTS service startup complete (model loading in background)")

    yield

    logger.info("Shutting down TTS service...")

    # Cancel background model loader if still running
    if _model_loader_task and not _model_loader_task.done():
        _model_loader_task.cancel()
        try:
            await _model_loader_task
        except asyncio.CancelledError:
            logger.info("Background model loader task cancelled")

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
