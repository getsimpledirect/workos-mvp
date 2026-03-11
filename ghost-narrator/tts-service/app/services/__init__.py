"""
Service modules for TTS service.

Contains business logic services for job storage, synthesis,
audio processing, storage, and notifications.
"""

from app.services.audio import (
    concatenate_wavs,
    concatenate_wavs_auto,
    concatenate_wavs_streaming,
    get_audio_duration,
    get_file_size_mb,
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
    "concatenate_wavs",
    "concatenate_wavs_auto",
    "concatenate_wavs_streaming",
    "get_audio_duration",
    "get_file_size_mb",
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
