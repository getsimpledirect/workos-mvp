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
Synthesis service for TTS chunk processing.

Provides functions for synthesizing text chunks into audio files
with support for both sequential and parallel processing.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Optional

from app.config import DEVICE, MAX_CHUNK_WORDS
from app.core.exceptions import SynthesisError
from app.core.tts_engine import get_tts_engine
from app.utils.text import split_into_chunks

if TYPE_CHECKING:
    from app.core.tts_engine import TTSEngine

logger = logging.getLogger(__name__)

# Global executor instance
_executor: Optional[concurrent.futures.ThreadPoolExecutor] = None


def initialize_executor(max_workers: int) -> concurrent.futures.ThreadPoolExecutor:
    """
    Initialize the thread pool executor.

    Args:
        max_workers: Maximum number of worker threads.

    Returns:
        The initialized ThreadPoolExecutor.
    """
    global _executor

    _executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    logger.info(f"Thread pool executor initialized with {max_workers} workers")
    return _executor


def get_executor() -> Optional[concurrent.futures.ThreadPoolExecutor]:
    """
    Get the global executor instance.

    Returns:
        The executor if initialized, None otherwise.
    """
    return _executor


def shutdown_executor(wait: bool = True, cancel_futures: bool = True) -> None:
    """
    Shutdown the thread pool executor.

    Args:
        wait: Whether to wait for pending tasks to complete.
        cancel_futures: Whether to cancel pending futures.
    """
    global _executor

    if _executor:
        try:
            _executor.shutdown(wait=wait, cancel_futures=cancel_futures)
            logger.info("Thread pool executor shut down")
        except Exception as exc:
            logger.error(f"Error shutting down executor: {exc}")
        finally:
            _executor = None


def synthesize_chunk(text: str, output_path: str, job_id: str = "default") -> str:
    """
    Synthesize a single text chunk using Fish Speech v1.5 voice cloning.

    This is a synchronous function designed to run in a thread pool.

    Args:
        text: The text to synthesize.
        output_path: Path where the WAV file will be saved.
        job_id: Job identifier for process tracking.

    Returns:
        The output path of the generated WAV file.

    Raises:
        SynthesisError: If synthesis fails.
    """
    if not text or not text.strip():
        raise SynthesisError(
            "Cannot synthesize empty text",
            details=f"output_path={output_path}",
        )

    engine = get_tts_engine()
    return engine.synthesize_to_file(text, output_path, job_id)


async def synthesize_chunks_sequential(
    chunks: list[str],
    job_dir: Path,
    job_id: str,
    status_check_callback: Optional[Callable[[], Coroutine[Any, Any, None]]] = None,
) -> list[str]:
    """
    Synthesize multiple chunks sequentially.

    This method is preferred when running on GPU to avoid memory issues.

    Args:
        chunks: List of text chunks to synthesize.
        job_dir: Directory for output chunk files.
        job_id: Job identifier for logging.

    Returns:
        List of paths to generated WAV files.

    Raises:
        SynthesisError: If synthesis fails for any chunk.
    """
    if not chunks:
        raise SynthesisError("Cannot synthesize empty chunks list")

    if not _executor:
        raise SynthesisError(
            "Executor not initialized",
            details="Call initialize_executor() during startup",
        )

    loop = asyncio.get_running_loop()
    chunk_wav_paths: list[str] = []

    for idx, chunk in enumerate(chunks):
        # Check job status before each chunk
        if status_check_callback:
            await status_check_callback()

        chunk_wav = str(job_dir / f"chunk_{idx:04d}.wav")
        word_count = len(chunk.split())

        logger.info(
            f"[{job_id}] Synthesizing chunk {idx + 1}/{len(chunks)} "
            f"({word_count} words)"
        )

        try:
            wav_path = await loop.run_in_executor(
                _executor,
                synthesize_chunk,
                chunk,
                chunk_wav,
                job_id,
            )
            chunk_wav_paths.append(wav_path)
        except Exception as exc:
            raise SynthesisError(
                f"Sequential synthesis failed at chunk {idx + 1}",
                details=str(exc),
            ) from exc

    logger.info(f"[{job_id}] Sequential synthesis complete - {len(chunks)} chunks")
    return chunk_wav_paths


