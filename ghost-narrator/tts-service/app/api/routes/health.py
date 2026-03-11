"""
Health check API routes.

Endpoints for service health monitoring, Kubernetes probes, and debugging.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter

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
    engine = get_tts_engine()
    model_ok = engine.is_ready
    is_healthy = voice_ok and model_ok

    jobs_count = -1
    try:
        job_store = get_job_store()
        jobs = await job_store.list_all()
        jobs_count = len(jobs)
    except Exception as exc:
        logger.error(f"Error listing jobs in health check: {exc}")

    executor = get_executor()
    gcs_client = get_gcs_client()
    job_store = get_job_store()

    return HealthResponse(
        status="healthy" if is_healthy else "degraded",
        device=DEVICE,
        model="xtts_v2",
        voice_sample=voice_ok,
        model_loaded=model_ok,
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
async def readiness() -> dict[str, Any]:
    """Kubernetes readiness probe endpoint."""
    engine = get_tts_engine()
    voice_ok = Path(VOICE_SAMPLE_PATH).exists()

    if not engine.is_ready:
        return {"ready": False, "reason": "TTS engine not loaded"}

    if not voice_ok:
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
    engine_status = engine.get_status()

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
    voice_status = {
        "path": VOICE_SAMPLE_PATH,
        "exists": voice_path.exists(),
        "size_bytes": voice_path.stat().st_size if voice_path.exists() else 0,
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
