import pytest

from app import blender, jackett, tmdb
from tests.test_films import xml

# what TMDb says about the films of the feed (by their cleaned title); the open movies are all animation
GENRES = {
    "Heat": ["Crime", "Drama", "Action"],
    "Se7en": ["Crime", "Mystery", "Thriller"],
    "Chinatown": ["Crime", "Drama", "Mystery"],
    "Casablanca": ["Drama", "Romance", "War"],
    "Vertigo": ["Mystery", "Romance", "Thriller"],
}
SERIES = {  # TMDb files these under TV
    "Bonanza": ["Western", "Drama"],
    "Lassie": ["Family", "Drama"],
    "Gunsmoke": ["Western", "Drama"],
    "Perry Mason": ["Crime", "Drama"],
}
OPEN = {tmdb.clean_title(f["title"]) for f in blender.FILMS}
FEED = xml(
    ("Heat.1995.1080p.BluRay", "h", "Public One", 50),
    ("Se7en_1995", "s", "Public One", 40),
    ("Chinatown - 1974", "c", "Public One", 30),
    ("Casablanca 1942", "k", "Public One", 20),
    ("Vertigo.1958", "v", "Public One", 10),
)


SERIES_FEED = xml(
    ("Bonanza S01E01", "b1", "Public One", 9),
    ("Lassie.1954.S02", "l1", "Public One", 8),
    ("Gunsmoke - S01", "g1", "Public One", 7),
    ("Perry_Mason_S03", "p1", "Public One", 6),
)


@pytest.fixture
def rated(logged_in, monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "key")
    tmdb._retry_after.clear()
    asked = []

    async def lookup(title, year):
        name = tmdb.clean_title(title)
        asked.append(name)
        series = next((SERIES[n] for n in SERIES if name.startswith(n)), None)
        genres = series or GENRES.get(name) or (["Animation"] if name in OPEN else None)
        return {"tmdb_id": 1, "kind": "tv" if series else "movie", "genres": genres} if genres else None

    async def fetch(q, indexer=None):
        return SERIES_FEED if q == "collection:classic_tv" else FEED

    monkeypatch.setattr(tmdb, "lookup", lookup)
    monkeypatch.setattr(jackett, "fetch_xml", fetch)
    logged_in.asked = asked
    return logged_in


def test_the_fixed_genres_are_gone_except_the_popular_row_the_series_tab_and_the_open_movies():
    assert set(jackett.GENRES) == {"populaires", "blender", "series"}


def test_genres_come_from_what_tmdb_says_about_the_films_most_filled_first(rated):
    genres = rated.get("/api/genres").json()
    assert [(g["id"], g["label"], g["section"]) for g in genres] == [
        ("populaires", "Popular", "films"),
        ("blender", "Open movies", "films"),
        ("animation", "Animation", "films"),  # the nine open movies
        ("crime", "Crime", "films"),  # then three films each, by name
        ("drama", "Drama", "films"),
        ("mystery", "Mystery", "films"),
        ("series", "Classic TV series", "series"),
        ("series-drama", "Drama", "series"),  # the series have their own genres, apart from the films' (Western has two: no row)
    ]  # Romance and Thriller have two films: not enough for a row


def test_every_film_seen_is_looked_up_under_its_cleaned_name(rated):
    rated.get("/api/genres")
    assert {"Heat", "Se7en", "Chinatown", "Casablanca", "Vertigo"} <= set(rated.asked)  # dots, dashes, underscores, year, quality: gone


def test_a_genre_row_lists_the_films_that_have_the_genre(rated):
    rated.get("/api/genres")
    crime = rated.get("/api/search", params={"genre": "crime"}).json()
    assert [m["title"] for m in crime] == ["Heat.1995.1080p.BluRay", "Se7en_1995", "Chinatown - 1974"]  # most seeded first
    page = rated.get("/api/library", params={"genre": "drama"}).json()
    assert [m["title"] for m in page["items"]] == ["Heat.1995.1080p.BluRay", "Chinatown - 1974", "Casablanca 1942"] and page["total"] == 3


def test_a_series_genre_lists_the_series_that_have_it_and_never_the_films(rated):
    rated.get("/api/genres")
    series = rated.get("/api/search", params={"genre": "series-drama"}).json()
    assert [m["title"] for m in series] == ["Bonanza S01E01", "Lassie.1954.S02", "Gunsmoke - S01", "Perry_Mason_S03"]
    assert rated.get("/api/library", params={"genre": "series-drama"}).json()["total"] == 4
    assert len(rated.get("/api/library", params={"genre": "drama"}).json()["items"]) == 3  # the films' Drama has no series in it
    assert rated.get("/api/search", params={"genre": "series-nope"}).status_code == 404


def test_a_genre_without_a_row_can_still_be_asked_for(rated):
    rated.get("/api/genres")
    assert [m["title"] for m in rated.get("/api/search", params={"genre": "action"}).json()] == ["Heat.1995.1080p.BluRay"]


def test_a_genre_nobody_has_is_a_404(rated):
    rated.get("/api/genres")
    assert rated.get("/api/search", params={"genre": "nope"}).status_code == 404
    assert rated.get("/api/library", params={"genre": "nope"}).status_code == 404


def test_a_typed_search_can_be_narrowed_to_a_genre(rated):
    rated.get("/api/genres")
    found = lambda q, genre: [m["title"] for m in rated.get("/api/library", params={"q": q, "genre": genre}).json()["items"]]  # noqa: E731
    mystery = found("vertigo", "mystery")
    assert mystery[0] == "Vertigo.1958" and "Heat.1995.1080p.BluRay" not in mystery and "Casablanca 1942" not in mystery
    assert "Vertigo.1958" not in found("vertigo", "crime")  # the fake archive.org answers with every film whatever is typed


def test_a_film_a_search_brings_is_given_its_genre_by_tmdb_before_the_filter(rated, monkeypatch):
    rated.get("/api/genres")
    extra = xml(("Rififi 1955", "r", "Public One", 5))

    async def fetch(q, indexer=None):
        return extra

    monkeypatch.setattr(jackett, "fetch_xml", fetch)
    GENRES["Rififi"] = ["Crime"]
    try:
        items = rated.get("/api/library", params={"q": "rififi", "genre": "crime"}).json()["items"]
        assert "Rififi 1955" in [m["title"] for m in items]
    finally:
        del GENRES["Rififi"]


def test_without_a_tmdb_key_only_the_fixed_rows_remain(rated, monkeypatch):
    monkeypatch.delenv("TMDB_API_KEY")
    assert [g["id"] for g in rated.get("/api/genres").json()] == ["populaires", "blender", "series"]


def test_the_genre_list_is_closed_to_visitors(client):
    assert client.get("/api/genres").status_code == 401
