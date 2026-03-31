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
Service modules for TTS service.

Contains business logic services for job storage, synthesis,
audio processing, storage, and notifications.
"""

from app.services.audio import (
    apply_final_mastering,
    concatenate_wavs,
    concatenate_wavs_auto,
    concatenate_wavs_streaming,
    get_audio_duration,
    get_file_size_mb,
    normalize_chunk_to_target_lufs,
    validate_audio_quality,
)
from app.services.job_store import (
    JobStore,
    get_job_store,
    initialize_job_store,
)
from app.services.notification import (
    close_http_client,
    get_http_client,
    initialize_http_client,
    is_notification_enabled,
    notify_job_completed,
    notify_job_failed,
    notify_n8n,
)
from app.services.storage import (
    build_gcs_path,
    cleanup_gcs_client,
    get_gcs_client,
    get_public_url,
    initialize_gcs_client,
    is_gcs_enabled,
    upload_to_gcs,
)
from app.services.synthesis import (
    cleanup_chunk_files,
    get_executor,
    initialize_executor,
    prepare_text_for_synthesis,
    shutdown_executor,
    synthesize_chunk,
    synthesize_chunks_auto,
    synthesize_chunks_parallel,
    synthesize_chunks_sequential,
)
from app.services.tts_job import run_tts_job

__all__ = [
    # Audio processing
    "apply_final_mastering",
    "concatenate_wavs",
    "concatenate_wavs_auto",
    "concatenate_wavs_streaming",
    "get_audio_duration",
    "get_file_size_mb",
    "normalize_chunk_to_target_lufs",
    "validate_audio_quality",
    # Job store
    "JobStore",
    "get_job_store",
    "initialize_job_store",
    # Notifications
    "close_http_client",
    "get_http_client",
    "initialize_http_client",
    "is_notification_enabled",
    "notify_job_completed",
    "notify_job_failed",
    "notify_n8n",
    # Storage
    "build_gcs_path",
    "cleanup_gcs_client",
    "get_gcs_client",
    "get_public_url",
    "initialize_gcs_client",
    "is_gcs_enabled",
    "upload_to_gcs",
    # Synthesis
    "cleanup_chunk_files",
    "get_executor",
    "initialize_executor",
    "prepare_text_for_synthesis",
    "shutdown_executor",
    "synthesize_chunk",
    "synthesize_chunks_auto",
    "synthesize_chunks_parallel",
    "synthesize_chunks_sequential",
    # TTS Job
    "run_tts_job",
]
