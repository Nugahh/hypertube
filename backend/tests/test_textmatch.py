import pytest

from app import textmatch as tm


@pytest.mark.parametrize(
    "text, folded",
    [
        ("Amélie Poulain!", "amelie poulain"),
        ("  Chaplin's   “Modern Times” (1936)  ", "chaplin s modern times 1936"),
        ("Crâ & Féca", "cra feca"),
        ("", ""),
    ],
)
def test_folding_removes_accents_case_and_punctuation(text, folded):
    assert tm.fold(text) == folded
    assert tm.tokens(text) == folded.split()


@pytest.mark.parametrize(
    "a, b, d",
    [("chaplin", "chaplin", 0), ("chapliin", "chaplin", 1), ("chaplni", "chaplin", 1), ("kitten", "sitting", 3), ("", "abc", 3)],
)
def test_the_distance_counts_edits_and_swaps(a, b, d):
    assert tm.distance(a, b) == d


@pytest.mark.parametrize(
    "token, word, quality",
    [
        ("chaplin", "chaplin", 4),  # the same word
        ("chap", "chaplin", 3),  # what is being typed
        ("lin", "chaplin", 0),  # the middle of a word is not a match
        ("chapliin", "chaplin", 1),  # one typo
        ("chaplain", "chaplin", 1),
        ("bunni", "bunny", 1),
        ("cat", "car", 0),  # short words must be exact: one letter changes the meaning
        ("dictateur", "dictator", 1),
        ("zzzz", "chaplin", 0),
    ],
)
def test_one_word_against_another(token, word, quality):
    assert tm.word_quality(token, word) == quality


def test_every_word_of_the_query_must_match_a_word_of_the_text():
    title = tm.tokens("Big Buck Bunny 2008")
    assert tm.match_quality(["big", "buck"], title) == 4
    assert tm.match_quality(["bunny", "big"], title) == 4  # any order
    assert tm.match_quality(["big", "bunni"], title) == 1  # the weakest word decides
    assert tm.match_quality(["big", "chap"], title) == 0  # one word without a match: no match
    assert tm.match_quality([], title) == 0
    assert tm.match_quality(["chapliin"], tm.tokens("Charles Chaplin")) == 1
