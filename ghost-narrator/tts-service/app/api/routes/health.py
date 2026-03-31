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
Health check API routes.

Endpoints for service health monitoring, Kubernetes probes, and debugging.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Response

from app.config import DEVICE, MAX_WORKERS, VOICE_SAMPLE_PATH
from app.core.tts_engine import get_tts_engine
from app.models.schemas import HealthResponse
from app.services.job_store import get_job_store
from app.services.notification import get_http_client
from app.services.storage import get_gcs_client
from app.services.synthesis import get_executor

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns service health status and component information.",
)
async def health() -> HealthResponse:
    """Health check endpoint for Docker and load balancers."""
    voice_ok = Path(VOICE_SAMPLE_PATH).exists()
    voice_dir = Path(VOICE_SAMPLE_PATH).parent
    reference_audio_present = voice_ok
    reference_tokens_present = (voice_dir / "reference_vq_tokens.npy").exists()
    engine = get_tts_engine()
    model_ok = engine.is_ready
    tts_engine_ready = engine.is_ready
    is_healthy = voice_ok and model_ok

    job_store = get_job_store()
    jobs_count = -1
    try:
        jobs_count = await job_store.count()
    except Exception as exc:
        logger.error(f"Error listing jobs in health check: {exc}")

    executor = get_executor()
    gcs_client = get_gcs_client()

    return HealthResponse(
        status="healthy" if is_healthy else "degraded",
        device=DEVICE,
        model="fish-speech-1.5",
        voice_sample=voice_ok,
        model_loaded=model_ok,
        reference_audio_present=reference_audio_present,
        reference_tokens_present=reference_tokens_present,
        tts_engine_ready=tts_engine_ready,
        job_store=job_store.storage_type,
        jobs_count=jobs_count,
        max_workers=MAX_WORKERS,
        executor_active=executor is not None,
        gcs_client_active=gcs_client is not None,
    )


@router.get(
    "/health/ready",
    summary="Readiness probe",
    description="Kubernetes readiness probe. Returns 200 if the service is ready to accept traffic.",
)
async def readiness(response: Response) -> dict[str, Any]:
    """Kubernetes readiness probe endpoint."""
    engine = get_tts_engine()
    voice_ok = Path(VOICE_SAMPLE_PATH).exists()

    if not engine.is_ready:
        response.status_code = 503
        return {"ready": False, "reason": "TTS engine not loaded"}

    if not voice_ok:
        response.status_code = 503
        return {"ready": False, "reason": "Voice sample not found"}

    return {"ready": True}


@router.get(
    "/health/live",
    summary="Liveness probe",
    description="Kubernetes liveness probe. Returns 200 if the service process is running.",
)
async def liveness() -> dict[str, bool]:
    """Kubernetes liveness probe endpoint."""
    return {"alive": True}


@router.get(
    "/health/detailed",
    summary="Detailed health",
    description="Returns detailed component-level health information for debugging.",
)
async def detailed_health() -> dict[str, Any]:
    """Detailed health check with component-level status."""
    engine = get_tts_engine()
    engine_status = {"is_ready": engine.is_ready}

    job_store = get_job_store()
    try:
        jobs_count = await job_store.count()
        job_store_status = {
            "type": job_store.storage_type,
            "connected": True,
            "jobs_count": jobs_count,
        }
    except Exception as exc:
        job_store_status = {
            "type": job_store.storage_type,
            "connected": False,
            "error": str(exc),
        }

    executor = get_executor()
    gcs_client = get_gcs_client()
    http_client = get_http_client()

    voice_path = Path(VOICE_SAMPLE_PATH)
    voice_exists = voice_path.exists()
    try:
        voice_size = voice_path.stat().st_size if voice_exists else 0
    except OSError:
        voice_size = 0
    voice_status = {
        "path": VOICE_SAMPLE_PATH,
        "exists": voice_exists,
        "size_bytes": voice_size,
    }

    is_healthy = engine_status.get("is_ready", False) and voice_status["exists"]

    return {
        "status": "healthy" if is_healthy else "degraded",
        "components": {
            "tts_engine": engine_status,
            "job_store": job_store_status,
            "executor": {"active": executor is not None, "max_workers": MAX_WORKERS},
            "gcs": {"enabled": gcs_client is not None},
            "http_client": {"enabled": http_client is not None},
            "voice_sample": voice_status,
        },
    }
