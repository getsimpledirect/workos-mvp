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
TTS job runner service for background processing.

Provides the main job execution pipeline that orchestrates
text chunking, synthesis, per-chunk normalization, audio
concatenation with dynamic gaps, final mastering, upload,
and notifications.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Optional

from pydub import AudioSegment as _AudioSegment

from app.core.exceptions import (
    JobDeletedError,
    SynthesisError,
    StorageError,
    AudioProcessingError,
    GCSUploadError,
)
from app.config import DEVICE, GCS_BUCKET_NAME, MAX_CHUNK_WORDS, OUTPUT_DIR
from app.services.audio import (
    apply_final_mastering,
    concatenate_wavs_auto,
    normalize_chunk_to_target_lufs,
    validate_audio_quality,
)
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

    This orchestrator manages:
    1. Status tracking via JobStore (Redis).
    2. Zero-shot voice calibration (Whisper).
    3. Multi-stage synthesis (LLaMA + Firefly).
    4. Audio post-processing (Normalization + Mastering).
    5. Cloud persistence (GCS) and external notifications (n8n).

    Args:
        job_id: Unique identifier for tracking and file storage.
        text: The raw text content to be synthesized.
        gcs_object_path: The target destination path in the GCS bucket.

    Raises:
        JobDeletedError: If the job is removed by a user during processing.
        RuntimeError: For fatal pipeline initialization or processing failures.
    """
    start_time = time.time()
    loop = asyncio.get_running_loop()
    job_dir = OUTPUT_DIR / job_id
    raw_wav = str(OUTPUT_DIR / f"{job_id}_raw.wav")
    final_mp3 = str(OUTPUT_DIR / f"{job_id}.mp3")
    job_store = get_job_store()
    executor = get_executor()

    async def _check_status() -> None:
        """Check if job is deleted or paused."""
        paused_iterations = 0
        max_paused_iterations = 1800  # 30 minutes max pause
        while True:
            job = await job_store.get(job_id)
            if not job or job.get("status") == "deleted":
                raise JobDeletedError(f"Job {job_id} was deleted")
            if job.get("status") == "paused":
                paused_iterations += 1
                if paused_iterations >= max_paused_iterations:
                    raise JobDeletedError(
                        f"Job {job_id} exceeded maximum pause duration"
                    )
                await asyncio.sleep(1)
                continue
            paused_iterations = 0  # Reset counter when job is no longer paused
            return

    # Track temp files for cleanup
    normalized_temp_files: list[str] = []

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

        # Wait for TTS engine to be ready (up to 60 seconds)
        engine_ready = False
        from app.core.tts_engine import get_tts_engine

        engine = get_tts_engine()
        for _ in range(60):
            if engine.is_ready:
                engine_ready = True
                break
            await asyncio.sleep(1)
            await _check_status()  # Still check if job was deleted while waiting

        if not engine_ready:
            raise RuntimeError("TTS engine failed to initialize within timeout")

        # Step 1: Prepare text - split into chunks
        await _check_status()
        chunks, total_words = prepare_text_for_synthesis(text, MAX_CHUNK_WORDS)
        logger.info(
            f"[{job_id}] Chunking complete - {len(chunks)} chunks, {total_words} words"
        )

        # Step 2: Synthesize chunks to WAV files
        await _check_status()
        # Use auto-selection for parallel (CPU) vs sequential (GPU)
        chunk_wav_paths = await synthesize_chunks_auto(
            chunks=chunks,
            job_dir=job_dir,
            job_id=job_id,
            status_check_callback=_check_status,
        )

        if not chunk_wav_paths:
            raise RuntimeError("No audio chunks were synthesized")

        # Step 3: Normalize all chunks to -23 LUFS (in parallel for speed)
        await _check_status()
        logger.info(
            f"[{job_id}] Normalizing {len(chunk_wav_paths)} chunks (parallel)..."
        )

        async def _normalize_one(i: int, wav_path: str) -> str:
            try:
                normalized_path = await loop.run_in_executor(
                    executor,
                    normalize_chunk_to_target_lufs,
                    wav_path,
                    -23.0,
                )
                if normalized_path != wav_path:
                    normalized_temp_files.append(normalized_path)
                return normalized_path
            except Exception as exc:
                logger.warning(
                    f"[{job_id}] Chunk {i} normalization failed, using original: {exc}"
                )
                return wav_path

        normalized_wav_paths = list(
            await asyncio.gather(
                *[_normalize_one(i, p) for i, p in enumerate(chunk_wav_paths)]
            )
        )

        logger.info(f"[{job_id}] Normalization complete")

        # Step 4: Concatenate WAVs with dynamic gaps into raw WAV
        await _check_status()
        try:
            await loop.run_in_executor(
                executor,
                concatenate_wavs_auto,
                normalized_wav_paths,
                raw_wav,
                chunks,  # Pass chunk texts for dynamic pause detection
            )
        except Exception as exc:
            raise RuntimeError(f"Audio concatenation failed: {exc}") from exc

        # Verify raw WAV was created
        if not Path(raw_wav).exists():
            raise RuntimeError("Raw WAV file was not created")

        raw_size = Path(raw_wav).stat().st_size / (1024 * 1024)
        logger.info(f"[{job_id}] Raw WAV created ({raw_size:.2f} MB)")

        # Step 5: Apply final mastering (-16 LUFS, 44.1kHz, 128kbps)
        await _check_status()
        logger.info(f"[{job_id}] Applying final mastering...")
        mastering_ok = await loop.run_in_executor(
            executor,
            apply_final_mastering,
            raw_wav,
            final_mp3,
        )

        mastering_used_fallback = False
        if not mastering_ok:
            # Fallback: use the raw MP3 if mastering fails
            logger.warning(f"[{job_id}] Mastering failed, falling back to raw export")
            # Fallback: export raw WAV to MP3 without mastering
            if Path(raw_wav).exists():
                seg = _AudioSegment.from_wav(raw_wav)
                seg.export(final_mp3, format="mp3", bitrate="128k")
                mastering_used_fallback = True

        # Verify final MP3 was created
        if not Path(final_mp3).exists():
            raise RuntimeError("Final MP3 file was not created")

        mp3_size = Path(final_mp3).stat().st_size / (1024 * 1024)
        logger.info(f"[{job_id}] Final MP3 created ({mp3_size:.2f} MB)")

        # Step 6: Quality validation (non-fatal, log only)
        try:
            quality = await loop.run_in_executor(
                executor,
                validate_audio_quality,
                final_mp3,
            )
            if quality:
                logger.info(f"[{job_id}] Quality metrics: {quality}")
        except Exception as exc:
            logger.warning(f"[{job_id}] Quality check failed (non-fatal): {exc}")

        # Step 7: Upload to GCS (if configured)
        await _check_status()
        gcs_uri: Optional[str] = None
        gcs_upload_failed = False
        if GCS_BUCKET_NAME and gcs_object_path and get_gcs_client():
            try:
                gcs_uri = await loop.run_in_executor(
                    executor,
                    upload_to_gcs,
                    final_mp3,
                    gcs_object_path,
                )
            except Exception as exc:
                # GCS upload failure is non-fatal — audio is still available locally
                logger.error(f"[{job_id}] GCS upload failed (non-fatal): {exc}")
                gcs_uri = None
                gcs_upload_failed = True

        # Step 8: Cleanup chunk directory and temp files
        cleanup_chunk_files(job_dir, job_id)
        _cleanup_temp_files(normalized_temp_files, job_id)
        _cleanup_intermediate(raw_wav, job_id)

        # Calculate total duration
        total_duration = time.time() - start_time

        # Update job status to completed
        completed_data: dict = {
            "status": "completed",
            "gcs_uri": gcs_uri,
            "local_path": final_mp3,
            "completed_at": time.time(),
            "duration_seconds": total_duration,
        }
        if mastering_used_fallback:
            completed_data["mastering_warning"] = (
                "Audio mastering failed; raw export used"
            )
        if gcs_upload_failed:
            completed_data["gcs_upload_warning"] = (
                "GCS upload failed; audio available locally only"
            )
        await job_store.update(job_id, completed_data)

        logger.info(
            f"[{job_id}] ✓ Job completed in {total_duration:.1f}s "
            f"({total_words} words, {len(chunks)} chunks)"
        )

        # Step 9: Notify webhook
        await notify_job_completed(job_id, gcs_uri)

    except (SynthesisError, StorageError, AudioProcessingError, GCSUploadError) as exc:
        duration = time.time() - start_time
        logger.error(
            f"[{job_id}] ✗ Job failed due to specific domain error after {duration:.1f}s: {exc}"
        )

        _cleanup_failed_job(job_dir, final_mp3, job_id)
        _cleanup_temp_files(normalized_temp_files, job_id)
        _cleanup_intermediate(raw_wav, job_id)

        error_name = exc.__class__.__name__
        error_msg = str(exc)[:450]

        await job_store.update(
            job_id,
            {
                "status": "failed",
                "error": f"{error_name}: {error_msg}",
                "completed_at": time.time(),
                "duration_seconds": duration,
            },
        )
        await notify_job_failed(job_id, f"{error_name}: {error_msg}")

    except Exception as exc:
        duration = time.time() - start_time
        logger.error(
            f"[{job_id}] ✗ Job failed after {duration:.1f}s: {exc}",
            exc_info=not isinstance(exc, JobDeletedError),
        )

        # Handle explicit deletion
        if isinstance(exc, JobDeletedError):
            logger.info(f"[{job_id}] Aborting job due to deletion")
            _cleanup_failed_job(job_dir, final_mp3, job_id)
            _cleanup_temp_files(normalized_temp_files, job_id)
            _cleanup_intermediate(raw_wav, job_id)
            return

        # Cleanup on failure
        _cleanup_failed_job(job_dir, final_mp3, job_id)
        _cleanup_temp_files(normalized_temp_files, job_id)
        _cleanup_intermediate(raw_wav, job_id)

        # Update job status to failed
        error_message = str(exc)[:450]  # Truncate long error messages
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


def _cleanup_temp_files(temp_files: list[str], job_id: str) -> None:
    """
    Clean up temporary normalized WAV files.

    Args:
        temp_files: List of temp file paths to remove.
        job_id: Job identifier for logging.
    """
    for temp_file in temp_files:
        try:
            if os.path.exists(temp_file):
                os.unlink(temp_file)
        except Exception as exc:
            logger.warning(f"[{job_id}] Failed to remove temp file {temp_file}: {exc}")


def _cleanup_intermediate(path: str, job_id: str) -> None:
    """
    Clean up an intermediate file (raw WAV or MP3).

    Args:
        path: Path to the intermediate file.
        job_id: Job identifier for logging.
    """
    try:
        if os.path.exists(path):
            os.unlink(path)
    except Exception as exc:
        logger.warning(f"[{job_id}] Failed to remove {path}: {exc}")
