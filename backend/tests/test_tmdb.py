import asyncio

import httpx
import pytest
from sqlalchemy import select

from app import models, tmdb

SEARCH = {"results": [{"id": 45, "title": "Sintel"}]}
DETAILS = {
    "title": "Sintel",
    "overview": "A girl searches for her dragon.",
    "runtime": 15,
    "vote_average": 7.456,
    "vote_count": 900,
    "release_date": "2010-09-30",
    "poster_path": "/p.jpg",
    "original_language": "en",
    "genres": [{"name": "Animation"}, {"name": "Fantasy"}],
    "credits": {
        "cast": [{"name": f"Actor {i}"} for i in range(12)],
        "crew": [
            {"name": "Colin Levy", "job": "Director"},
            {"name": "Ton Roosendaal", "job": "Producer"},
            {"name": "Someone", "job": "Gaffer"},
        ],
    },
}


@pytest.fixture(autouse=True)
def fresh_pauses():
    tmdb._retry_after.clear()  # ids restart at 1 in every test database


@pytest.fixture
def api(monkeypatch):
    """A fake TMDb: `routes` maps a path to its JSON, `calls` records every request."""
    monkeypatch.setenv("TMDB_API_KEY", "0123456789abcdef0123456789abcdef")
    fake = type("Fake", (), {"routes": {"/search/movie": SEARCH, "/movie/45": DETAILS}, "calls": [], "status": 200})()

    def handler(request):
        fake.calls.append(request)
        if fake.status != 200:
            return httpx.Response(fake.status, json={})
        payload = fake.routes.get(request.url.path.removeprefix("/3"), {"results": []})
        return httpx.Response(200, json=payload(request) if callable(payload) else payload)

    monkeypatch.setattr(tmdb, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5))
    return fake


@pytest.mark.parametrize(
    "raw, clean",
    [
        ("Sintel.2010.720p", "Sintel"),
        ("Night of the Living Dead 1968", "Night of the Living Dead"),
        ("2001 A Space Odyssey 1968", "2001 A Space Odyssey"),
        ("Big_Buck_Bunny [1080p] (2008)", "Big Buck Bunny"),
        ("Metropolis", "Metropolis"),
    ],
)
def test_clean_title_keeps_only_the_name(raw, clean):
    assert tmdb.clean_title(raw) == clean


def test_lookup_normalizes_the_movie(api):
    info = asyncio.run(tmdb.lookup("Sintel 2010", 2010))
    assert info == {
        "tmdb_id": 45,
        "kind": "movie",
        "overview": "A girl searches for her dragon.",
        "runtime": 15,
        "rating": 7.5,
        "year": 2010,
        "poster": "https://image.tmdb.org/t/p/w500/p.jpg",
        "language": "en",
        "genres": ["Animation", "Fantasy"],
        "directors": ["Colin Levy"],
        "producers": ["Ton Roosendaal"],
        "cast": [f"Actor {i}" for i in range(8)],
    }
    search = api.calls[0]
    assert (search.url.params["query"], search.url.params["year"], search.url.params["api_key"]) == ("Sintel", "2010", "0123456789abcdef0123456789abcdef")


def test_a_read_access_token_goes_in_the_authorization_header(api, monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "eyJhbGciOi.token.value")
    asyncio.run(tmdb.lookup("Sintel", None))
    assert api.calls[0].headers["authorization"] == "Bearer eyJhbGciOi.token.value"
    assert "api_key" not in api.calls[0].url.params


def test_a_series_is_found_when_no_movie_matches(api):
    api.routes = {
        "/search/tv": {"results": [{"id": 7}]},
        "/tv/7": {"name": "Dragnet", "overview": "Cops.", "episode_run_time": [30], "vote_average": 0, "vote_count": 0,
                  "first_air_date": "1951-12-16", "poster_path": None, "original_language": "en",
                  "created_by": [{"name": "Jack Webb"}], "credits": {"cast": [], "crew": []}},
    }
    info = asyncio.run(tmdb.lookup("Dragnet", None))
    assert (info["kind"], info["runtime"], info["year"], info["directors"]) == ("tv", 30, 1951, ["Jack Webb"])
    assert info["rating"] is None and info["poster"] is None  # an unrated title has no rating, not 0


def test_nothing_found_is_none_and_a_provider_error_is_an_error(api):
    api.routes = {}
    assert asyncio.run(tmdb.lookup("Zzzz", None)) is None
    api.status = 500
    with pytest.raises(tmdb.TmdbError):
        asyncio.run(tmdb.lookup("Sintel", None))


def test_without_a_key_nothing_is_asked(monkeypatch, api):
    monkeypatch.setenv("TMDB_API_KEY", "")
    assert asyncio.run(tmdb.lookup("Sintel", None)) is None and api.calls == []


def _movies(session_factory, *titles):
    with session_factory() as s:
        rows = [models.Movie(source_id=t, title=t, size=1, seeders=1, peers=1, provider="p", link="l", status="idle") for t in titles]
        s.add_all(rows)
        s.commit()
        return [r.id for r in rows]


def test_enrich_stores_the_info_once(api, session_factory):
    [mid] = _movies(session_factory, "Sintel 2010")
    with session_factory() as s:
        asyncio.run(tmdb.enrich(s, [s.get(models.Movie, mid)]))
        asyncio.run(tmdb.enrich(s, [s.get(models.Movie, mid)]))
        info = s.get(models.MovieInfo, mid)
        assert (info.tmdb_id, info.rating, info.cast[0]) == (45, 7.5, "Actor 0")
    assert len(api.calls) == 2  # search + details, once


