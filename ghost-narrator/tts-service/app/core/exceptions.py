"""
Custom exceptions for TTS service.

This module defines domain-specific exceptions that provide clear error
semantics throughout the application.
"""

from __future__ import annotations

from typing import Optional


class TTSServiceError(Exception):
    """Base exception for all TTS service errors."""

    def __init__(self, message: str, details: Optional[str] = None) -> None:
        self.message = message
        self.details = details
        super().__init__(self.message)

    def __str__(self) -> str:
        if self.details:
            return f"{self.message}: {self.details}"
        return self.message


class TTSEngineError(TTSServiceError):
    """Raised when the TTS engine fails to initialize or process audio."""

    pass


class SynthesisError(TTSServiceError):
    """Raised when audio synthesis fails for a text chunk."""

    pass


class AudioProcessingError(TTSServiceError):
    """Raised when audio concatenation or processing fails."""

    pass


class StorageError(TTSServiceError):
    """Raised when file storage operations fail (local or GCS)."""

    pass


class GCSUploadError(StorageError):
    """Raised when uploading to Google Cloud Storage fails."""

    def __init__(
        self, message: str, bucket: Optional[str] = None, path: Optional[str] = None
    ) -> None:
        self.bucket = bucket
        self.path = path
        details = f"bucket={bucket}, path={path}" if bucket or path else None
        super().__init__(message, details)


class JobNotFoundError(TTSServiceError):
    """Raised when a requested job does not exist."""

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        super().__init__(f"Job not found: {job_id}")


class JobAlreadyExistsError(TTSServiceError):
    """Raised when attempting to create a job that already exists."""

    def __init__(self, job_id: str, status: str) -> None:
        self.job_id = job_id
        self.status = status
        super().__init__(f"Job already exists with status: {status}")


class JobStoreError(TTSServiceError):
    """Raised when job store operations fail."""

    pass


class ValidationError(TTSServiceError):
    """Raised when input validation fails."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(message, details=f"field={field}")


class VoiceSampleNotFoundError(TTSServiceError):
    """Raised when the voice sample file is not available."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"Voice sample not found at {path}")


class NotificationError(TTSServiceError):
    """Raised when webhook notification fails."""

    def __init__(self, url: str, message: str) -> None:
        self.url = url
        super().__init__(message, details=f"url={url}")


class JobDeletedError(TTSServiceError):
    """Raised when a job is explicitly deleted while processing."""

    pass
