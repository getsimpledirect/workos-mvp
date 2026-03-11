"""
Text processing utilities for TTS service.

Provides functions for splitting text into optimal chunks for
TTS synthesis while maintaining sentence boundaries.
"""

from __future__ import annotations

import re
from typing import Final

# Default maximum words per chunk
DEFAULT_MAX_CHUNK_WORDS: Final[int] = 200

# Sentence boundary pattern
SENTENCE_BOUNDARY_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?<=[.!?])\s+")


def split_into_chunks(text: str, max_words: int = DEFAULT_MAX_CHUNK_WORDS) -> list[str]:
    """
    Split text into chunks at sentence boundaries for optimal TTS quality.

    This function intelligently splits text into manageable chunks by:
    1. Breaking at sentence boundaries (., !, ?)
    2. Respecting maximum word count per chunk
    3. Keeping sentences together when possible

    Args:
        text: The input text to split into chunks.
        max_words: Maximum number of words per chunk (default: 200).

    Returns:
        A list of text chunks, each suitable for TTS synthesis.
        Returns an empty list if input is empty/whitespace.

    Examples:
        >>> chunks = split_into_chunks("Hello world. How are you?", max_words=10)
        >>> len(chunks)
        1
        >>> chunks[0]
        'Hello world. How are you?'

        >>> long_text = "First sentence. " * 50
        >>> chunks = split_into_chunks(long_text, max_words=20)
        >>> all(len(c.split()) <= 25 for c in chunks)  # Some tolerance
        True
    """
    if not text or not text.strip():
        return []

    # Split into sentences at sentence boundaries
    sentences = SENTENCE_BOUNDARY_PATTERN.split(text.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        stripped = text.strip()
        return [stripped] if stripped else []

    chunks: list[str] = []
    current_sentences: list[str] = []
    current_word_count: int = 0

    for sentence in sentences:
        word_count = len(sentence.split())

        # Skip empty sentences
        if word_count == 0:
            continue

        # If adding this sentence exceeds max_words and we have content,
        # finalize the current chunk and start a new one
        if current_word_count + word_count > max_words and current_sentences:
            chunks.append(" ".join(current_sentences))
            current_sentences = [sentence]
            current_word_count = word_count
        else:
            current_sentences.append(sentence)
            current_word_count += word_count

    # Don't forget the last chunk
    if current_sentences:
        chunks.append(" ".join(current_sentences))

    # Fallback: if no chunks were created but we have text, return the whole text
    return chunks if chunks else [text.strip()]


def count_words(text: str) -> int:
    """
    Count the number of words in a text string.

    Args:
        text: The input text to count words in.

    Returns:
        The number of words in the text.
    """
    if not text or not text.strip():
        return 0
    return len(text.split())


def estimate_audio_duration(text: str, words_per_minute: int = 150) -> float:
    """
    Estimate the audio duration for a given text.

    Args:
        text: The input text to estimate duration for.
        words_per_minute: Average speaking rate (default: 150 WPM).

    Returns:
        Estimated duration in seconds.
    """
    word_count = count_words(text)
    return (word_count / words_per_minute) * 60


def sanitize_text(text: str) -> str:
    """
    Sanitize text for TTS synthesis.

    Performs basic text cleanup:
    - Removes excessive whitespace
    - Normalizes line breaks
    - Strips leading/trailing whitespace

    Args:
        text: The input text to sanitize.

    Returns:
        Sanitized text ready for TTS processing.
    """
    if not text:
        return ""

    # Normalize line breaks to spaces
    text = re.sub(r"[\r\n]+", " ", text)

    # Collapse multiple spaces into one
    text = re.sub(r"\s+", " ", text)

    # Strip leading/trailing whitespace
    text = text.strip()

    return text


def validate_text_length(text: str, max_length: int) -> tuple[bool, str]:
    """
    Validate that text does not exceed maximum length.

    Args:
        text: The input text to validate.
        max_length: Maximum allowed character length.

    Returns:
        A tuple of (is_valid, error_message).
        error_message is empty string if valid.
    """
    if not text:
        return False, "Text must not be empty"

    if not text.strip():
        return False, "Text must not be empty or whitespace only"

    if len(text) > max_length:
        return False, f"Text too long ({len(text)} chars). Max: {max_length}"

    return True, ""
