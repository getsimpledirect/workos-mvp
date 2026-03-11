"""
TTS job runner service for background processing.

Provides the main job execution pipeline that orchestrates
text chunking, synthesis, audio concatenation, upload, and notifications.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from pathlib import Path
from typing import Optional

from app.config import DEVICE, GCS_BUCKET_NAME, MAX_CHUNK_WORDS, OUTPUT_DIR
from app.services.audio import concatenate_wavs_auto
from app.services.job_store import get_job_store
from app.services.notification import notify_job_completed, notify_job_failed
from app.services.storage import get_gcs_client, upload_to_gcs
from app.services.synthesis import (
    cleanup_chunk_files,
    get_executor,
    prepare_text_for_synthesis,
    synthesize_chunks_auto,
)

logger = logging.getLogger(__name__)


async def run_tts_job(
    job_id: str,
    text: str,
    gcs_object_path: str,
) -> None:
    """
    Execute the complete TTS pipeline with parallel processing and optimizations.

    This is the main background task that:
    1. Splits text into chunks
    2. Synthesizes each chunk to WAV
    3. Concatenates WAVs into a single MP3
    4. Uploads to GCS (if configured)
    5. Notifies webhook (if configured)
    6. Cleans up temporary files

    Args:
        job_id: Unique identifier for this job.
        text: The text to synthesize.
        gcs_object_path: GCS object path for upload.
    """
    start_time = time.time()
    loop = asyncio.get_event_loop()
    job_dir = OUTPUT_DIR / job_id
    final_mp3 = str(OUTPUT_DIR / f"{job_id}.mp3")
    job_store = get_job_store()
    executor = get_executor()

    # Validate executor is initialized
    if executor is None:
        logger.error(f"[{job_id}] Thread pool executor not initialized")
        await job_store.update(
            job_id,
            {
                "status": "failed",
                "error": "Service not properly initialized: executor unavailable",
                "completed_at": time.time(),
                "duration_seconds": 0,
            },
        )
        return

    # Create job directory
    try:
        job_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.error(f"[{job_id}] Failed to create job directory: {exc}")
        await job_store.update(
            job_id,
            {
                "status": "failed",
                "error": f"Directory creation failed: {exc}",
                "completed_at": time.time(),
                "duration_seconds": 0,
            },
        )
        return

    logger.info(f"[{job_id}] Job started - {len(text)} chars, device={DEVICE}")

    try:
        # Update status to processing
        await job_store.update(
            job_id,
            {
                "status": "processing",
                "started_at": start_time,
            },
        )

        # Step 1: Prepare text - split into chunks
        chunks, total_words = prepare_text_for_synthesis(text, MAX_CHUNK_WORDS)
        logger.info(
            f"[{job_id}] Chunking complete - {len(chunks)} chunks, {total_words} words"
        )

        # Step 2: Synthesize chunks to WAV files
        chunk_wav_paths = await synthesize_chunks_auto(
            chunks=chunks,
            job_dir=job_dir,
            job_id=job_id,
            device=DEVICE,
        )

        if not chunk_wav_paths:
            raise RuntimeError("No audio chunks were synthesized")

        # Step 3: Concatenate WAVs into single MP3
        try:
            await loop.run_in_executor(
                executor,
                concatenate_wavs_auto,
                chunk_wav_paths,
                final_mp3,
            )
        except Exception as exc:
            raise RuntimeError(f"Audio concatenation failed: {exc}") from exc

        # Verify MP3 was created
        if not Path(final_mp3).exists():
            raise RuntimeError("Final MP3 file was not created")

        mp3_size = Path(final_mp3).stat().st_size / (1024 * 1024)
        logger.info(f"[{job_id}] MP3 created ({mp3_size:.2f} MB)")

        # Step 4: Upload to GCS (if configured)
        gcs_uri: Optional[str] = None
        if GCS_BUCKET_NAME and gcs_object_path and get_gcs_client():
            try:
                gcs_uri = await loop.run_in_executor(
                    executor,
                    upload_to_gcs,
                    final_mp3,
                    gcs_object_path,
                )
            except Exception as exc:
                # GCS upload failure is non-fatal
                logger.error(f"[{job_id}] GCS upload failed (non-fatal): {exc}")
                gcs_uri = None

        # Step 5: Cleanup chunk directory
        cleanup_chunk_files(job_dir, job_id)

        # Calculate total duration
        total_duration = time.time() - start_time

        # Update job status to completed
        await job_store.update(
            job_id,
            {
                "status": "completed",
                "gcs_uri": gcs_uri,
                "local_path": final_mp3,
                "completed_at": time.time(),
                "duration_seconds": total_duration,
            },
        )

        logger.info(
            f"[{job_id}] ✓ Job completed in {total_duration:.1f}s "
            f"({total_words} words, {len(chunks)} chunks)"
        )

        # Step 6: Notify webhook
        await notify_job_completed(job_id, gcs_uri)

    except Exception as exc:
        duration = time.time() - start_time
        logger.error(
            f"[{job_id}] ✗ Job failed after {duration:.1f}s: {exc}",
            exc_info=True,
        )

        # Cleanup on failure
        _cleanup_failed_job(job_dir, final_mp3, job_id)

        # Update job status to failed
        error_message = str(exc)[:500]  # Truncate long error messages
        await job_store.update(
            job_id,
            {
                "status": "failed",
                "error": error_message,
                "completed_at": time.time(),
                "duration_seconds": duration,
            },
        )

        # Notify webhook of failure
        await notify_job_failed(job_id, error_message)


def _cleanup_failed_job(job_dir: Path, final_mp3: str, job_id: str) -> None:
    """
    Clean up resources after a failed job.

    Args:
        job_dir: Directory containing chunk files.
        final_mp3: Path to the (possibly partial) MP3 file.
        job_id: Job identifier for logging.
    """
    # Remove chunk directory
    try:
        shutil.rmtree(job_dir, ignore_errors=True)
    except Exception as cleanup_exc:
        logger.warning(f"[{job_id}] Cleanup failed: {cleanup_exc}")

    # Remove partial MP3 if it exists
    try:
        mp3_path = Path(final_mp3)
        if mp3_path.exists():
            mp3_path.unlink(missing_ok=True)
    except Exception as cleanup_exc:
        logger.warning(f"[{job_id}] Failed to remove partial MP3: {cleanup_exc}")
