import pytest

from app import tmdb
from tests.test_movies import library, movie_id, sintel  # noqa: F401  (the sample library fixture)

SINTEL = {
    "tmdb_id": 45,
    "kind": "movie",
    "overview": "A girl searches for her dragon.",
    "runtime": 15,
    "rating": 7.5,
    "year": 2010,
    "poster": "https://image.tmdb.org/t/p/w500/p.jpg",
    "language": "en",
    "genres": ["Animation"],
    "directors": ["Colin Levy"],
    "producers": ["Ton Roosendaal"],
    "cast": ["Actor 0", "Actor 1"],
}


@pytest.fixture(autouse=True)
def fresh_pauses():
    tmdb._retry_after.clear()


@pytest.fixture
def tmdb_knows_sintel(monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "key")

    async def lookup(title, year):
        return SINTEL if "Sintel" in title else None

    monkeypatch.setattr(tmdb, "lookup", lookup)


def test_thumbnails_show_the_rating_and_the_tmdb_poster(library, tmdb_knows_sintel):  # noqa: F811
    movie = next(m for m in library.get("/api/search", params={"q": "sintel"}).json() if m["title"] == "Sintel.2010.720p")
    assert movie["rating"] == 7.5
    assert movie["cover"] == "https://image.tmdb.org/t/p/w500/p.jpg"


def test_without_tmdb_a_thumbnail_has_no_rating_and_no_cover(library):  # noqa: F811
    movie = next(m for m in library.get("/api/search").json() if m["title"] == "Sintel.2010.720p")
    assert movie["rating"] is None and movie["cover"] is None


def test_the_sheet_has_summary_casting_length_and_rating(library, tmdb_knows_sintel):  # noqa: F811
    detail = library.get(f"/api/movies/{sintel(library)}").json()
    assert detail["overview"] == "A girl searches for her dragon."
    assert (detail["runtime"], detail["rating"], detail["language"]) == (15, 7.5, "en")
    assert (detail["directors"], detail["producers"], detail["cast"], detail["genres"]) == (["Colin Levy"], ["Ton Roosendaal"], ["Actor 0", "Actor 1"], ["Animation"])


def test_the_sheet_of_an_unknown_movie_has_empty_info_not_errors(library):  # noqa: F811
    detail = library.get(f"/api/movies/{sintel(library)}").json()
    assert (detail["overview"], detail["runtime"], detail["rating"]) == (None, None, None)
    assert detail["cast"] == [] and detail["directors"] == []
