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
TTS Engine wrapper module for Fish Speech v1.5.

Provides a singleton wrapper for high-fidelity, studio-quality synthesis
using Fish Speech v1.5's CLI-based inference pipeline.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from threading import Lock, Semaphore
from typing import Optional

import numpy as np
import soundfile as sf
import torch
from faster_whisper import WhisperModel
from app.config import (
    DEVICE,
    TTS_LANGUAGE,
    VOICE_SAMPLE_PATH,
    MAX_WORKERS,
    SEMANTIC_TOKEN_TIMEOUT,
    AUDIO_DECODE_TIMEOUT,
)
from app.core.exceptions import SynthesisError, TTSEngineError, VoiceSampleNotFoundError

logger = logging.getLogger(__name__)


class TTSEngine:
    """
    Thread-safe wrapper for Fish Speech v1.5 TTS engine.

    This engine uses Fish Speech v1.5's CLI-based inference:
    1. Whisper (Tiny) for auto-transcribing reference audio
    2. DAC codec for reference audio encoding (VQ tokens)
    3. Text2Semantic model for semantic token generation
    4. DAC decoder for final audio synthesis
    """

    _instance: Optional["TTSEngine"] = None
    _lock: Lock = Lock()

    def __new__(cls) -> "TTSEngine":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    instance._whisper_model = None
                    instance._synthesis_lock = Semaphore(
                        MAX_WORKERS if DEVICE == "cpu" else 1
                    )
                    instance._active_processes: dict[str, set[subprocess.Popen]] = {}
                    instance._process_lock = Lock()
                    instance._device = DEVICE
                    instance._language = TTS_LANGUAGE
                    instance._voice_sample_path = VOICE_SAMPLE_PATH
                    instance._checkpoint_dir = Path("/app/checkpoints/fish-speech-1.5")
                    instance._reference_tokens_path = None
                    instance._reference_text = None
                    cls._instance = instance
        return cls._instance

    def initialize(self) -> None:
        """
        Initialize Fish Speech v1.5 engine and calibrate reference voice.

        This method:
        1. Transcribes reference audio using Whisper
        2. Encodes reference audio to VQ tokens using Fish Speech DAC
        3. Validates checkpoint directory and models

        Raises:
            TTSEngineError: If model weights are missing or initialization fails.
        """
        if self._initialized:
            return

        with self._lock:
            if self._initialized:
                return

            try:
                logger.info(f"Initialising Fish Speech v1.5 on {self._device}")

                # 1. Validate checkpoint directory
                if not self._checkpoint_dir.exists():
                    raise TTSEngineError(
                        f"Checkpoint directory not found: {self._checkpoint_dir}",
                        details="Run model download during Docker build or manually download from HuggingFace",
                    )

                codec_path = (
                    self._checkpoint_dir
                    / "firefly-gan-vq-fsq-8x1024-21hz-generator.pth"
                )
                if not codec_path.exists():
                    # Try alternative codec name
                    codec_path = self._checkpoint_dir / "codec.pth"
                    if not codec_path.exists():
                        raise TTSEngineError(
                            f"Codec model not found in {self._checkpoint_dir}",
                            details="Expected firefly-gan-vq-fsq-8x1024-21hz-generator.pth or codec.pth",
                        )

                # 2. Calibrate Reference Voice (Whisper transcription)
                self._calibrate_reference_voice()

                # 3. Encode reference audio to VQ tokens
                self._encode_reference_audio(codec_path)

                self._initialized = True
                logger.info("Fish Speech v1.5 engine ready (Studio Quality)")

            except Exception as exc:
                logger.error(f"Fish Speech initialization failed: {exc}")
                raise TTSEngineError(
                    "Failed to load Fish Speech v1.5", details=str(exc)
                )

    def _calibrate_reference_voice(self) -> None:
        """
        Transcribe reference.wav to reference.txt if missing.

        Uses OpenAI Whisper (tiny) on CPU for minimal VRAM impact. The
        transcribed text is saved alongside the reference audio to be
        used as prompt for Fish Speech.

        Raises:
            VoiceSampleNotFoundError: If reference.wav is not found.
        """
        ref_path = Path(self._voice_sample_path)
        txt_path = ref_path.with_suffix(".txt")

        if not ref_path.exists():
            raise VoiceSampleNotFoundError(str(ref_path))

        if txt_path.exists():
            logger.info(f"Using existing reference text: {txt_path}")
            self._reference_text = txt_path.read_text(encoding="utf-8").strip()
            return

        logger.info(f"Calibrating reference voice (transcribing {ref_path.name})...")
        try:
            if self._whisper_model is None:
                # Use CPU for whisper to save VRAM for the main models
                self._whisper_model = WhisperModel(
                    "tiny", device="cpu", compute_type="int8"
                )

            try:
                segments, _ = self._whisper_model.transcribe(str(ref_path))
                text = " ".join([segment.text for segment in segments]).strip()

                if not text:
                    logger.warning(
                        "Whisper transcribed empty text from reference audio"
                    )
                    text = "Reference audio for voice cloning."

                txt_path.write_text(text, encoding="utf-8")
                self._reference_text = text

                logger.info(
                    f"Calibration complete. Reference text saved to {txt_path.name}"
                )
            finally:
                # Always free Whisper model memory regardless of success or failure
                del self._whisper_model
                self._whisper_model = None

        except Exception as exc:
            logger.warning(f"Voice calibration failed (non-fatal): {exc}")
            self._reference_text = "Reference audio for voice cloning."

    def _encode_reference_audio(self, codec_path: Path) -> None:
        """
        Encode reference audio to VQ tokens using Fish Speech DAC.

        Args:
            codec_path: Path to the DAC codec checkpoint

        Raises:
            TTSEngineError: If encoding fails
        """
        ref_path = Path(self._voice_sample_path)
        tokens_path = ref_path.parent / "reference_vq_tokens.npy"
        # Ensure the voices directory exists for artifacts
        voices_dir = ref_path.parent
        voices_dir.mkdir(parents=True, exist_ok=True)

        # Check if tokens already exist
        if tokens_path.exists():
            logger.info(f"Using existing reference tokens: {tokens_path}")
            self._reference_tokens_path = tokens_path
            return

        logger.info("Encoding reference audio to VQ tokens...")
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                # Run Fish Speech DAC inference to get VQ tokens
                cmd = [
                    "python",
                    "-m",
                    "tools.vqgan.inference",
                    "-i",
                    str(ref_path),
                    "--checkpoint-path",
                    str(codec_path),
                    "--device",
                    self._device,
                ]

                result = subprocess.run(
                    cmd, cwd=temp_dir, capture_output=True, text=True, timeout=60
                )

                if result.returncode != 0:
                    raise TTSEngineError(
                        "Reference audio encoding failed",
                        details=f"DAC inference error: {result.stderr}",
                    )

                # Mirror and move DAC output to tokens path safely across filesystems
                fake_npy = Path(temp_dir) / "fake.npy"
                if fake_npy.exists():
                    # Mirror for debugging/artifact visibility
                    artifact_path = voices_dir / "fake.npy"
                    if not artifact_path.exists():
                        try:
                            shutil.copy2(str(fake_npy), str(artifact_path))
                            logger.info(f"Mirrored DAC output to {artifact_path}")
                        except OSError:
                            pass
                    # Move to tokens path (reference_vq_tokens.npy) safely
                    try:
                        shutil.copy2(str(fake_npy), str(tokens_path))
                        self._reference_tokens_path = tokens_path
                        logger.info(
                            f"Reference tokens saved to {tokens_path} (fallback copy)"
                        )
                    except Exception as copy_exc:
                        raise TTSEngineError(
                            "Reference token file move failed",
                            details=f"Fallback copy failed: {copy_exc}",
                        )
                else:
                    raise TTSEngineError(
                        "Reference token file not generated",
                        details="Expected fake.npy output from DAC inference",
                    )

        except subprocess.TimeoutExpired:
            raise TTSEngineError("Reference audio encoding timed out (>60s)")
        except Exception as exc:
            logger.error(f"Reference audio encoding failed: {exc}")
            raise TTSEngineError("Failed to encode reference audio", details=str(exc))

    @property
    def is_ready(self) -> bool:
        """Check if the engine is initialized and ready for synthesis."""
        return self._initialized

    def cancel_job(self, job_id: str) -> None:
        """
        Instantly terminate all active subprocesses for a given job.

        Args:
            job_id: The job identifier to cancel.
        """
        with self._process_lock:
            processes = self._active_processes.pop(job_id, set())
            for proc in processes:
                try:
                    if proc.poll() is None:  # If still running
                        logger.info(f"[{job_id}] Terminating process {proc.pid}")
                        proc.terminate()
                        # Wait briefly for termination, then kill if necessary
                        try:
                            proc.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                except Exception as e:
                    logger.warning(f"[{job_id}] Error terminating process: {e}")

    def _register_process(self, job_id: str, proc: subprocess.Popen) -> None:
        """Register an active subprocess for tracking."""
        with self._process_lock:
            if job_id not in self._active_processes:
                self._active_processes[job_id] = set()
            self._active_processes[job_id].add(proc)

    def _unregister_process(self, job_id: str, proc: subprocess.Popen) -> None:
        """Unregister a finished subprocess."""
        with self._process_lock:
            if job_id in self._active_processes:
                self._active_processes[job_id].discard(proc)
                if not self._active_processes[job_id]:
                    del self._active_processes[job_id]

    def synthesize_to_file(
        self, text: str, output_path: str, job_id: str = "default"
    ) -> str:
        """
        Synthesize text using Fish Speech v1.5 CLI-based inference.

        This method performs the full inference pipeline:
        1. Generate semantic tokens from text (text2semantic)
        2. Decode tokens to high-fidelity audio (DAC decoder)

        Args:
            text: The input text to synthesize.
            output_path: Target path for the generated WAV file.
            job_id: Optional job identifier for process tracking.

        Returns:
            The absolute path to the generated synthesis output.

        Raises:
            SynthesisError: If synthesis fails or output is not generated.
        """
        if not self._initialized:
            raise SynthesisError("TTS engine not initialized")

        with self._synthesis_lock:
            try:
                logger.debug(
                    f"[{job_id}] Synthesizing '{text[:50]}...' using Fish Speech v1.5"
                )

                with tempfile.TemporaryDirectory() as temp_dir:
                    # Step 1: Generate semantic tokens from text
                    codes_path = self._generate_semantic_tokens(text, temp_dir, job_id)

                    # Step 2: Decode semantic tokens to audio
                    self._decode_to_audio(codes_path, output_path, temp_dir, job_id)

                if not Path(output_path).exists():
                    raise SynthesisError(
                        "Synthesis completed but output file was not created",
                        details=f"Expected output at: {output_path}",
                    )

                logger.info(f"Synthesis complete: {output_path}")
                return str(Path(output_path).absolute())

            except Exception as exc:
                if isinstance(exc, SynthesisError):
                    raise
                logger.error(f"Synthesis failed: {exc}")
                raise SynthesisError(f"Failed to synthesize audio: {str(exc)}")

    def _generate_semantic_tokens(
        self, text: str, cwd: str, job_id: str = "default"
    ) -> Path:
        """
        Generate semantic tokens from text using Fish Speech text2semantic model.

        Args:
            text: Input text to convert to semantic tokens
            cwd: The working directory for subprocess
            job_id: Job identifier for process tracking

        Returns:
            Path to the generated codes file

        Raises:
            SynthesisError: If semantic token generation fails
        """
        try:
            # Prepare command for text2semantic inference
            cmd = [
                "python",
                "-m",
                "tools.llama.generate",
                "--text",
                text,
                "--checkpoint-path",
                str(self._checkpoint_dir),
                "--device",
                self._device,
            ]

            # Add reference audio parameters for voice cloning
            if self._reference_tokens_path and self._reference_text:
                cmd.extend(
                    [
                        "--prompt-text",
                        self._reference_text,
                        "--prompt-tokens",
                        str(self._reference_tokens_path),
                    ]
                )

            logger.debug(f"[{job_id}] Running text2semantic: {' '.join(cmd)}")

            # Use Popen to allow for manual termination if job is deleted
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self._register_process(job_id, proc)
            try:
                stdout, stderr = proc.communicate(timeout=SEMANTIC_TOKEN_TIMEOUT)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate()
                raise SynthesisError(
                    f"Semantic token generation timed out (>{SEMANTIC_TOKEN_TIMEOUT}s)"
                )
            finally:
                self._unregister_process(job_id, proc)

            if proc.returncode != 0:
                raise SynthesisError(
                    "Semantic token generation failed",
                    details=f"text2semantic error: {stderr}",
                )

            # Find the generated codes file (codes_0.npy, codes_1.npy, etc.)
            codes_path = Path(cwd) / "codes_0.npy"
            if not codes_path.exists():
                raise SynthesisError(
                    "Semantic tokens file not generated",
                    details="Expected codes_0.npy output from text2semantic",
                )

            logger.debug(f"Semantic tokens generated: {codes_path}")
            return codes_path

        except Exception as exc:
            if isinstance(exc, SynthesisError):
                raise
            logger.error(f"Semantic token generation failed: {exc}")
            raise SynthesisError("Failed to generate semantic tokens", details=str(exc))

    def _decode_to_audio(
        self, codes_path: Path, output_path: str, cwd: str, job_id: str = "default"
    ) -> None:
        """
        Decode semantic tokens to audio using Fish Speech DAC decoder.

        Args:
            codes_path: Path to the semantic tokens file
            output_path: Target path for the audio file
            cwd: The working directory for subprocess
            job_id: Job identifier for process tracking

        Raises:
            SynthesisError: If audio decoding fails
        """
        try:
            codec_path = (
                self._checkpoint_dir / "firefly-gan-vq-fsq-8x1024-21hz-generator.pth"
            )
            if not codec_path.exists():
                codec_path = self._checkpoint_dir / "codec.pth"

            # Run DAC decoder
            cmd = [
                "python",
                "-m",
                "tools.vqgan.inference",
                "-i",
                str(codes_path),
                "--checkpoint-path",
                str(codec_path),
                "--device",
                self._device,
            ]

            logger.debug(f"[{job_id}] Running DAC decoder: {' '.join(cmd)}")

            # Use Popen to allow for manual termination
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self._register_process(job_id, proc)
            try:
                stdout, stderr = proc.communicate(timeout=AUDIO_DECODE_TIMEOUT)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate()
                raise SynthesisError(
                    f"Audio decoding timed out (>{AUDIO_DECODE_TIMEOUT}s)"
                )
            finally:
                self._unregister_process(job_id, proc)

            if proc.returncode != 0:
                raise SynthesisError(
                    "Audio decoding failed",
                    details=f"DAC decoder error: {stderr}",
                )

            # Move generated fake.wav to output_path
            fake_wav = Path(cwd) / "fake.wav"
            if fake_wav.exists():
                # Ensure output directory exists
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)

                # Use shutil.copy2 then unlink for cross-filesystem safety
                # rename() fails across Docker volumes with "Invalid cross-device link"
                try:
                    fake_wav.rename(output_path)
                except OSError:
                    # Cross-device link error - copy then delete instead
                    shutil.copy2(str(fake_wav), str(output_path))
                    fake_wav.unlink()

                logger.info(f"Audio decoded to: {output_path}")
            else:
                raise SynthesisError(
                    "Audio file not generated",
                    details="Expected fake.wav output from DAC decoder",
                )

        except Exception as exc:
            if isinstance(exc, SynthesisError):
                raise
            logger.error(f"Audio decoding failed: {exc}")
            raise SynthesisError("Failed to decode audio", details=str(exc))

    def __del__(self):
        """Cleanup resources on deletion."""
        if hasattr(self, "_whisper_model") and self._whisper_model is not None:
            del self._whisper_model


def get_tts_engine() -> TTSEngine:
    """
    Get the singleton TTSEngine instance.

    Returns:
        The TTSEngine singleton instance.
    """
    return TTSEngine()


def initialize_tts_engine() -> TTSEngine:
    """
    Initialize and return the TTS engine.

    This function should be called during application startup.

    Returns:
        The initialized TTSEngine instance.

    Raises:
        TTSEngineError: If initialization fails.
    """
    engine = TTSEngine()
    engine.initialize()
    return engine
