"""Small shared text-formatting helpers for the API and pipeline output.

The author asked for NO em/en dashes anywhere in the site or generated data.
Local models -- and Gemini especially -- love them, and prompt instructions are
unreliable, so we normalize at the storage/serving boundary instead of trusting
the model. Done here in one place so /api/bible, the report, and chat all agree.
"""

from __future__ import annotations

import re

# Em dash (U+2014) / en dash (U+2013), with any surrounding spaces, -> a single
# spaced hyphen. Collapsing the spaces means "word -- word" and "word--word"
# both become "word - word" rather than leaving stray double spaces.
_DASH_RE = re.compile(r"\s*[—–]\s*")


def dedash(text):
    """Replace em/en dashes with a spaced hyphen. None and "" pass through
    unchanged so callers can keep using `field or None` semantics."""
    if not text:
        return text
    return _DASH_RE.sub(" - ", text)


def dedash_deep(obj):
    """Recursively dedash every string in a JSON-like structure (dict/list/str),
    leaving non-strings (ints, bools, None) untouched."""
    if isinstance(obj, str):
        return dedash(obj)
    if isinstance(obj, dict):
        return {k: dedash_deep(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [dedash_deep(v) for v in obj]
    return obj
