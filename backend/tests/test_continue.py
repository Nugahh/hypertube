from datetime import datetime, timedelta, timezone

import pytest

from app import jackett, models
from tests.test_films import FEED, xml  # noqa: F401


@pytest.fixture
def seen(logged_in, monkeypatch, session_factory):
    """Ada (id 1) is logged in and has the films of the feed in the library; Bob (id 2) exists."""
    async def fetch(q, indexer=None):
        return FEED

    monkeypatch.setattr(jackett, "fetch_xml", fetch)
    ids = {m["title"]: m["id"] for m in logged_in.get("/api/search", params={"limit": 100}).json()}
    with session_factory() as s:
        s.add(models.User(email="bob@example.com", username="bob", first_name="B", last_name="B", password_hash="x"))
        s.commit()

    def watch(title_or_id, user=1, days_ago=0):
        movie_id = ids.get(title_or_id, title_or_id)
        with session_factory() as s:
            s.merge(models.Watched(user_id=user, movie_id=movie_id, watched_at=datetime.now(timezone.utc) - timedelta(days=days_ago)))
            s.commit()

    logged_in.ids, logged_in.watch = ids, watch
    return logged_in


def titles(client):
    res = client.get("/api/continue")
    assert res.status_code == 200, res.text
    return [m["title"] for m in res.json()]


def test_continue_is_closed_to_visitors(client):
    assert client.get("/api/continue").status_code == 401


def test_a_member_who_watched_nothing_has_nothing_to_continue(seen):
    assert titles(seen) == []


def test_the_films_the_member_started_come_back_latest_first(seen):
    seen.watch("Metropolis.1927.1080p", days_ago=3)
    seen.watch("Dracula 1958", days_ago=1)
    seen.watch("Nosferatu 1922", days_ago=2)
    assert titles(seen) == ["Dracula 1958", "Nosferatu 1922", "Metropolis.1927.1080p"]


def test_what_another_member_watched_is_not_shown(seen):
    seen.watch("Dracula 1958", user=2)
    assert titles(seen) == []


def test_two_copies_of_a_film_are_one_thumbnail_marked_watched(seen):
    seen.watch("Metropolis.1927.1080p", days_ago=2)
    seen.watch("Metropolis 1927", days_ago=1)
    [metropolis] = seen.get("/api/continue").json()
    assert metropolis["watched"] is True and len(metropolis["sources"]) == 2


def test_at_most_twenty_films(seen, session_factory):
    with session_factory() as s:
        for i in range(25):
            movie = models.Movie(source_id=f"x{i}", title=f"Film {i}", size=1, seeders=1, peers=1, provider="p", link="x", status="idle")
            s.add(movie)
            s.flush()
            s.add(models.Watched(user_id=1, movie_id=movie.id, watched_at=datetime.now(timezone.utc) - timedelta(minutes=i)))
        s.commit()
    assert len(titles(seen)) == 20


def test_a_thumbnail_is_named_by_tmdb_not_by_its_torrent(seen, session_factory):
    title, movie = next(iter(seen.ids.items()))
    with session_factory() as s:
        s.add(models.MovieInfo(movie_id=movie, tmdb_id=603, kind="movie"))
        s.add(models.CatalogTitle(kind="movie", tmdb_id=603, title="The Matrix"))
        s.commit()
    seen.watch(movie)
    got = {m["id"]: m["title"] for m in seen.get("/api/continue").json()}
    assert got[movie] == "The Matrix" and title != "The Matrix"
