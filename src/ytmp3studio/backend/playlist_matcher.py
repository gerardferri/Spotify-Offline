"""Deterministic ranking of YouTube search results for imported tracks."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import unicodedata

from ytmp3studio.domain.models import SearchResult


_NOISE = {
    "official", "audio", "video", "lyrics", "lyric", "hd", "hq",
    "topic", "provided", "youtube",
}
_VARIANTS = {
    "live", "remix", "remastered", "remaster", "karaoke", "cover",
    "instrumental", "slowed", "reverb", "sped", "nightcore", "acoustic",
}
_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class MatchDecision:
    result: SearchResult | None
    score: float
    accepted: bool
    reason: str


class PlaylistMatcher:
    """Choose a conservative result, preferring exact metadata and duration."""

    def __init__(self, minimum_score: float = 72.0) -> None:
        self.minimum_score = minimum_score

    @staticmethod
    def query(artist: str, title: str) -> str:
        # Keep the first pass deliberately literal: song name + performer.
        return f"{title.strip()} {artist.strip()}".strip()

    def choose(
        self,
        artist: str,
        title: str,
        duration_ms: int | None,
        results: list[SearchResult],
    ) -> MatchDecision:
        if not results:
            return MatchDecision(None, 0.0, False, "No se encontraron resultados.")
        ranked = sorted(
            ((self.score(artist, title, duration_ms, item), item) for item in results),
            key=lambda pair: pair[0],
            reverse=True,
        )
        score, result = ranked[0]
        accepted = score >= self.minimum_score
        reason = (
            "Coincidencia automática fiable."
            if accepted
            else f"La mejor coincidencia solo alcanzó {score:.0f}/100."
        )
        return MatchDecision(result, score, accepted, reason)

    def score(
        self,
        artist: str,
        title: str,
        duration_ms: int | None,
        result: SearchResult,
    ) -> float:
        target_title = _tokens(title)
        target_artist = _tokens(artist)
        candidate_title = _tokens(result.title) - _NOISE
        candidate_channel = _tokens(result.channel) - _NOISE

        title_score = _similarity(target_title, candidate_title)
        combined_artist = _similarity(
            target_artist, candidate_title | candidate_channel
        )
        score = 58.0 * title_score + 24.0 * combined_artist

        if duration_ms is not None and result.duration_seconds is not None:
            target_seconds = duration_ms / 1000.0
            delta = abs(target_seconds - result.duration_seconds)
            tolerance = _duration_tolerance(target_seconds)
            if delta <= tolerance:
                score += 18
            elif delta <= 20:
                # Outside the ideal window, fade the duration bonus until it
                # disappears at twenty seconds of difference.
                score += 12 * (20 - delta) / (20 - tolerance)
            else:
                # A difference this large usually means a music video intro,
                # an extended edit, or a different recording.  Even otherwise
                # exact metadata should not make it an automatic match.
                score -= 40 + min(20, (delta - 20) / 4)
        else:
            score += 5

        target_variants = (target_title | target_artist) & _VARIANTS
        unexpected = (candidate_title & _VARIANTS) - target_variants
        score -= 18 * len(unexpected)
        if result.is_live:
            score -= 50
        if result.availability and result.availability not in {"public", "unlisted"}:
            score -= 8
        return max(0.0, min(100.0, score))


def _duration_tolerance(target_seconds: float) -> int:
    """Return the ideal duration window for the Spotify track length."""
    if target_seconds <= 3 * 60:
        return 4
    if target_seconds <= 8 * 60:
        return 6
    return 10


def _tokens(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    folded = "".join(char for char in normalized if not unicodedata.combining(char))
    return set(_TOKEN_RE.findall(folded))


def _similarity(expected: set[str], actual: set[str]) -> float:
    if not expected or not actual:
        return 0.0
    overlap = len(expected & actual) / len(expected)
    sequence = SequenceMatcher(
        None, " ".join(sorted(expected)), " ".join(sorted(actual))
    ).ratio()
    return 0.75 * overlap + 0.25 * sequence