def test_enrich_remembers_that_nothing_was_found(api, session_factory):
    api.routes = {}
    [mid] = _movies(session_factory, "Zzzz")
    with session_factory() as s:
        asyncio.run(tmdb.enrich(s, [s.get(models.Movie, mid)]))
        asyncio.run(tmdb.enrich(s, [s.get(models.Movie, mid)]))
        assert s.get(models.MovieInfo, mid).tmdb_id is None
    assert len(api.calls) == 2  # movie + tv search, once


def test_enrich_survives_a_provider_error_and_tries_again_later(api, session_factory, monkeypatch):
    [mid] = _movies(session_factory, "Sintel 2010")
    api.status = 500
    with session_factory() as s:
        asyncio.run(tmdb.enrich(s, [s.get(models.Movie, mid)]))
        assert s.get(models.MovieInfo, mid) is None
        api.status = 200
        monkeypatch.setattr(tmdb, "_retry_after", {})  # the pause after a failure is over
        asyncio.run(tmdb.enrich(s, [s.get(models.Movie, mid)]))
        assert s.get(models.MovieInfo, mid).tmdb_id == 45


def test_enrich_does_nothing_without_a_key(monkeypatch, api, session_factory):
    monkeypatch.setenv("TMDB_API_KEY", "")
    [mid] = _movies(session_factory, "Sintel 2010")
    with session_factory() as s:
        asyncio.run(tmdb.enrich(s, [s.get(models.Movie, mid)]))
        assert s.scalar(select(models.MovieInfo)) is None


def _multi(request):
    """TMDb answers in the language it is asked in."""
    if request.url.params["language"] == "fr-FR":
        return {"results": [
            {"media_type": "movie", "id": 914, "title": "Le Dictateur", "original_title": "The Great Dictator", "release_date": "1940-10-15"},
            {"media_type": "person", "id": 1, "name": "Charles Chaplin", "known_for_department": "Acting"},
            {"media_type": "movie", "id": 5, "title": "Le Kid", "original_title": "The Kid", "release_date": "1921-02-06"},
            {"media_type": "movie", "id": 6, "title": "Les Temps modernes", "original_title": "Modern Times", "release_date": "1936-02-05"},
            {"media_type": "movie", "id": 7, "title": "La Ruée vers l'or", "original_title": "The Gold Rush", "release_date": "1925-06-26"},
            {"media_type": "person", "id": 2, "name": "Sydney Chaplin", "known_for_department": "Acting"},
            {"media_type": "person", "id": 3, "name": "Oona Chaplin", "known_for_department": "Acting"},
            {"media_type": "movie", "id": 8, "release_date": "1999-01-01"},
        ]}
    return {"results": [{"media_type": "movie", "id": 914, "title": "The Great Dictator", "original_title": "The Great Dictator", "release_date": "1940-10-15"}]}


def test_discover_finds_titles_in_both_languages_and_people(api):
    api.routes["/search/multi"] = _multi
    found = asyncio.run(tmdb.discover("le dictateur", "fr"))
    assert [c.url.params["language"] for c in api.calls] == ["fr-FR", "en-US"]  # the member's language, and English
    assert all(c.url.params["query"] == "le dictateur" for c in api.calls)
    assert found["titles"][0] == {"id": 914, "year": 1940, "names": ["Le Dictateur", "The Great Dictator"]}
    assert len(found["titles"]) == 3  # the best three, and a hit without a name is left out
    assert [p["name"] for p in found["people"]] == ["Charles Chaplin", "Sydney Chaplin", "Oona Chaplin"]
    assert found["people"][0] == {"id": 1, "name": "Charles Chaplin", "department": "Acting", "popularity": 0}


def test_discover_asks_once_when_the_member_speaks_english(api):
    api.routes["/search/multi"] = _multi
    asyncio.run(tmdb.discover("dictator", "en"))
    assert [c.url.params["language"] for c in api.calls] == ["en-US"]


def test_discover_is_quiet_without_a_key_and_loud_on_errors(api, monkeypatch):
    api.status = 500
    with pytest.raises(tmdb.TmdbError):
        asyncio.run(tmdb.discover("x", "en"))
    monkeypatch.setenv("TMDB_API_KEY", "")
    assert asyncio.run(tmdb.discover("x", "en")) == {"titles": [], "people": []}


def test_a_filmography_lists_the_films_directed_and_acted_most_voted_first(api):
    api.routes["/person/1/combined_credits"] = {
        "crew": [
            {"media_type": "movie", "job": "Director", "title": "The Kid", "original_title": "The Kid", "release_date": "1921-02-06", "vote_count": 900},
            {"media_type": "movie", "job": "Director", "title": "Modern Times", "original_title": "Modern Times", "release_date": "1936-02-05", "vote_count": 2000},
            {"media_type": "movie", "job": "Music", "title": "Not Directed", "release_date": "1950-01-01", "vote_count": 10},
            {"media_type": "tv", "job": "Director", "name": "A Series", "vote_count": 5000},
        ],
        "cast": [{"media_type": "movie", "title": "Limelight", "original_title": "Limelight", "release_date": "1952-10-16", "vote_count": 300}],
    }
    films = asyncio.run(tmdb.filmography(1))
    assert [f["title"] for f in films["director"]] == ["Modern Times", "The Kid"]
    assert films["director"][0] == {"title": "Modern Times", "original_title": "Modern Times", "year": 1936}
    assert [f["title"] for f in films["cast"]] == ["Limelight"]
