import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core.exceptions import SynthesisError
from app.services.tts_job import run_tts_job


@pytest.fixture
def mock_job_store():
    with patch("app.services.tts_job.get_job_store") as mock_get_store:
        mock_store = AsyncMock()
        mock_get_store.return_value = mock_store
        yield mock_store


@pytest.fixture
def mock_tts_engine():
    with patch("app.services.tts_job.get_tts_engine") as mock_get_engine:
        mock_engine = MagicMock()
        mock_engine.is_ready = True
        mock_engine.synthesize_to_file.return_value = "/tmp/mock.wav"
        mock_get_engine.return_value = mock_engine
        yield mock_engine


@pytest.mark.asyncio
async def test_run_tts_job_success(mock_job_store, mock_tts_engine):
    mock_job_store.get.return_value = {"status": "processing"}

    job_id = "test-job-123"
    text = "Hello world. This is a test."
    gcs_path = "audio/test.mp3"

    # prepare_text_for_synthesis returns (chunks, total_words)
    with patch("app.services.tts_job.prepare_text_for_synthesis") as mock_prepare, \
         patch("app.services.tts_job.synthesize_chunks_auto") as mock_synth, \
         patch("app.services.tts_job.concatenate_wavs_auto") as mock_concat, \
         patch("app.services.tts_job.normalize_chunk_to_target_lufs", side_effect=lambda p, _: p), \
         patch("app.services.tts_job.apply_final_mastering", return_value=True), \
         patch("app.services.tts_job.validate_audio_quality", return_value=None), \
         patch("app.services.tts_job.get_gcs_client", return_value=None), \
         patch("app.services.tts_job.notify_job_completed", new_callable=AsyncMock), \
         patch("app.services.tts_job.get_executor") as mock_get_exec, \
         patch("app.services.tts_job.cleanup_chunk_files"), \
         patch.object(Path, "mkdir"), \
         patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "stat") as mock_stat:

        mock_stat.return_value.st_size = 1024 * 1024
        mock_get_exec.return_value = MagicMock()
        mock_prepare.return_value = (["Hello world.", "This is a test."], 6)
        mock_synth.return_value = ["/tmp/chunk_0000.wav"]
        mock_concat.return_value = None

        await run_tts_job(job_id, text, gcs_path)

        # Assert job store was updated to completed
        statuses = [
            call.args[1].get("status")
            for call in mock_job_store.update.call_args_list
            if isinstance(call.args[1], dict)
        ]
        assert "completed" in statuses


@pytest.mark.asyncio
async def test_run_tts_job_deleted_mid_process(mock_job_store, mock_tts_engine):
    # Simulate a job being deleted during processing
    mock_job_store.get.side_effect = [
        {"status": "processing"},  # engine ready check
        {"status": "deleted"},     # _check_status before chunking
    ]

    job_id = "test-job-deleted"
    text = "A very long text. " * 50
    gcs_path = "audio/deleted.mp3"

    with patch("app.services.tts_job.get_executor") as mock_get_exec, \
         patch.object(Path, "mkdir"):
        mock_get_exec.return_value = MagicMock()

        await run_tts_job(job_id, text, gcs_path)

        # Job was deleted — should never be marked completed
        statuses = [
            call.args[1].get("status")
            for call in mock_job_store.update.call_args_list
            if isinstance(call.args[1], dict)
        ]
        assert "completed" not in statuses


@pytest.mark.asyncio
async def test_run_tts_job_synthesis_failure(mock_job_store, mock_tts_engine):
    """Synthesis failure should mark job as failed with an error message."""
    mock_job_store.get.return_value = {"status": "processing"}

    job_id = "test-job-synth-fail"
    text = "Some text to synthesize."
    gcs_path = "audio/fail.mp3"

    with patch("app.services.tts_job.prepare_text_for_synthesis") as mock_prepare, \
         patch("app.services.tts_job.synthesize_chunks_auto") as mock_synth, \
         patch("app.services.tts_job.get_executor") as mock_get_exec, \
         patch("app.services.tts_job.notify_job_failed", new_callable=AsyncMock), \
         patch.object(Path, "mkdir"):

        mock_get_exec.return_value = MagicMock()
        mock_prepare.return_value = (["Some text to synthesize."], 4)
        mock_synth.side_effect = SynthesisError("GPU out of memory")

        await run_tts_job(job_id, text, gcs_path)

        statuses = [
            call.args[1].get("status")
            for call in mock_job_store.update.call_args_list
            if isinstance(call.args[1], dict)
        ]
        assert "failed" in statuses
        assert "completed" not in statuses


@pytest.mark.asyncio
async def test_run_tts_job_gcs_failure_still_completes(mock_job_store, mock_tts_engine):
    """GCS upload failure is non-fatal — job should still be marked completed."""
    mock_job_store.get.return_value = {"status": "processing"}

    job_id = "test-job-gcs-fail"
    text = "Hello world."
    gcs_path = "audio/gcs-fail.mp3"

    with patch("app.services.tts_job.prepare_text_for_synthesis") as mock_prepare, \
         patch("app.services.tts_job.synthesize_chunks_auto") as mock_synth, \
         patch("app.services.tts_job.concatenate_wavs_auto"), \
         patch("app.services.tts_job.normalize_chunk_to_target_lufs", side_effect=lambda p, _: p), \
         patch("app.services.tts_job.apply_final_mastering", return_value=True), \
         patch("app.services.tts_job.validate_audio_quality", return_value=None), \
         patch("app.services.tts_job.get_gcs_client", return_value=MagicMock()), \
         patch("app.services.tts_job.GCS_BUCKET_NAME", "my-bucket"), \
         patch("app.services.tts_job.upload_to_gcs", side_effect=Exception("Network error")), \
         patch("app.services.tts_job.notify_job_completed", new_callable=AsyncMock), \
         patch("app.services.tts_job.get_executor") as mock_get_exec, \
         patch("app.services.tts_job.cleanup_chunk_files"), \
         patch.object(Path, "mkdir"), \
         patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "stat") as mock_stat:

        mock_stat.return_value.st_size = 1024 * 1024
        mock_get_exec.return_value = MagicMock()
        mock_prepare.return_value = (["Hello world."], 2)
        mock_synth.return_value = ["/tmp/chunk_0000.wav"]

        await run_tts_job(job_id, text, gcs_path)

        # Job completes even when GCS fails
        statuses = [
            call.args[1].get("status")
            for call in mock_job_store.update.call_args_list
            if isinstance(call.args[1], dict)
        ]
        assert "completed" in statuses

        # The completed payload should include a GCS warning
        completed_updates = [
            call.args[1]
            for call in mock_job_store.update.call_args_list
            if isinstance(call.args[1], dict) and call.args[1].get("status") == "completed"
        ]
        assert any("gcs_upload_warning" in u for u in completed_updates)


@pytest.mark.asyncio
async def test_run_tts_job_executor_not_initialized(mock_job_store, mock_tts_engine):
    """Missing executor should fail the job immediately without raising."""
    mock_job_store.get.return_value = {"status": "processing"}

    job_id = "test-job-no-exec"
    text = "Hello world."
    gcs_path = "audio/no-exec.mp3"

    with patch("app.services.tts_job.get_executor", return_value=None), \
         patch.object(Path, "mkdir"):

        await run_tts_job(job_id, text, gcs_path)

        statuses = [
            call.args[1].get("status")
            for call in mock_job_store.update.call_args_list
            if isinstance(call.args[1], dict)
        ]
        assert "failed" in statuses
        assert "completed" not in statuses
