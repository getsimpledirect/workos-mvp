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
TTS API routes.

Endpoints for text-to-speech generation, job status, and audio download.
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Path as FastApiPath
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
        422: {
            "description": "Validation error (empty text, text too long, or invalid job_id)"
        },
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

    # Atomically check for existing job and create initial record
    job_store = get_job_store()
    initial_data = {
        "status": "queued",
        "gcs_uri": None,
        "local_path": None,
        "created_at": time.time(),
    }

    created = await job_store.create_if_not_exists(job_id, initial_data)

    if not created:
        existing_job = await job_store.get(job_id)
        existing_status = existing_job.get("status") if existing_job else None
        if existing_status in ("queued", "processing", "paused"):
            # Job is active — return the existing job rather than duplicating
            return GenerateResponse(job_id=job_id, status=existing_status)
        # Job is terminal (completed/failed/deleted) or missing — allow re-run
        await job_store.set(job_id, initial_data)

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
async def get_status(
    job_id: str = FastApiPath(..., pattern=r"^[a-zA-Z0-9_-]+$", max_length=200),
) -> StatusResponse:
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
async def download(
    job_id: str = FastApiPath(..., pattern=r"^[a-zA-Z0-9_-]+$", max_length=200),
) -> FileResponse:
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

    file_path = Path(local_path).resolve()
    if not str(file_path).startswith(str(OUTPUT_DIR.resolve())):
        raise HTTPException(
            status_code=400,
            detail="Invalid file path",
        )
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


@router.post(
    "/pause/{job_id}",
    response_model=StatusResponse,
    summary="Pause TTS job",
    description="Pause an active TTS job. Synthesis will stop after the current chunk.",
    responses={
        200: {"description": "Job paused"},
        404: {"description": "Job not found"},
        409: {"description": "Job already completed or failed"},
    },
)
async def pause_job(
    job_id: str = FastApiPath(..., pattern=r"^[a-zA-Z0-9_-]+$", max_length=200),
) -> StatusResponse:
    """Pause a TTS job."""
    job_store = get_job_store()
    job = await job_store.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    if job["status"] in ("completed", "failed"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot pause job in '{job['status']}' state",
        )

    await job_store.update(job_id, {"status": "paused"})
    logger.info(f"TTS job paused: {job_id}")

    updated_job = await job_store.get(job_id)
    return StatusResponse(job_id=job_id, **updated_job)


@router.post(
    "/resume/{job_id}",
    response_model=StatusResponse,
    summary="Resume TTS job",
    description="Resume a paused TTS job.",
    responses={
        200: {"description": "Job resumed"},
        404: {"description": "Job not found"},
        409: {"description": "Job not paused"},
    },
)
async def resume_job(
    job_id: str = FastApiPath(..., pattern=r"^[a-zA-Z0-9_-]+$", max_length=200),
) -> StatusResponse:
    """Resume a TTS job."""
    job_store = get_job_store()
    job = await job_store.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    if job["status"] != "paused":
        raise HTTPException(
            status_code=409, detail=f"Job is '{job['status']}', not 'paused'"
        )

    await job_store.update(job_id, {"status": "processing"})
    logger.info(f"TTS job resumed: {job_id}")

    updated_job = await job_store.get(job_id)
    return StatusResponse(job_id=job_id, **updated_job)


@router.delete(
    "/{job_id}",
    summary="Delete TTS job",
    description="Abort an active job and remove all associated files and records.",
    responses={
        200: {"description": "Job deleted and resources cleaned up"},
        404: {"description": "Job not found"},
    },
)
async def delete_job(
    job_id: str = FastApiPath(..., pattern=r"^[a-zA-Z0-9_-]+$", max_length=200),
) -> dict[str, Any]:
    """Delete a TTS job and cleanup resources."""
    job_store = get_job_store()
    job = await job_store.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    # 1. Update status to 'deleted' to signal the background worker to stop
    await job_store.update(job_id, {"status": "deleted"})

    # 2. Instantly kill any active synthesis processes
    from app.core.tts_engine import get_tts_engine

    get_tts_engine().cancel_job(job_id)

    logger.info(f"TTS job signal for deletion: {job_id}")

    # 3. Cleanup local files if they exist
    job_dir = OUTPUT_DIR / job_id
    final_mp3 = OUTPUT_DIR / f"{job_id}.mp3"
    raw_wav = OUTPUT_DIR / f"{job_id}_raw.wav"

    try:
        if job_dir.exists():
            import shutil

            shutil.rmtree(job_dir, ignore_errors=True)
        if final_mp3.exists():
            final_mp3.unlink(missing_ok=True)
        if raw_wav.exists():
            raw_wav.unlink(missing_ok=True)
    except Exception as exc:
        logger.warning(f"File cleanup during deletion failed for {job_id}: {exc}")

    # 3. Remove from job store
    await job_store.delete(job_id)

    return {"message": f"Job '{job_id}' and associated resources deleted"}


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
