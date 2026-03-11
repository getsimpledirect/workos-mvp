"""
Core module for TTS service.

Contains the TTS engine wrapper and custom exceptions.
"""

from app.core.exceptions import (
    AudioProcessingError,
    GCSUploadError,
    JobAlreadyExistsError,
    JobNotFoundError,
    JobStoreError,
    NotificationError,
    StorageError,
    SynthesisError,
    TTSEngineError,
    TTSServiceError,
    ValidationError,
    VoiceSampleNotFoundError,
)

__all__ = [
    "AudioProcessingError",
    "GCSUploadError",
    "JobAlreadyExistsError",
    "JobNotFoundError",
    "JobStoreError",
    "NotificationError",
    "StorageError",
    "SynthesisError",
    "TTSEngineError",
    "TTSServiceError",
    "ValidationError",
    "VoiceSampleNotFoundError",
]
