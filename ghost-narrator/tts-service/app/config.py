"""
Application configuration module.

Centralizes all environment variables and application settings.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Final


# Voice and TTS settings
VOICE_SAMPLE_PATH: Final[str] = os.environ.get("VOICE_SAMPLE_PATH", "/app/voices/reference.wav")
TTS_LANGUAGE: Final[str] = os.environ.get("TTS_LANGUAGE", "en")
try:
    MAX_CHUNK_WORDS: Final[int] = max(10, min(int(os.environ.get("MAX_CHUNK_WORDS", "200")), 1000))
except ValueError:
    MAX_CHUNK_WORDS: Final[int] = 200
DEVICE: Final[str] = os.environ.get("DEVICE", "cuda")

# Google Cloud Storage settings
GCS_BUCKET_NAME: Final[str] = os.environ.get("GCS_BUCKET_NAME", "")
GCS_AUDIO_PREFIX: Final[str] = os.environ.get("GCS_AUDIO_PREFIX", "audio/articles")

# Webhook settings
N8N_CALLBACK_URL: Final[str] = os.environ.get("N8N_CALLBACK_URL", "")

# Worker and concurrency settings
try:
    MAX_WORKERS: Final[int] = max(1, min(int(os.environ.get("MAX_WORKERS", "4")), 32))
except ValueError:
    MAX_WORKERS: Final[int] = 4

# Redis settings
REDIS_URL: Final[str] = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
try:
    REDIS_JOB_TTL: Final[int] = max(60, min(int(os.environ.get("REDIS_JOB_TTL", "86400")), 604800))
except ValueError:
    REDIS_JOB_TTL: Final[int] = 86400

# Output directory
OUTPUT_DIR: Final[Path] = Path(os.environ.get("OUTPUT_DIR", "/app/output"))
try:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
except (PermissionError, OSError):
    pass  # Directory creation deferred to runtime; will fail clearly on first write

# Validation constants
MAX_TEXT_LENGTH: Final[int] = 100_000
VALID_JOB_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-zA-Z0-9_-]{1,200}$")
MAX_JOB_ID_LENGTH: Final[int] = 200

# Audio settings
MP3_BITRATE: Final[str] = "128k"
STREAMING_THRESHOLD_MS: Final[int] = 600_000

# HTTP client settings
HTTP_TIMEOUT: Final[float] = 10.0
HTTP_CONNECT_TIMEOUT: Final[float] = 5.0
MAX_KEEPALIVE_CONNECTIONS: Final[int] = 5
MAX_CONNECTIONS: Final[int] = 10

# Retry settings
MAX_RETRIES: Final[int] = 3

# GCS upload settings
GCS_UPLOAD_TIMEOUT: Final[int] = 300
