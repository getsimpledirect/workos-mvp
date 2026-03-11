"""
Audio processing service for TTS output.

Provides functions for concatenating WAV files into MP3 output
with optimizations for memory efficiency on large files.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Final

from pydub import AudioSegment

from app.config import INTER_CHUNK_PAUSE_MS, MP3_BITRATE, STREAMING_THRESHOLD_MS
from app.core.exceptions import AudioProcessingError

logger = logging.getLogger(__name__)

# Constants
DEFAULT_PAUSE_MS: Final[int] = INTER_CHUNK_PAUSE_MS
DEFAULT_BITRATE: Final[str] = MP3_BITRATE
STREAMING_THRESHOLD: Final[int] = STREAMING_THRESHOLD_MS


def validate_wav_files(wav_paths: list[str]) -> None:
    """
    Validate that all WAV files exist and are accessible.

    Args:
        wav_paths: List of paths to WAV files.

    Raises:
        AudioProcessingError: If any WAV file is missing or invalid.
    """
    if not wav_paths:
        raise AudioProcessingError("Cannot process empty WAV list")

    for wav_path in wav_paths:
        path = Path(wav_path)
        if not path.exists():
            raise AudioProcessingError(
                f"WAV file not found: {wav_path}",
                details="Ensure all chunk files were created successfully",
            )
        if path.stat().st_size == 0:
            raise AudioProcessingError(
                f"WAV file is empty: {wav_path}",
                details="TTS synthesis may have failed for this chunk",
            )


def concatenate_wavs(
    wav_paths: list[str],
    output_mp3: str,
    pause_ms: int = DEFAULT_PAUSE_MS,
    bitrate: str = DEFAULT_BITRATE,
) -> str:
    """
    Join all chunk WAVs into a single MP3 file with inter-chunk pauses.

    This function is optimized for smaller files (fewer than 10 chunks).
    For larger files, use `concatenate_wavs_streaming` instead.

    Args:
        wav_paths: List of paths to WAV files to concatenate.
        output_mp3: Output path for the resulting MP3 file.
        pause_ms: Duration of silence between chunks in milliseconds.
        bitrate: Output MP3 bitrate (e.g., "96k", "128k").

    Returns:
        The path to the created MP3 file.

    Raises:
        AudioProcessingError: If concatenation fails.
    """
    validate_wav_files(wav_paths)

    output_path = Path(output_mp3)

    try:
        logger.debug(f"Concatenating {len(wav_paths)} WAV files to {output_mp3}")

        combined = AudioSegment.empty()
        inter_chunk_pause = AudioSegment.silent(duration=pause_ms)

        for i, wav_path in enumerate(wav_paths):
            segment = AudioSegment.from_wav(wav_path)
            if i > 0:
                combined += inter_chunk_pause
            combined += segment

        combined.export(output_mp3, format="mp3", bitrate=bitrate)

        logger.debug(
            f"Successfully created MP3: {output_mp3} "
            f"({output_path.stat().st_size / (1024 * 1024):.2f} MB)"
        )

        return output_mp3

    except AudioProcessingError:
        raise
    except Exception as exc:
        if output_path.exists():
            output_path.unlink(missing_ok=True)
        raise AudioProcessingError(
            "WAV concatenation failed",
            details=str(exc),
        ) from exc


def concatenate_wavs_streaming(
    wav_paths: list[str],
    output_mp3: str,
    pause_ms: int = DEFAULT_PAUSE_MS,
    bitrate: str = DEFAULT_BITRATE,
    threshold_ms: int = STREAMING_THRESHOLD,
) -> str:
    """
    Join all chunk WAVs into a single MP3 file with streaming to reduce memory.

    This function periodically exports to a temporary file to avoid holding
    the entire audio in memory. Use this for larger files (10+ chunks).

    Args:
        wav_paths: List of paths to WAV files to concatenate.
        output_mp3: Output path for the resulting MP3 file.
        pause_ms: Duration of silence between chunks in milliseconds.
        bitrate: Output MP3 bitrate (e.g., "96k", "128k").
        threshold_ms: Memory threshold in milliseconds before flushing to disk.

    Returns:
        The path to the created MP3 file.

    Raises:
        AudioProcessingError: If concatenation fails.
    """
    validate_wav_files(wav_paths)

    output_path = Path(output_mp3)
    temp_path: str | None = None

    try:
        logger.debug(
            f"Streaming concatenation of {len(wav_paths)} WAV files to {output_mp3}"
        )

        inter_chunk_pause = AudioSegment.silent(duration=pause_ms)
        combined = AudioSegment.from_wav(wav_paths[0])

        for wav_path in wav_paths[1:]:
            combined += inter_chunk_pause
            segment = AudioSegment.from_wav(wav_path)
            combined += segment

            # If combined duration exceeds threshold, flush to disk
            if len(combined) > threshold_ms:
                temp_path = f"{output_mp3}.temp.{int(time.time())}.mp3"
                combined.export(temp_path, format="mp3", bitrate=bitrate)
                combined = AudioSegment.from_mp3(temp_path)
                os.remove(temp_path)
                temp_path = None

        combined.export(output_mp3, format="mp3", bitrate=bitrate)

        logger.debug(
            f"Successfully created MP3 (streaming): {output_mp3} "
            f"({output_path.stat().st_size / (1024 * 1024):.2f} MB)"
        )

        return output_mp3

    except AudioProcessingError:
        raise
    except Exception as exc:
        # Cleanup on failure
        if temp_path and Path(temp_path).exists():
            Path(temp_path).unlink(missing_ok=True)
        if output_path.exists():
            output_path.unlink(missing_ok=True)
        raise AudioProcessingError(
            "Streaming WAV concatenation failed",
            details=str(exc),
        ) from exc


def concatenate_wavs_auto(
    wav_paths: list[str],
    output_mp3: str,
    pause_ms: int = DEFAULT_PAUSE_MS,
    bitrate: str = DEFAULT_BITRATE,
    streaming_threshold_chunks: int = 10,
) -> str:
    """
    Automatically choose the best concatenation strategy based on input size.

    Uses standard concatenation for small files and streaming for larger ones.

    Args:
        wav_paths: List of paths to WAV files to concatenate.
        output_mp3: Output path for the resulting MP3 file.
        pause_ms: Duration of silence between chunks in milliseconds.
        bitrate: Output MP3 bitrate (e.g., "96k", "128k").
        streaming_threshold_chunks: Number of chunks above which to use streaming.

    Returns:
        The path to the created MP3 file.

    Raises:
        AudioProcessingError: If concatenation fails.
    """
    if len(wav_paths) > streaming_threshold_chunks:
        logger.debug(
            f"Using streaming concatenation for {len(wav_paths)} chunks "
            f"(threshold: {streaming_threshold_chunks})"
        )
        return concatenate_wavs_streaming(wav_paths, output_mp3, pause_ms, bitrate)
    else:
        logger.debug(f"Using standard concatenation for {len(wav_paths)} chunks")
        return concatenate_wavs(wav_paths, output_mp3, pause_ms, bitrate)


def get_audio_duration(file_path: str) -> float:
    """
    Get the duration of an audio file in seconds.

    Args:
        file_path: Path to the audio file (WAV or MP3).

    Returns:
        Duration in seconds.

    Raises:
        AudioProcessingError: If file cannot be read.
    """
    path = Path(file_path)
    if not path.exists():
        raise AudioProcessingError(f"Audio file not found: {file_path}")

    try:
        if path.suffix.lower() == ".wav":
            audio = AudioSegment.from_wav(file_path)
        elif path.suffix.lower() == ".mp3":
            audio = AudioSegment.from_mp3(file_path)
        else:
            raise AudioProcessingError(
                f"Unsupported audio format: {path.suffix}",
                details="Supported formats: .wav, .mp3",
            )

        return len(audio) / 1000.0  # Convert milliseconds to seconds

    except AudioProcessingError:
        raise
    except Exception as exc:
        raise AudioProcessingError(
            f"Failed to read audio file: {file_path}",
            details=str(exc),
        ) from exc


def get_file_size_mb(file_path: str) -> float:
    """
    Get the file size in megabytes.

    Args:
        file_path: Path to the file.

    Returns:
        File size in MB.

    Raises:
        AudioProcessingError: If file does not exist.
    """
    path = Path(file_path)
    if not path.exists():
        raise AudioProcessingError(f"File not found: {file_path}")

    return path.stat().st_size / (1024 * 1024)
