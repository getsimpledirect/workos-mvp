"""
TTS Engine wrapper module for Fish Speech v1.5.

Provides a singleton wrapper for high-fidelity, studio-quality synthesis
using a LLaMA semantic model and Firefly (VQ-GAN) decoder.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from threading import Lock
from typing import Any, Optional

import torch
import whisper
from app.config import DEVICE, TTS_LANGUAGE, VOICE_SAMPLE_PATH
from app.core.exceptions import SynthesisError, TTSEngineError, VoiceSampleNotFoundError

logger = logging.getLogger(__name__)


class TTSEngine:
    """
    Thread-safe wrapper for Fish Speech v1.5 TTS engine.
    
    This engine uses:
    1. Whisper (Tiny) for auto-transcribing reference audio.
    2. LLaMA (1.4B) for semantic token generation.
    3. Firefly (VQ-GAN) for audio decoding.
    """

    _instance: Optional["TTSEngine"] = None
    _lock: Lock = Lock()

    def __new__(cls) -> "TTSEngine":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    instance._llama = None
                    instance._firefly = None  # Corrected from _vits
                    instance._tokenizer = None
                    instance._whisper_model = None
                    instance._synthesis_lock = Lock()
                    instance._device = DEVICE
                    instance._language = TTS_LANGUAGE
                    instance._voice_sample_path = VOICE_SAMPLE_PATH
                    instance._checkpoint_dir = Path("/app/checkpoints/fish-speech-1.5")
                    cls._instance = instance
        return cls._instance

    def initialize(self) -> None:
        """
        Load Fish Speech v1.5 models and calibrate reference voice.

        This method initializes the dual-model architecture (LLaMA + Firefly)
        and runs the automatic voice calibration using Whisper if needed.

        Raises:
            TTSEngineError: If model weights are missing or initialization fails.
        """
        if self._initialized:
            return

        with self._lock:
            if self._initialized:
                return

            try:
                logger.info(f"Initialising Fish Speech v1.5 on {self._device} (FP16)")
                
                # 1. Calibrate Reference Voice (Whisper)
                self._calibrate_reference_voice()

                # 2. Load Tokenizer & LLaMA (Semantic Model)
                from fish_speech.models.text_to_semantic.llama import LlamaForConditionalGeneration
                from transformers import AutoTokenizer

                logger.info("Loading LLaMA semantic model...")
                self._tokenizer = AutoTokenizer.from_pretrained(self._checkpoint_dir)
                self._llama = LlamaForConditionalGeneration.from_pretrained(
                    self._checkpoint_dir, 
                    device_map=self._device,
                    torch_dtype=torch.float16
                )
                self._llama.eval()

                # 3. Load Firefly (VQ-GAN Decoder)
                from fish_speech.models.vqgan.modules.firefly import Firefly
                
                logger.info("Loading Firefly decoder...")
                self._firefly = Firefly.from_pretrained(
                    self._checkpoint_dir,
                    device_map=self._device,
                    torch_dtype=torch.float16
                )
                self._firefly.eval()

                self._initialized = True
                logger.info("Fish Speech v1.5 engine ready (Studio Quality)")

            except Exception as exc:
                logger.error(f"Fish Speech initialization failed: {exc}")
                raise TTSEngineError("Failed to load Fish Speech v1.5", details=str(exc))

    def _calibrate_reference_voice(self) -> None:
        """
        Transcribe reference.wav to reference.txt if missing.

        Uses OpenAI Whisper (tiny) on CPU for minimal VRAM impact. The 
        transcribed text is saved alongside the reference audio to be 
        used as a semantic prompt for Fish Speech.

        Raises:
            VoiceSampleNotFoundError: If reference.wav is not found.
        """
        ref_path = Path(self._voice_sample_path)
        txt_path = ref_path.with_suffix(".txt")

        if not ref_path.exists():
            raise VoiceSampleNotFoundError(str(ref_path))

        if txt_path.exists():
            logger.info(f"Using existing reference text: {txt_path}")
            return

        logger.info(f"Calibrating reference voice (transcribing {ref_path.name})...")
        try:
            if self._whisper_model is None:
                # Use CPU for whisper to save VRAM for the main models if needed
                # tiny is extremely fast on CPU anyway
                self._whisper_model = whisper.load_model("tiny", device="cpu")
            
            result = self._whisper_model.transcribe(str(ref_path))
            text = result["text"].strip()
            
            if not text:
                logger.warning("Whisper transcribed empty text from reference audio")
                text = "Reference audio transcription pending."
            
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(text)
            
            logger.info(f"Calibration complete. Reference text saved to {txt_path.name}")
            
            # Cleanup
            del self._whisper_model
            self._whisper_model = None
                
        except Exception as exc:
            logger.warning(f"Voice calibration failed (non-fatal): {exc}")

    @property
    def is_ready(self) -> bool:
        """Check if the engine is initialized and ready for synthesis."""
        return self._initialized

    def synthesize_to_file(self, text: str, output_path: str) -> str:
        """
        Synthesize text using zero-shot cloning with explicit inference logic.

        This method performs the full inference pipeline:
        1. Load reference audio and transcription.
        2. Generate semantic tokens via LLaMA.
        3. Decode tokens to high-fidelity audio via Firefly.

        Args:
            text: The input text to synthesize.
            output_path: Target path for the generated WAV file.

        Returns:
            The absolute path to the generated synthesis output.

        Raises:
            SynthesisError: If synthesis fails or output is not generated.
        """
        if not self._initialized:
            raise SynthesisError("TTS engine not initialized")

        # Load reference text for prompt
        ref_txt_path = Path(self._voice_sample_path).with_suffix(".txt")
        prompt_text = ref_txt_path.read_text(encoding="utf-8") if ref_txt_path.exists() else ""

        with self._synthesis_lock:
            try:
                import torch
                import librosa
                import soundfile as sf
                
                logger.debug(f"Synthesizing '{text[:50]}...' using Fish Speech v1.5")
                
                # 1. Prepare Semantic Tokens
                # Standard Fish Speech 1.5 inference pattern
                from fish_speech.utils.schema import ServeReferenceAudio, ServeTTSRequest
                from fish_speech.inference import generate_audio_v1_5
                
                # Load reference at 44.1kHz (V1.5 Standard)
                audio, _ = librosa.load(self._voice_sample_path, sr=44100)
                
                # Wrap inference in inference_mode for VRAM efficiency and speed
                with torch.inference_mode():
                    generate_audio_v1_5(
                        llama=self._llama,
                        firefly=self._firefly,
                        tokenizer=self._tokenizer,
                        text=text,
                        prompt_text=prompt_text,
                        prompt_audio=audio,
                        output_path=output_path,
                        device=self._device,
                        decode_config=None 
                    )

                if not Path(output_path).exists():
                    raise SynthesisError("Fish Speech failed to produce output file")

                return output_path

            except Exception as exc:
                logger.error(f"Fish Speech synthesis failed: {exc}")
                raise SynthesisError("Studio-quality synthesis failed", details=str(exc))

    def get_status(self) -> dict[str, Any]:
        """
        Get current status and metadata of the TTS engine.

        Returns:
            A dictionary containing engine status, device, and capabilities.
        """
        return {
            "model": "fish-speech-1.5",
            "quality": "studio",
            "device": self._device,
            "is_ready": self._initialized,
            "voice_sample_path": self._voice_sample_path,
        }


def get_tts_engine() -> TTSEngine:
    return TTSEngine()


def initialize_tts_engine() -> TTSEngine:
    engine = get_tts_engine()
    engine.initialize()
    return engine