async def synthesize_chunks_parallel(
    chunks: list[str],
    job_dir: Path,
    job_id: str,
    status_check_callback: Optional[Callable[[], Coroutine[Any, Any, None]]] = None,
) -> list[str]:
    """
    Synthesize multiple chunks in parallel using thread pool.

    This method is preferred when running on CPU with multiple workers.

    Args:
        chunks: List of text chunks to synthesize.
        job_dir: Directory for output chunk files.
        job_id: Job identifier for logging.

    Returns:
        List of paths to generated WAV files (in order).

    Raises:
        SynthesisError: If synthesis fails for any chunk.
    """
    if not chunks:
        raise SynthesisError("Cannot synthesize empty chunks list")

    if not _executor:
        raise SynthesisError(
            "Executor not initialized",
            details="Call initialize_executor() during startup",
        )

    loop = asyncio.get_running_loop()

    # Check job status before starting batch
    if status_check_callback:
        await status_check_callback()

    tasks: list[asyncio.Future[str]] = []

    for idx, chunk in enumerate(chunks):
        chunk_wav = str(job_dir / f"chunk_{idx:04d}.wav")
        task = loop.run_in_executor(
            _executor, synthesize_chunk, chunk, chunk_wav, job_id
        )
        tasks.append(task)

    logger.info(f"[{job_id}] Starting parallel synthesis of {len(chunks)} chunks")

    try:
        chunk_wav_paths = await asyncio.gather(*tasks, return_exceptions=False)
        logger.info(f"[{job_id}] Parallel synthesis complete")
        return list(chunk_wav_paths)

    except Exception as exc:
        # Cancel any remaining tasks and wait for them to finish cancelling
        # to avoid "coroutine was never awaited" warnings and resource leaks.
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        raise SynthesisError(
            "Parallel synthesis failed",
            details=str(exc),
        ) from exc


async def synthesize_chunks_auto(
    chunks: list[str],
    job_dir: Path,
    job_id: str,
    device: Optional[str] = None,
    status_check_callback: Optional[Callable[[], Coroutine[Any, Any, None]]] = None,
) -> list[str]:
    """
    Automatically choose the best synthesis strategy based on device and chunk count.

    - CPU with multiple chunks: Use parallel synthesis
    - GPU or single chunk: Use sequential synthesis

    Args:
        chunks: List of text chunks to synthesize.
        job_dir: Directory for output chunk files.
        job_id: Job identifier for logging.
        device: Device type (cpu, cuda). Defaults to config DEVICE.

    Returns:
        List of paths to generated WAV files.

    Raises:
        SynthesisError: If synthesis fails.
    """
    current_device = device or DEVICE

    if current_device == "cpu" and len(chunks) > 1:
        logger.debug(
            f"[{job_id}] Using parallel synthesis for {len(chunks)} chunks on CPU"
        )
        return await synthesize_chunks_parallel(
            chunks, job_dir, job_id, status_check_callback
        )
    else:
        logger.debug(
            f"[{job_id}] Using sequential synthesis for {len(chunks)} chunks "
            f"on {current_device}"
        )
        return await synthesize_chunks_sequential(
            chunks, job_dir, job_id, status_check_callback
        )


def prepare_text_for_synthesis(
    text: str,
    max_chunk_words: int = MAX_CHUNK_WORDS,
) -> tuple[list[str], int]:
    """
    Prepare text for synthesis by splitting into chunks.

    Args:
        text: The full text to prepare.
        max_chunk_words: Maximum words per chunk.

    Returns:
        A tuple of (chunks, total_word_count).

    Raises:
        SynthesisError: If text is empty or chunking fails.
    """
    if not text or not text.strip():
        raise SynthesisError("Cannot prepare empty text for synthesis")

    chunks = split_into_chunks(text, max_chunk_words)

    if not chunks:
        raise SynthesisError(
            "Text chunking resulted in empty chunks",
            details=f"Original text length: {len(text)}",
        )

    total_words = sum(len(chunk.split()) for chunk in chunks)

    logger.debug(
        f"Prepared {len(chunks)} chunks with {total_words} total words "
        f"(max {max_chunk_words} words per chunk)"
    )

    return chunks, total_words


def cleanup_chunk_files(job_dir: Path, job_id: str) -> None:
    """
    Clean up temporary chunk WAV files.

    Args:
        job_dir: Directory containing chunk files.
        job_id: Job identifier for logging.
    """
    try:
        import shutil

        if job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)
            logger.debug(f"[{job_id}] Cleaned up chunk files in {job_dir}")
    except Exception as exc:
        logger.warning(f"[{job_id}] Failed to cleanup chunk files: {exc}")
