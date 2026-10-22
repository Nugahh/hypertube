import pytest
from fastapi.testclient import TestClient

from app import main
from tests.test_films import films, listed  # noqa: F401  (a feed where two films are offered twice)
from tests.test_movies import library, sintel  # noqa: F401  (Jackett's sample feed + a fake download engine)

BOB = {"email": "bob@example.com", "username": "bob", "first_name": "B", "last_name": "B", "password": "Builder pass 1!"}


def ids(client):
    return {m["title"]: m["id"] for m in client.get("/api/search", params={"limit": 100}).json()}


def shelf(client, kind):
    res = client.get(f"/api/bookmarks/{kind}")
    assert res.status_code == 200, res.text
    return [m["title"] for m in res.json()]


def test_a_film_goes_in_and_out_of_my_list(films):
    metro = ids(films)["Metropolis.1927.1080p"]
    assert shelf(films, "list") == []
    assert films.put(f"/api/movies/{metro}/bookmarks/list").status_code == 204
    assert shelf(films, "list") == ["Metropolis.1927.1080p"]
    assert films.delete(f"/api/movies/{metro}/bookmarks/list").status_code == 204
    assert shelf(films, "list") == []


def test_the_list_and_the_favorites_are_two_different_shelves(films):
    metro = ids(films)["Metropolis.1927.1080p"]
    films.put(f"/api/movies/{metro}/bookmarks/favorite")
    assert shelf(films, "favorite") == ["Metropolis.1927.1080p"] and shelf(films, "list") == []
    [card] = listed(films, "metropolis")
    assert (card["favorite"], card["listed"]) == (True, False)


def test_a_thumbnail_is_neither_listed_nor_a_favorite_by_default(films):
    assert all(m["favorite"] is False and m["listed"] is False for m in films.get("/api/search").json())


def test_adding_and_removing_twice_is_harmless(films):
    metro = ids(films)["Metropolis.1927.1080p"]
    assert [films.put(f"/api/movies/{metro}/bookmarks/list").status_code for _ in range(2)] == [204, 204]
    assert shelf(films, "list") == ["Metropolis.1927.1080p"]
    assert [films.delete(f"/api/movies/{metro}/bookmarks/list").status_code for _ in range(2)] == [204, 204]


def test_an_unknown_film_or_shelf_is_refused(films):
    assert films.put("/api/movies/999/bookmarks/list").status_code == 404
    assert films.put("/api/movies/1/bookmarks/nope").status_code == 422
    assert films.get("/api/bookmarks/nope").status_code == 422


def test_the_latest_addition_comes_first(films):
    known = ids(films)
    for title in ("Dracula 1931", "Nosferatu 1922", "Dracula 1958"):
        films.put(f"/api/movies/{known[title]}/bookmarks/list")
    assert shelf(films, "list") == ["Dracula 1958", "Nosferatu 1922", "Dracula 1931"]


def test_two_copies_of_a_film_are_one_entry_whichever_copy_was_added_and_removed(films):
    films.get("/api/search")
    known = ids(films)  # only the best copy of each film is listed: find the other one in the film's sources
    [metro] = listed(films, "metropolis")
    other = next(s["id"] for s in metro["sources"] if s["id"] != metro["id"])
    films.put(f"/api/movies/{other}/bookmarks/favorite")
    assert shelf(films, "favorite") == ["Metropolis.1927.1080p"]  # shown as the film, with its best copy
    [card] = listed(films, "metropolis")
    assert card["favorite"] is True
    assert films.delete(f"/api/movies/{known['Metropolis.1927.1080p']}/bookmarks/favorite").status_code == 204  # removed from the other one
    assert shelf(films, "favorite") == []


def test_downloads_lists_what_the_server_has_or_is_getting(library):  # noqa: F811
    assert library.get("/api/downloads").json() == []
    library.engine.ready = 1000  # a torrent that has 1000 of the 10 240 bytes
    film = sintel(library)
    assert library.post(f"/api/movies/{film}/download").status_code == 200
    [item] = library.get("/api/downloads").json()
    assert item["id"] == film and item["state"] == "downloading" and 0 < item["progress"] < 1
    library.engine.torrents[next(iter(library.engine.torrents))].ready = 10240  # the rest arrives
    [item] = library.get("/api/downloads").json()
    assert item["state"] == "ready" and item["progress"] == 1


def test_a_film_that_was_only_looked_at_is_not_a_download(library):  # noqa: F811
    library.get("/api/search")
    assert library.get("/api/downloads").json() == []
