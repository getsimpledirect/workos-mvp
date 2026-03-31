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
Pydantic schema models for API requests and responses.

Defines all data transfer objects (DTOs) for the TTS service API.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GenerateRequest(BaseModel):
    """Request payload for TTS synthesis."""

    text: str = Field(
        ...,
        min_length=1,
        max_length=100_000,
        description="Text to synthesize. Must be 1-100,000 characters and not whitespace-only.",
    )
    job_id: Optional[str] = Field(
        default=None,
        max_length=200,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Custom job ID. Must be alphanumeric with hyphens/underscores, max 200 chars. Auto-generated if omitted.",
    )
    gcs_path: Optional[str] = Field(
        default=None,
        description="Custom GCS output path. Must not contain '..' or start with '/'. Auto-generated if omitted.",
    )
    site_slug: Optional[str] = Field(
        default="site",
        max_length=100,
        description="Site identifier for GCS path generation. Defaults to 'site'.",
    )

    @field_validator("text")
    @classmethod
    def validate_text_not_empty(cls, value: str) -> str:
        """Validate text is not whitespace-only."""
        if not value.strip():
            raise ValueError("Text must not be empty or whitespace-only")
        return value

    @field_validator("gcs_path")
    @classmethod
    def validate_gcs_path(cls, value: Optional[str]) -> Optional[str]:
        """Validate GCS path has no path traversal. Empty string treated as None."""
        if value is not None:
            if not value.strip():
                return None
            if ".." in value or value.startswith("/"):
                raise ValueError("gcs_path must not contain '..' or start with '/'")
        return value


class GenerateResponse(BaseModel):
    """Response after submitting a TTS job."""

    job_id: str = Field(..., description="Unique job identifier.")
    status: str = Field(
        ..., description="Initial job status. Always 'queued' for new jobs."
    )


class StatusResponse(BaseModel):
    """Job status response."""

    model_config = ConfigDict(extra="ignore")

    job_id: str = Field(..., description="Unique job identifier.")
    status: str = Field(
        ...,
        description="Current status: queued, processing, paused, completed, or failed.",
    )
    gcs_uri: Optional[str] = Field(
        default=None, description="GCS URI when completed and GCS is enabled."
    )
    local_path: Optional[str] = Field(
        default=None, description="Server file path for download endpoint."
    )
    error: Optional[str] = Field(
        default=None, description="Error message when status is 'failed'."
    )
    created_at: Optional[float] = Field(
        default=None, description="Unix timestamp of job creation."
    )
    started_at: Optional[float] = Field(
        default=None, description="Unix timestamp when processing began."
    )
    completed_at: Optional[float] = Field(
        default=None, description="Unix timestamp of completion."
    )
    duration_seconds: Optional[float] = Field(
        default=None, description="Processing duration in seconds."
    )


class JobListResponse(BaseModel):
    """List of all jobs."""

    total: int = Field(..., ge=0, description="Total job count.")
    jobs: dict[str, dict[str, Any]] = Field(
        ..., description="Map of job_id to job data."
    )


class HealthResponse(BaseModel):
    """Service health status."""

    model_config = ConfigDict(protected_namespaces=())

    status: str = Field(..., description="Overall status: healthy or degraded.")
    device: str = Field(..., description="Compute device: cpu or cuda.")
    model: str = Field(..., description="TTS model name.")
    voice_sample: bool = Field(..., description="True if voice sample file exists.")
    model_loaded: bool = Field(..., description="True if TTS model is loaded.")
    job_store: str = Field(..., description="Storage backend: redis or memory.")
    jobs_count: int = Field(..., description="Job count, or -1 on error.")
    max_workers: int = Field(..., description="Max concurrent workers.")
    executor_active: bool = Field(..., description="True if executor is running.")
    gcs_client_active: bool = Field(..., description="True if GCS client is connected.")
    reference_audio_present: bool = Field(
        False, description="Voice reference audio exists in voices directory."
    )
    reference_tokens_present: bool = Field(
        False, description="Reference token file (reference_vq_tokens.npy) exists."
    )
    tts_engine_ready: bool = Field(False, description="TTSEngine reported ready.")


class ErrorResponse(BaseModel):
    """Error response."""

    detail: str = Field(..., description="Error message.")
    error_code: Optional[str] = Field(
        default=None, description="Machine-readable error code."
    )
