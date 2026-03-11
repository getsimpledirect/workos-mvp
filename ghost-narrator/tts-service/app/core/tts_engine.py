"""
TTS Engine wrapper module.

Provides a singleton wrapper around the Coqui XTTS-v2 engine with proper
initialization, error handling, and thread-safe synthesis.
"""

from __future__ import annotations

import logging
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any, Optional

from app.config import DEVICE, TTS_LANGUAGE, VOICE_SAMPLE_PATH
from app.core.exceptions import SynthesisError, TTSEngineError, VoiceSampleNotFoundError

if TYPE_CHECKING:
    from TTS.api import TTS as CoquiTTS

logger = logging.getLogger(__name__)


class TTSEngine:
    """
    Thread-safe wrapper for Coqui XTTS-v2 TTS engine.

    This class manages the lifecycle of the TTS engine and provides
    methods for voice-cloning text-to-speech synthesis.
    """

    _instance: Optional["TTSEngine"] = None
    _lock: Lock = Lock()

    # Instance attributes (declared for type checking)
    _initialized: bool
    _engine: Optional[Any]  # CoquiTTS type at runtime
    _synthesis_lock: Lock
    _device: str
    _language: str
    _voice_sample_path: str

    def __new__(cls) -> "TTSEngine":
        """Ensure singleton instance of TTSEngine."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    instance._engine = None
                    instance._synthesis_lock = Lock()
                    instance._device = DEVICE
                    instance._language = TTS_LANGUAGE
                    instance._voice_sample_path = VOICE_SAMPLE_PATH
                    cls._instance = instance
        return cls._instance

    def __init__(self) -> None:
        """Initialize TTSEngine (only runs once due to singleton pattern)."""
        # All initialization is done in __new__ to avoid race conditions
        pass

    def initialize(self) -> None:
        """
        Load the XTTS-v2 model.

        Raises:
            TTSEngineError: If model loading fails.
        """
        if self._engine is not None:
            logger.debug("TTS engine already initialized")
            return

        logger.info(f"Loading XTTS-v2 on device={self._device}")

        try:
            from TTS.api import TTS as CoquiTTS

            self._engine = CoquiTTS("tts_models/multilingual/multi-dataset/xtts_v2").to(
                self._device
            )
            logger.info("XTTS-v2 ready")
        except ImportError as exc:
            raise TTSEngineError(
                "Failed to import TTS library",
                details="Ensure TTS package is installed correctly",
            ) from exc
        except Exception as exc:
            raise TTSEngineError(
                "Failed to load XTTS-v2 model",
                details=str(exc),
            ) from exc

    @property
    def is_ready(self) -> bool:
        """Check if the TTS engine is loaded and ready."""
        return self._engine is not None

    @property
    def device(self) -> str:
        """Get the device the engine is running on."""
        return self._device

    def validate_voice_sample(self) -> None:
        """
        Validate that the voice sample file exists.

        Raises:
            VoiceSampleNotFoundError: If voice sample is not found.
        """
        if not Path(self._voice_sample_path).exists():
            raise VoiceSampleNotFoundError(self._voice_sample_path)

    def synthesize_to_file(self, text: str, output_path: str) -> str:
        """
        Synthesize text to a WAV file using voice cloning.

        Args:
            text: The text to synthesize.
            output_path: Path where the WAV file will be saved.

        Returns:
            The output path of the generated WAV file.

        Raises:
            SynthesisError: If synthesis fails.
            VoiceSampleNotFoundError: If voice sample is not available.
        """
        if not text or not text.strip():
            raise SynthesisError("Cannot synthesize empty text")

        if self._engine is None:
            raise SynthesisError("TTS engine not initialized")

        self.validate_voice_sample()

        output_file = Path(output_path)

        with self._synthesis_lock:
            try:
                self._engine.tts_to_file(
                    text=text,
                    speaker_wav=self._voice_sample_path,
                    language=self._language,
                    file_path=output_path,
                )

                if not output_file.exists() or output_file.stat().st_size == 0:
                    raise SynthesisError(
                        "TTS engine failed to create valid output",
                        details=f"path={output_path}",
                    )

                return output_path

            except SynthesisError:
                raise
            except Exception as exc:
                if output_file.exists():
                    output_file.unlink(missing_ok=True)
                raise SynthesisError(
                    "TTS synthesis failed",
                    details=str(exc),
                ) from exc

    def get_status(self) -> dict:
        """
        Get the current status of the TTS engine.

        Returns:
            Dictionary containing engine status information.
        """
        return {
            "model": "xtts_v2",
            "device": self._device,
            "language": self._language,
            "is_ready": self.is_ready,
            "voice_sample_path": self._voice_sample_path,
            "voice_sample_exists": Path(self._voice_sample_path).exists(),
        }


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
    engine = get_tts_engine()
    engine.initialize()
    return engine
