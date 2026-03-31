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
Text processing utilities for TTS service.

Provides functions for splitting text into optimal chunks for
TTS synthesis while maintaining sentence boundaries, and for
determining context-aware pause durations between chunks.
"""

from __future__ import annotations

import logging
import re
from typing import Final

logger = logging.getLogger(__name__)

# Default maximum words per chunk (40-60 words = 8-12 second audio segments)
DEFAULT_MAX_CHUNK_WORDS: Final[int] = 200

# Transition words that suggest a new topic/paragraph boundary
_TRANSITION_STARTERS: Final[tuple[str, ...]] = (
    "now,",
    "but ",
    "so ",
    "here",
    "this",
    "the ",
    "when",
    "if ",
    "what",
    "think",
    "there",
    "at the",
    "in the",
    "for ",
)


def split_into_chunks(text: str, max_words: int = DEFAULT_MAX_CHUNK_WORDS) -> list[str]:
    """
    Split narration text into TTS-optimal chunks.

    Strategy:
    - Split on paragraph boundaries first (double newline or sentence groups)
    - Within paragraphs, group sentences into chunks of ~40-60 words
    - Never split mid-sentence
    - Keep sentence-ending punctuation with its sentence (not the next chunk)
    - Chunks of 40-60 words produce 8-12 second audio segments — optimal for
      Fish Speech voice consistency and natural prosody

    Args:
        text: The input text to split into chunks.
        max_words: Maximum number of words per chunk (default: 50).

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

    # Normalize whitespace
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)

    # Split into paragraphs
    paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]

    chunks: list[str] = []

    for para in paragraphs:
        # Split paragraph into sentences using common sentence endings
        # Keep the punctuation with the sentence
        sentences = re.split(r"(?<=[.!?])\s+", para.strip())
        sentences = [s.strip() for s in sentences if s.strip()]

        current_chunk_words: list[str] = []
        current_word_count: int = 0

        for sentence in sentences:
            sentence_words = sentence.split()
            sentence_word_count = len(sentence_words)

            # Skip empty sentences
            if sentence_word_count == 0:
                continue

            # If adding this sentence exceeds max_words and we already have content,
            # flush current chunk and start a new one
            if (
                current_word_count + sentence_word_count > max_words
                and current_chunk_words
            ):
                chunks.append(" ".join(current_chunk_words))
                current_chunk_words = []
                current_word_count = 0

            current_chunk_words.extend(sentence_words)
            current_word_count += sentence_word_count

            # If this single sentence is already at/over the limit, flush immediately
            if current_word_count >= max_words:
                chunks.append(" ".join(current_chunk_words))
                current_chunk_words = []
                current_word_count = 0

        # Flush remaining words in this paragraph
        if current_chunk_words:
            chunks.append(" ".join(current_chunk_words))

    # Filter empty or trivially short chunks
    chunks = [c.strip() for c in chunks if c.strip()]

    if not chunks:
        # All content was filtered — return full text as one chunk and warn
        logger.warning(
            f"Text chunking produced no valid chunks for {len(text)}-char input; "
            "returning as single chunk (may exceed max_words limit)"
        )
        return [text.strip()]
    return chunks


def get_pause_ms_after_chunk(chunk: str, next_chunk: str | None) -> int:
    """
    Determine appropriate silence gap after this chunk.

    Returns milliseconds of silence to insert between audio chunks.
    - After a sentence ending a paragraph (next chunk starts a new topic): 700ms
    - After a sentence-ending chunk: 450ms
    - After a mid-sentence break: 250ms

    Args:
        chunk: The current chunk text.
        next_chunk: The next chunk text, or None if this is the last chunk.

    Returns:
        Silence duration in milliseconds.
    """
    if not next_chunk:
        return 0  # No trailing silence at end

    chunk_stripped = chunk.strip()

    # Paragraph-level break: current ends with sentence-final punctuation
    if (
        chunk_stripped.endswith(".")
        or chunk_stripped.endswith("!")
        or chunk_stripped.endswith("?")
    ):
        # Check if next chunk seems to be a new thought (starts with transition words)
        next_lower = next_chunk.lower().strip()
        if any(next_lower.startswith(t) for t in _TRANSITION_STARTERS):
            return 700  # Paragraph/topic boundary
        return 450  # Normal sentence boundary

    return 250  # Mid-thought break
