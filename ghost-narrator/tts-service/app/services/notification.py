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
Notification service for webhook callbacks.

Provides functions for notifying external systems (like n8n) about
job completion status via HTTP webhooks with retry logic.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Optional

from app.config import MAX_RETRIES, N8N_CALLBACK_URL
from app.core.exceptions import NotificationError

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)

# Global HTTP client instance
_httpx_client: Optional["httpx.AsyncClient"] = None


def initialize_http_client() -> "httpx.AsyncClient":
    """
    Initialize the async HTTP client.

    Returns:
        The initialized httpx AsyncClient.

    Raises:
        NotificationError: If client initialization fails.
    """
    global _httpx_client

    try:
        import httpx

        from app.config import (
            HTTP_CONNECT_TIMEOUT,
            HTTP_TIMEOUT,
            MAX_CONNECTIONS,
            MAX_KEEPALIVE_CONNECTIONS,
        )

        _httpx_client = httpx.AsyncClient(
            timeout=httpx.Timeout(HTTP_TIMEOUT, connect=HTTP_CONNECT_TIMEOUT),
            limits=httpx.Limits(
                max_keepalive_connections=MAX_KEEPALIVE_CONNECTIONS,
                max_connections=MAX_CONNECTIONS,
            ),
        )
        logger.info("HTTP client initialized")
        return _httpx_client

    except ImportError as exc:
        raise NotificationError(
            url="",
            message="Failed to import httpx - ensure httpx package is installed",
        ) from exc
    except Exception as exc:
        raise NotificationError(
            url="",
            message=f"Failed to initialize HTTP client: {exc}",
        ) from exc


def get_http_client() -> Optional["httpx.AsyncClient"]:
    """
    Get the global HTTP client instance.

    Returns:
        The HTTP client if initialized, None otherwise.
    """
    return _httpx_client


def is_notification_enabled() -> bool:
    """
    Check if notifications are enabled.

    Returns:
        True if callback URL is configured and client is initialized.
    """
    return bool(N8N_CALLBACK_URL and _httpx_client is not None)


async def notify_n8n(
    job_id: str,
    status: str,
    gcs_uri: Optional[str] = None,
    error: Optional[str] = None,
    max_retries: int = MAX_RETRIES,
    callback_url: Optional[str] = None,
) -> bool:
    """
    POST job result back to n8n webhook with retry logic.

    Args:
        job_id: The unique job identifier.
        status: Job status (completed, failed, etc.).
        gcs_uri: Optional GCS URI if audio was uploaded.
        error: Optional error message if job failed.
        max_retries: Maximum number of retry attempts.
        callback_url: Optional override for the callback URL.

    Returns:
        True if notification was successful, False otherwise.

    Note:
        This function does not raise exceptions - it logs errors and
        returns False on failure to avoid disrupting the main workflow.
    """
    url = callback_url or N8N_CALLBACK_URL

    if not url:
        logger.debug("No callback URL configured - skipping notification")
        return True

    if not _httpx_client:
        logger.warning("HTTP client not initialized - skipping notification")
        return False

    payload = {
        "job_id": job_id,
        "status": status,
        "gcs_uri": gcs_uri,
        "error": error,
    }

    for attempt in range(max_retries):
        try:
            response = await _httpx_client.post(url, json=payload)
            response.raise_for_status()
            logger.info(f"Notified n8n for job {job_id} ({status})")
            return True

        except Exception as exc:
            if attempt < max_retries - 1:
                wait_time = min(2**attempt, 30)  # Exponential backoff capped at 30s
                logger.warning(
                    f"n8n callback failed for job {job_id} "
                    f"(attempt {attempt + 1}/{max_retries}): {exc}. "
                    f"Retrying in {wait_time}s..."
                )
                await asyncio.sleep(wait_time)
            else:
                logger.error(
                    f"n8n callback failed for job {job_id} "
                    f"after {max_retries} attempts: {exc}"
                )
                return False

    return False


async def notify_job_completed(
    job_id: str,
    gcs_uri: Optional[str] = None,
) -> bool:
    """
    Notify that a job completed successfully.

    Args:
        job_id: The unique job identifier.
        gcs_uri: Optional GCS URI where audio was uploaded.

    Returns:
        True if notification was successful.
    """
    return await notify_n8n(
        job_id=job_id,
        status="completed",
        gcs_uri=gcs_uri,
        error=None,
    )


async def notify_job_failed(
    job_id: str,
    error: str,
) -> bool:
    """
    Notify that a job failed.

    Args:
        job_id: The unique job identifier.
        error: Error message describing the failure.

    Returns:
        True if notification was successful.
    """
    # Truncate error message to prevent overly large payloads
    truncated_error = error[:500] if len(error) > 500 else error

    return await notify_n8n(
        job_id=job_id,
        status="failed",
        gcs_uri=None,
        error=truncated_error,
    )


async def close_http_client() -> None:
    """
    Close the HTTP client and cleanup resources.

    This should be called during application shutdown.
    """
    global _httpx_client

    if _httpx_client:
        try:
            await _httpx_client.aclose()
            logger.info("HTTP client closed")
        except Exception as exc:
            logger.error(f"Error closing HTTP client: {exc}")
        finally:
            _httpx_client = None
