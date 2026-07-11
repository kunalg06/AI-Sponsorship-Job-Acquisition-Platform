"""Name normalization for matching UK sponsor register entries.

The register's raw ``Organisation Name`` column is messy: inconsistent
whitespace, trading-name suffixes ("... T/A ..."), and legal-form suffixes
(LTD, LIMITED, ...) that a pasted job posting's employer name usually won't
include. ``normalize_name`` produces a stable ``match_key`` so a name found
elsewhere (a job post, Companies House) can be looked up reliably.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TRADING_AS_RE = re.compile(r"\s+(?:t\s*/\s*a|trading\s+as)\s+", re.IGNORECASE)
_PUNCTUATION_RE = re.compile(r"[.,()]")
_WHITESPACE_RE = re.compile(r"\s+")

# Legal-form suffixes stripped from the end of a name when building a match
# key. Compared token-by-token (not substring) so "UNLIMITED" is never
# mistaken for "LIMITED".
_SUFFIX_TOKENS = {"LIMITED", "LTD", "LLP", "PLC", "LP", "CIC"}


@dataclass(frozen=True)
class NormalizedName:
    original: str
    legal_name: str
    trading_name: str | None
    match_key: str


def _clean_whitespace(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value.strip())


def _strip_suffix_tokens(tokens: list[str]) -> list[str]:
    tokens = list(tokens)
    while tokens and tokens[-1].upper() in _SUFFIX_TOKENS:
        tokens.pop()
    return tokens


def make_match_key(name: str) -> str:
    """Build a normalized lookup key: uppercase, no punctuation, no legal suffix."""
    cleaned = _clean_whitespace(_PUNCTUATION_RE.sub(" ", name))
    tokens = _strip_suffix_tokens(cleaned.split(" "))
    return _clean_whitespace(" ".join(tokens)).upper()


def normalize_name(raw_name: str) -> NormalizedName:
    """Split a raw register name into legal name / trading name and derive a match_key."""
    original = raw_name.strip()
    cleaned = _clean_whitespace(original)

    legal_name = cleaned
    trading_name: str | None = None

    parts = _TRADING_AS_RE.split(cleaned, maxsplit=1)
    if len(parts) == 2:
        legal_name, trading_name = _clean_whitespace(parts[0]), _clean_whitespace(parts[1])

    return NormalizedName(
        original=original,
        legal_name=legal_name,
        trading_name=trading_name or None,
        match_key=make_match_key(legal_name),
    )
