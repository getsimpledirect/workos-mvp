"""
Utility modules for TTS service.

Contains helper functions for text processing and other utilities.
"""

from app.utils.text import get_pause_ms_after_chunk, split_into_chunks

__all__ = [
    "get_pause_ms_after_chunk",
    "split_into_chunks",
]
