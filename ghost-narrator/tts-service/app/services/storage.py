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
Google Cloud Storage service for file uploads.

Provides functions for uploading generated audio files to GCS
with proper error handling and retry logic.
"""

from __future__ import annotations

import logging
from pathlib import Path
import concurrent.futures
from typing import TYPE_CHECKING, Optional

import time

from app.config import GCS_BUCKET_NAME, GCS_UPLOAD_TIMEOUT, MAX_RETRIES, OUTPUT_DIR
from app.core.exceptions import GCSUploadError, StorageError

if TYPE_CHECKING:
    from google.cloud import storage as gcs

logger = logging.getLogger(__name__)

# Global GCS client instance
_gcs_client: Optional["gcs.Client"] = None


def initialize_gcs_client() -> Optional["gcs.Client"]:
    """
    Initialize the GCS client.

    Returns:
        The GCS client if bucket is configured, None otherwise.

    Raises:
        StorageError: If client initialization fails.
    """
    global _gcs_client

    if not GCS_BUCKET_NAME:
        logger.info("GCS_BUCKET_NAME not configured - GCS uploads disabled")
        return None

    try:
        from google.cloud import storage as gcs

        _gcs_client = gcs.Client()
        logger.info(f"GCS client initialized for bucket: {GCS_BUCKET_NAME}")
        return _gcs_client

    except ImportError as exc:
        raise StorageError(
            "Failed to import google-cloud-storage",
            details="Ensure google-cloud-storage package is installed",
        ) from exc
    except Exception as exc:
        raise StorageError(
            "Failed to initialize GCS client",
            details=str(exc),
        ) from exc


def get_gcs_client() -> Optional["gcs.Client"]:
    """
    Get the global GCS client instance.

    Returns:
        The GCS client if initialized, None otherwise.
    """
    return _gcs_client


def is_gcs_enabled() -> bool:
    """
    Check if GCS uploads are enabled.

    Returns:
        True if GCS is configured and client is initialized.
    """
    return bool(GCS_BUCKET_NAME and _gcs_client is not None)


def validate_local_file(local_path: str) -> Path:
    """
    Validate that a local file exists and is not empty.

    Args:
        local_path: Path to the local file.

    Returns:
        Path object for the validated file.

    Raises:
        StorageError: If file is missing or empty.
    """
    path = Path(local_path).resolve()

    # Prevent path traversal — only files within OUTPUT_DIR may be uploaded
    if not str(path).startswith(str(OUTPUT_DIR.resolve())):
        raise StorageError(
            f"Upload path is outside the allowed output directory: {local_path}",
            details="Only files within OUTPUT_DIR can be uploaded",
        )

    if not path.exists():
        raise StorageError(
            f"Cannot upload non-existent file: {local_path}",
            details="Ensure the file was created successfully before upload",
        )

    if path.stat().st_size == 0:
        raise StorageError(
            f"Cannot upload empty file: {local_path}",
            details="The generated audio file has zero bytes",
        )

    return path


def upload_to_gcs(
    local_path: str,
    gcs_object_path: str,
    content_type: str = "audio/mpeg",
    timeout: int = GCS_UPLOAD_TIMEOUT,
) -> str:
    """
    Upload a file to Google Cloud Storage.

    Args:
        local_path: Path to the local file to upload.
        gcs_object_path: Destination path in GCS bucket.
        content_type: MIME type for the uploaded file.
        timeout: Upload timeout in seconds.

    Returns:
        The GCS URI (gs://bucket/path) of the uploaded file.

    Raises:
        GCSUploadError: If upload fails.
        StorageError: If GCS client is not initialized or file is invalid.
    """
    if not _gcs_client:
        raise StorageError(
            "GCS client not initialized",
            details="Call initialize_gcs_client() during startup",
        )

    path = validate_local_file(local_path)
    file_size = path.stat().st_size
    file_size_mb = file_size / (1024 * 1024)

    logger.debug(
        f"Uploading {local_path} ({file_size_mb:.2f} MB) to gs://{GCS_BUCKET_NAME}/{gcs_object_path}"
    )

    last_exc: Optional[Exception] = None
    for attempt in range(MAX_RETRIES):
        try:
            bucket = _gcs_client.bucket(GCS_BUCKET_NAME)
            blob = bucket.blob(gcs_object_path)

            blob.upload_from_filename(
                local_path,
                content_type=content_type,
                timeout=timeout,
            )

            gcs_uri = f"gs://{GCS_BUCKET_NAME}/{gcs_object_path}"
            logger.info(f"Uploaded to {gcs_uri} ({file_size_mb:.2f} MB)")
            return gcs_uri

        except Exception as exc:
            last_exc = exc
            if attempt < MAX_RETRIES - 1:
                wait_time = min(2**attempt, 30)
                logger.warning(
                    f"GCS upload attempt {attempt + 1}/{MAX_RETRIES} failed "
                    f"for {local_path}: {exc}. Retrying in {wait_time}s..."
                )
                time.sleep(wait_time)
            else:
                logger.error(
                    f"GCS upload failed after {MAX_RETRIES} attempts for {local_path}: {exc}"
                )

    raise GCSUploadError(
        f"Failed to upload to GCS after {MAX_RETRIES} attempts: {last_exc}",
        bucket=GCS_BUCKET_NAME,
        path=gcs_object_path,
    ) from last_exc


async def upload_to_gcs_async(
    local_path: str,
    gcs_object_path: str,
    executor: concurrent.futures.ThreadPoolExecutor,
    content_type: str = "audio/mpeg",
) -> str:
    """
    Upload a file to GCS asynchronously using a thread pool.

    Args:
        local_path: Path to the local file to upload.
        gcs_object_path: Destination path in GCS bucket.
        executor: Thread pool executor for running the upload.
        content_type: MIME type for the uploaded file.

    Returns:
        The GCS URI of the uploaded file.

    Raises:
        GCSUploadError: If upload fails.
    """
    import asyncio

    loop = asyncio.get_running_loop()

    return await loop.run_in_executor(
        executor,
        upload_to_gcs,
        local_path,
        gcs_object_path,
        content_type,
    )


def build_gcs_path(
    prefix: str,
    site_slug: str,
    job_id: str,
    extension: str = "mp3",
) -> str:
    """
    Build a GCS object path from components.

    Args:
        prefix: Base path prefix (e.g., "audio/articles").
        site_slug: Site identifier.
        job_id: Unique job identifier.
        extension: File extension without dot.

    Returns:
        Complete GCS object path.
    """
    # Clean up components
    prefix = prefix.strip("/")
    site_slug = site_slug.strip("/")
    job_id = job_id.strip("/")
    extension = extension.lstrip(".")

    return f"{prefix}/{site_slug}/{job_id}.{extension}"


def get_public_url(gcs_uri: str) -> str:
    """
    Convert a GCS URI to a public HTTPS URL.

    Note: The bucket must be configured for public access.

    Args:
        gcs_uri: GCS URI in format gs://bucket/path.

    Returns:
        Public HTTPS URL.

    Raises:
        ValueError: If URI format is invalid.
    """
    if not gcs_uri.startswith("gs://"):
        raise ValueError(f"Invalid GCS URI format: {gcs_uri}")

    # Remove gs:// prefix
    path = gcs_uri[5:]

    return f"https://storage.googleapis.com/{path}"


def cleanup_gcs_client() -> None:
    """
    Cleanup the GCS client.

    This should be called during application shutdown.
    """
    global _gcs_client

    if _gcs_client:
        try:
            _gcs_client.close()
            logger.info("GCS client closed")
        except Exception as exc:
            logger.error(f"Error closing GCS client: {exc}")
        finally:
            _gcs_client = None
