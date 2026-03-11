"""
TTS API routes.

Endpoints for text-to-speech generation, job status, and audio download.
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException
from fastapi.responses import FileResponse

from app.config import (
    GCS_AUDIO_PREFIX,
    GCS_BUCKET_NAME,
    MAX_JOB_ID_LENGTH,
    MAX_TEXT_LENGTH,
    OUTPUT_DIR,
    VALID_JOB_ID_PATTERN,
    VOICE_SAMPLE_PATH,
)
from app.models.schemas import (
    GenerateRequest,
    GenerateResponse,
    JobListResponse,
    StatusResponse,
)
from app.services.job_store import get_job_store
from app.services.tts_job import run_tts_job

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tts", tags=["TTS"])


def _sanitize_job_id(job_id: str | None) -> str:
    """
    Sanitize and validate a job ID.

    Args:
        job_id: Optional custom job ID.

    Returns:
        A sanitized job ID or a new UUID if none provided.

    Raises:
        HTTPException: If job ID is invalid.
    """
    if not job_id:
        return str(uuid.uuid4())

    # Sanitize: strip, replace spaces, lowercase
    sanitized = job_id.strip().replace(" ", "-").lower()

    if len(sanitized) > MAX_JOB_ID_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"job_id exceeds maximum length of {MAX_JOB_ID_LENGTH} characters",
        )

    if not VALID_JOB_ID_PATTERN.match(sanitized):
        raise HTTPException(
            status_code=422,
            detail="job_id must contain only alphanumeric characters, hyphens, and underscores",
        )

    return sanitized


@router.post(
    "/generate",
    response_model=GenerateResponse,
    status_code=202,
    summary="Submit TTS job",
    description=(
        "Submit text for asynchronous speech synthesis. "
        "Returns immediately with a job ID to poll for status."
    ),
    responses={
        202: {"description": "Job accepted and queued for processing"},
        422: {"description": "Validation error (empty text, text too long, or invalid job_id)"},
        503: {"description": "Service unavailable (voice sample not configured)"},
    },
)
async def generate(
    background_tasks: BackgroundTasks,
    request: GenerateRequest = Body(
        ...,
        openapi_examples={
            "basic": {
                "summary": "Basic text synthesis",
                "description": "Simple text with custom job ID and site slug.",
                "value": {
                    "text": "Hello, this is a test of the text-to-speech system.",
                    "job_id": "article-12345",
                    "site_slug": "my-blog",
                },
            },
            "minimal": {
                "summary": "Minimal request",
                "description": "Only the required text field, all others use defaults.",
                "value": {
                    "text": "Welcome to our podcast. Today we discuss the latest trends in artificial intelligence and machine learning.",
                },
            },
            "full": {
                "summary": "Full request with custom GCS path",
                "description": "All fields populated including a custom GCS output path.",
                "value": {
                    "text": "Breaking news: Scientists have discovered a new species of deep-sea fish in the Pacific Ocean.",
                    "job_id": "news-2024-06-15-pacific-discovery",
                    "gcs_path": "audio/news/2024/06/pacific-discovery.mp3",
                    "site_slug": "news-daily",
                },
            },
        },
    ),
) -> GenerateResponse:
    """Submit a TTS job for background processing."""
    # Validate voice sample exists
    if not Path(VOICE_SAMPLE_PATH).exists():
        raise HTTPException(
            status_code=503,
            detail=f"Voice sample not found at {VOICE_SAMPLE_PATH}",
        )

    # Validate text is not empty
    if not request.text.strip():
        raise HTTPException(
            status_code=422,
            detail="Text must not be empty or whitespace-only",
        )

    # Validate text length
    if len(request.text) > MAX_TEXT_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Text exceeds maximum length of {MAX_TEXT_LENGTH} characters",
        )

    # Sanitize and validate job ID
    job_id = _sanitize_job_id(request.job_id)

    # Validate GCS path if provided
    if request.gcs_path:
        if ".." in request.gcs_path or request.gcs_path.startswith("/"):
            raise HTTPException(
                status_code=422,
                detail="gcs_path must not contain '..' or start with '/'",
            )

    # Check for existing job
    job_store = get_job_store()
    if await job_store.exists(job_id):
        existing_job = await job_store.get(job_id)
        if existing_job and existing_job.get("status") not in ("failed",):
            return GenerateResponse(
                job_id=job_id,
                status=existing_job["status"],
            )

    # Create initial job record
    await job_store.set(
        job_id,
        {
            "status": "queued",
            "gcs_uri": None,
            "local_path": None,
            "created_at": time.time(),
        },
    )

    # Build GCS object path
    gcs_object_path = request.gcs_path or (
        f"{GCS_AUDIO_PREFIX}/{request.site_slug}/{job_id}.mp3"
    )

    # Add job to background tasks
    background_tasks.add_task(
        run_tts_job,
        job_id,
        request.text,
        gcs_object_path,
    )

    logger.info(f"TTS job queued: {job_id}")

    return GenerateResponse(job_id=job_id, status="queued")


@router.get(
    "/status/{job_id}",
    response_model=StatusResponse,
    summary="Get job status",
    description="Retrieve the current status and metadata of a TTS job.",
    responses={
        200: {"description": "Job status retrieved"},
        404: {"description": "Job not found"},
    },
)
async def get_status(job_id: str) -> StatusResponse:
    """Get the status of a TTS job."""
    job_store = get_job_store()
    job_data = await job_store.get(job_id)

    if not job_data:
        raise HTTPException(
            status_code=404,
            detail=f"Job '{job_id}' not found",
        )

    return StatusResponse(job_id=job_id, **job_data)


@router.get(
    "/download/{job_id}",
    summary="Download audio",
    description="Download the generated MP3 file. Only available when job status is 'completed'.",
    responses={
        200: {"description": "Audio file (audio/mpeg)", "content": {"audio/mpeg": {}}},
        404: {"description": "Job not found"},
        409: {"description": "Job not completed"},
        410: {"description": "Audio file no longer available"},
    },
)
async def download(job_id: str) -> FileResponse:
    """Download the generated MP3 audio file."""
    job_store = get_job_store()
    job = await job_store.get(job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job '{job_id}' not found",
        )

    if job["status"] != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Job status is '{job['status']}', must be 'completed' to download",
        )

    local_path = job.get("local_path")
    if not local_path:
        raise HTTPException(
            status_code=410,
            detail="Audio file path not recorded",
        )

    file_path = Path(local_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=410,
            detail="Audio file no longer available",
        )

    try:
        file_size = file_path.stat().st_size
        if file_size == 0:
            raise HTTPException(
                status_code=500,
                detail="Audio file is empty",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error accessing file {local_path}: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Error accessing audio file",
        )

    return FileResponse(
        local_path,
        media_type="audio/mpeg",
        filename=f"{job_id}.mp3",
    )


@router.get(
    "/jobs",
    response_model=JobListResponse,
    summary="List all jobs",
    description="Retrieve all TTS jobs with their current status.",
    responses={
        200: {"description": "Job list retrieved"},
    },
)
async def list_jobs() -> JobListResponse:
    """List all TTS jobs."""
    job_store = get_job_store()
    jobs = await job_store.list_all()

    return JobListResponse(
        total=len(jobs),
        jobs=jobs,
    )
