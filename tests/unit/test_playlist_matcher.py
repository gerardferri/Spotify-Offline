from ytmp3studio.backend.playlist_matcher import PlaylistMatcher
from ytmp3studio.domain.models import SearchResult
import pytest


def result(title, channel="Artist - Topic", duration=200, **kwargs):
    return SearchResult("id", "https://youtube.test/id", title, channel, duration, **kwargs)


def test_prefers_exact_official_audio_with_matching_duration():
    matcher = PlaylistMatcher()
    decision = matcher.choose(
        "La Graciosa", "La canción", 200_000,
        [result("La canción (Live)", duration=260), result("La Graciosa - La canción (Official Audio)")],
    )
    assert decision.accepted
    assert decision.result.title.endswith("(Official Audio)")


def test_rejects_variant_not_present_in_spotify_title():
    matcher = PlaylistMatcher()
    decision = matcher.choose(
        "Artist", "Song", 200_000,
        [result("Song karaoke", channel="Karaoke Channel", duration=200)],
    )
    assert not decision.accepted


def test_allows_remix_when_it_is_in_original_title():
    matcher = PlaylistMatcher()
    decision = matcher.choose(
        "Artist", "Song remix", 200_000,
        [result("Artist - Song Remix (Official Audio)", duration=201)],
    )
    assert decision.accepted


def test_empty_results_returns_explainable_failure():
    decision = PlaylistMatcher().choose("Artist", "Song", None, [])
    assert decision.result is None
    assert not decision.accepted
    assert "No se encontraron" in decision.reason


@pytest.mark.parametrize(
    ("spotify_seconds", "ideal_tolerance"),
    [
        (180, 4),
        (181, 6),
        (480, 6),
        (481, 10),
    ],
)
def test_duration_uses_adaptive_ideal_tolerance(spotify_seconds, ideal_tolerance):
    matcher = PlaylistMatcher()
    exact = result("Artist - Song (Official Audio)", duration=spotify_seconds)
    boundary = result(
        "Artist - Song (Official Audio)",
        duration=spotify_seconds + ideal_tolerance,
    )
    outside = result(
        "Artist - Song (Official Audio)",
        duration=spotify_seconds + ideal_tolerance + 1,
    )

    exact_score = matcher.score("Artist", "Song", spotify_seconds * 1000, exact)
    boundary_score = matcher.score("Artist", "Song", spotify_seconds * 1000, boundary)
    outside_score = matcher.score("Artist", "Song", spotify_seconds * 1000, outside)

    assert boundary_score == exact_score
    assert outside_score < boundary_score


def test_duration_difference_over_twenty_seconds_is_not_accepted():
    decision = PlaylistMatcher().choose(
        "Artist",
        "Song",
        200_000,
        [result("Artist - Song (Official Audio)", duration=221)],
    )

    assert not decision.accepted


def test_duration_penalty_does_not_change_requested_variant_handling():
    decision = PlaylistMatcher().choose(
        "Artist",
        "Song remix",
        200_000,
        [result("Artist - Song Remix (Official Audio)", duration=204)],
    )

    assert decision.accepted
