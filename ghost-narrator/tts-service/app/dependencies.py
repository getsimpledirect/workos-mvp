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
Dependency injection module for FastAPI.

Provides dependency functions that can be injected into route handlers
to access services, configuration, and shared resources.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, Optional

from fastapi import Depends, HTTPException, status

from app.config import VOICE_SAMPLE_PATH
from app.core.tts_engine import TTSEngine, get_tts_engine
from app.services.job_store import JobStore, get_job_store
from app.services.notification import get_http_client
from app.services.storage import get_gcs_client, is_gcs_enabled
from app.services.synthesis import get_executor

if TYPE_CHECKING:
    import concurrent.futures
    from pathlib import Path

    import httpx
    from google.cloud import storage as gcs

logger = logging.getLogger(__name__)


# ============================================================================
# Service Dependencies
# ============================================================================


async def get_job_store_dependency() -> JobStore:
    """
    Dependency for accessing the job store service.

    Returns:
        The JobStore singleton instance.
    """
    return get_job_store()


def get_tts_engine_dependency() -> TTSEngine:
    """
    Dependency for accessing the TTS engine.

    Returns:
        The TTSEngine singleton instance.

    Raises:
        HTTPException: If TTS engine is not ready.
    """
    engine = get_tts_engine()

    if not engine.is_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TTS engine is not initialized",
        )

    return engine


def get_executor_dependency() -> "concurrent.futures.ThreadPoolExecutor":
    """
    Dependency for accessing the thread pool executor.

    Returns:
        The ThreadPoolExecutor instance.

    Raises:
        HTTPException: If executor is not initialized.
    """
    executor = get_executor()

    if executor is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Thread pool executor is not initialized",
        )

    return executor


def get_gcs_client_dependency() -> Optional["gcs.Client"]:
    """
    Dependency for accessing the GCS client.

    Returns:
        The GCS client if available, None otherwise.
    """
    return get_gcs_client()


def get_http_client_dependency() -> Optional["httpx.AsyncClient"]:
    """
    Dependency for accessing the HTTP client.

    Returns:
        The HTTP client if available, None otherwise.
    """
    return get_http_client()


# ============================================================================
# Validation Dependencies
# ============================================================================


def require_voice_sample() -> bool:
    """
    Dependency that validates the voice sample file exists.

    Returns:
        True if voice sample exists.

    Raises:
        HTTPException: If voice sample is not found.
    """
    from pathlib import Path

    if not Path(VOICE_SAMPLE_PATH).exists():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Voice sample not found at {VOICE_SAMPLE_PATH}. Mount voices/ directory.",
        )

    return True


def require_gcs_enabled() -> bool:
    """
    Dependency that validates GCS is enabled and configured.

    Returns:
        True if GCS is enabled.

    Raises:
        HTTPException: If GCS is not configured.
    """
    if not is_gcs_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GCS storage is not configured",
        )

    return True


def require_tts_ready() -> TTSEngine:
    """
    Dependency that validates the TTS engine is fully ready.

    This checks both the engine and voice sample availability.

    Returns:
        The ready TTSEngine instance.

    Raises:
        HTTPException: If TTS is not ready.
    """
    from pathlib import Path

    engine = get_tts_engine()

    if not engine.is_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TTS engine is not loaded",
        )

    if not Path(VOICE_SAMPLE_PATH).exists():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Voice sample not found at {VOICE_SAMPLE_PATH}",
        )

    return engine


# ============================================================================
# Type Aliases for Dependency Injection
# ============================================================================

# These can be used as type hints in route handlers for cleaner code

JobStoreDep = Annotated[JobStore, Depends(get_job_store_dependency)]
TTSEngineDep = Annotated[TTSEngine, Depends(get_tts_engine_dependency)]
ExecutorDep = Annotated[
    "concurrent.futures.ThreadPoolExecutor", Depends(get_executor_dependency)
]
VoiceSampleDep = Annotated[bool, Depends(require_voice_sample)]
TTSReadyDep = Annotated[TTSEngine, Depends(require_tts_ready)]


# ============================================================================
# Composite Dependencies
# ============================================================================


class ServiceContainer:
    """
    Container for commonly used services.

    This can be used to inject multiple services at once into a route handler.
    """

    def __init__(
        self,
        job_store: JobStore,
        tts_engine: TTSEngine,
    ) -> None:
        self.job_store = job_store
        self.tts_engine = tts_engine


async def get_service_container(
    job_store: JobStoreDep,
    tts_engine: TTSEngineDep,
) -> ServiceContainer:
    """
    Dependency for getting a container with common services.

    Args:
        job_store: The job store dependency.
        tts_engine: The TTS engine dependency.

    Returns:
        ServiceContainer with injected services.
    """
    return ServiceContainer(
        job_store=job_store,
        tts_engine=tts_engine,
    )


ServiceContainerDep = Annotated[ServiceContainer, Depends(get_service_container)]
