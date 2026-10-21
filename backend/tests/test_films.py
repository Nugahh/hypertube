import pytest

from app import jackett, models


def xml(*items):
    body = "".join(
        f"<item><title>{t}</title><guid>{g}</guid><jackettindexer id='x'>{p}</jackettindexer><size>1000</size>"
        f"<link>http://jackett:9117/dl/x/?path={g}</link><torznab:attr name='seeders' value='{s}' /></item>"
        for t, g, p, s in items
    )
    return f'<?xml version="1.0"?><rss version="2.0" xmlns:torznab="http://torznab.com/schemas/2015/feed"><channel>{body}</channel></rss>'


FEED = xml(
    ("Metropolis 1927", "m1", "Public One", 9),
    ("Metropolis.1927.1080p", "m2", "Public Two", 30),
    ("Dracula 1931", "d1", "Public One", 5),
    ("Dracula 1958", "d2", "Public One", 4),
    ("Nosferatu", "n1", "Public One", 3),
    ("Nosferatu 1922", "n2", "Public Two", 8),
)


@pytest.fixture
def films(logged_in, monkeypatch):
    async def fetch(q, indexer=None):
        return FEED

    monkeypatch.setattr(jackett, "fetch_xml", fetch)
    return logged_in


def listed(client, name, **params):
    res = client.get("/api/library", params={"per_page": 60, **params})
    assert res.status_code == 200, res.text
    return [m for m in res.json()["items"] if m["title"].lower().startswith(name)]


def test_the_same_film_from_two_providers_is_one_thumbnail_with_both_sources(films):
    [metropolis] = listed(films, "metropolis")
    assert metropolis["title"] == "Metropolis.1927.1080p"  # the best seeded one stands for the film
    assert [(s["provider"], s["seeders"]) for s in metropolis["sources"]] == [("Public Two", 30), ("Public One", 9)]
    assert metropolis["sources"][0]["id"] == metropolis["id"]


def test_the_total_counts_films_not_torrents(films):
    res = films.get("/api/library", params={"per_page": 60}).json()
    assert res["total"] == len(res["items"]) and len({m["id"] for m in res["items"]}) == res["total"]
    assert sum(len(m["sources"]) for m in res["items"]) > res["total"]


def test_films_of_the_same_title_but_other_years_stay_apart(films):
    assert len(listed(films, "dracula")) == 2


def test_a_result_without_a_year_joins_the_film_of_that_title(films):
    [nosferatu] = listed(films, "nosferatu")
    assert len(nosferatu["sources"]) == 2


def test_a_film_without_other_source_lists_itself(films):
    [dracula, _] = listed(films, "dracula")
    assert [s["id"] for s in dracula["sources"]] == [dracula["id"]]


def test_a_downloaded_copy_stands_for_the_film_even_with_fewer_seeders(films, session_factory):
    listed(films, "metropolis")  # remembers the results
    with session_factory() as s:
        row = s.query(models.Movie).filter_by(source_id="m1").one()
        row.status = "ready"
        s.commit()
        ready = row.id
    [metropolis] = listed(films, "metropolis")
    assert metropolis["id"] == ready and metropolis["sources"][0]["id"] == ready


def test_a_film_is_watched_when_any_of_its_sources_was(films, session_factory):
    listed(films, "metropolis")
    with session_factory() as s:
        other = s.query(models.Movie).filter_by(source_id="m1").one()
        s.add(models.Watched(user_id=1, movie_id=other.id))
        s.commit()
    [metropolis] = listed(films, "metropolis")
    assert metropolis["title"] == "Metropolis.1927.1080p" and metropolis["watched"] is True


def test_a_typed_search_groups_the_sources_too(films):
    [metropolis] = listed(films, "metropolis", q="metropolis")
    assert len(metropolis["sources"]) == 2


def test_the_rows_group_the_sources_too(films):
    found = [m for m in films.get("/api/search", params={"limit": 100}).json() if m["title"].lower().startswith("metropolis")]
    assert len(found) == 1 and len(found[0]["sources"]) == 2


def test_the_front_page_lists_each_film_once(films):
    names = [m["name"] for m in films.get("/api/movies").json() if m["name"].lower().startswith("metropolis")]
    assert len(names) == 1
