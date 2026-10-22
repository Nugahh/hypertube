import httpx
import pytest
from sqlalchemy import select

from app import catalog, jackett, models, tmdb

GENRES = {"genres": [{"id": 28, "name": "Action"}, {"id": 80, "name": "Crime"}]}
MATRIX = {"id": 603, "title": "The Matrix", "release_date": "1999-03-30", "vote_average": 8.2, "vote_count": 25000, "poster_path": "/m.jpg",
          "overview": "A hacker learns the truth.", "genre_ids": [28], "popularity": 90.5}
KRILL = {"id": 1396, "name": "Breaking Bad", "first_air_date": "2008-01-20", "vote_average": 8.9, "vote_count": 12000, "poster_path": "/b.jpg",
         "overview": "A teacher cooks.", "genre_ids": [80], "popularity": 120.0}
DETAILS = {
    "title": "The Matrix", "overview": "A hacker learns the truth.", "runtime": 136, "vote_average": 8.2, "vote_count": 25000,
    "release_date": "1999-03-30", "poster_path": "/m.jpg", "original_language": "en", "genres": [{"name": "Action"}],
    "credits": {"cast": [{"name": "Keanu Reeves"}], "crew": [{"name": "Lana Wachowski", "job": "Director"}]},
}


@pytest.fixture
def api(logged_in, monkeypatch):
    """A fake TMDb: `calls` records every request."""
    monkeypatch.setenv("TMDB_API_KEY", "0123456789abcdef0123456789abcdef")
    fake = type("Fake", (), {"calls": [], "status": 200})()

    def page(results):
        return lambda request: {"page": int(request.url.params["page"]), "total_results": 4000, "total_pages": 200, "results": results}

    routes = {
        "/genre/movie/list": GENRES, "/genre/tv/list": GENRES,
        "/discover/movie": page([MATRIX]), "/discover/tv": page([KRILL]),
        "/search/movie": page([MATRIX]), "/search/tv": page([KRILL]),
        "/movie/603": DETAILS, "/tv/1396": {**{k: v for k, v in DETAILS.items() if k != "title"}, "name": "Breaking Bad", "first_air_date": "2008-01-20", "created_by": [{"name": "Vince Gilligan"}], "episode_run_time": [47]},
    }

    def handler(request):
        fake.calls.append(request)
        if fake.status != 200:
            return httpx.Response(fake.status, json={})
        payload = routes.get(request.url.path.removeprefix("/3"))
        return httpx.Response(404, json={}) if payload is None else httpx.Response(200, json=payload(request) if callable(payload) else payload)

    monkeypatch.setattr(tmdb, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5))
    logged_in.fake = fake
    return logged_in


def discovered(fake):
    return [r for r in fake.calls if "/discover/" in r.url.path]


def test_the_genres_are_tmdbs_in_the_members_language(api):
    assert api.get("/api/catalog/genres", params={"kind": "movie"}).json() == [{"id": 28, "name": "Action"}, {"id": 80, "name": "Crime"}]
    assert api.fake.calls[-1].url.params["language"] == "en-US"
    api.patch("/api/users/me", json={"language": "fr"})
    api.get("/api/catalog/genres", params={"kind": "series"})  # not a kind
    api.get("/api/catalog/genres", params={"kind": "tv"})
    assert api.fake.calls[-1].url.params["language"] == "fr-FR"


def test_a_page_is_what_tmdb_lists_by_popularity_with_its_genres_named(api):
    page = api.get("/api/catalog", params={"kind": "movie", "genre": 28, "page": 2}).json()
    assert page == {
        "items": [{"kind": "movie", "id": 603, "title": "The Matrix", "year": 1999, "rating": 8.2, "poster": "https://image.tmdb.org/t/p/w500/m.jpg",
                   "overview": "A hacker learns the truth.", "genres": ["Action"], "favorite": False, "listed": False}],
        "page": 2, "total": 4000, "has_more": True,
    }
    [call] = discovered(api.fake)
    params = call.url.params
    assert (params["with_genres"], params["page"], params["sort_by"], params["include_adult"]) == ("28", "2", "popularity.desc", "false")
    assert int(params["vote_count.gte"]) > 0  # nobody-rated titles are not the catalogue


def test_without_a_genre_it_is_everything(api):
    api.get("/api/catalog", params={"kind": "movie"})
    assert "with_genres" not in discovered(api.fake)[0].url.params


def test_a_search_asks_tmdb_for_the_words_and_does_not_filter_by_genre(api):
    page = api.get("/api/catalog", params={"kind": "movie", "q": "  matrix ", "genre": 28}).json()
    assert [i["title"] for i in page["items"]] == ["The Matrix"] and page["has_more"] is True
    [call] = [r for r in api.fake.calls if "/search/" in r.url.path]
    assert call.url.params["query"] == "matrix" and "with_genres" not in call.url.params  # TMDb cannot filter a search by genre
    assert not discovered(api.fake)
    api.get("/api/catalog", params={"kind": "tv", "q": "breaking"})
    assert api.fake.calls[-1].url.path.endswith("/search/tv")


def test_series_are_browsed_the_same_way(api):
    [show] = api.get("/api/catalog", params={"kind": "tv", "genre": 80}).json()["items"]
    assert (show["title"], show["year"], show["genres"]) == ("Breaking Bad", 2008, ["Crime"])
    assert discovered(api.fake)[0].url.path.endswith("/discover/tv")


def test_tmdb_stops_at_500_pages(api):
    assert api.get("/api/catalog", params={"kind": "movie", "page": 501}).status_code == 422
    assert api.get("/api/catalog", params={"kind": "movie", "page": 0}).status_code == 422
    last = api.get("/api/catalog", params={"kind": "movie", "page": 500}).json()
    assert last["has_more"] is False


def test_what_is_listed_is_kept_in_the_database_once(api, session_factory):
    for _ in range(2):
        api.get("/api/catalog", params={"kind": "movie"})
    api.get("/api/catalog", params={"kind": "tv"})
    with session_factory() as s:
        rows = s.scalars(select(models.CatalogTitle).order_by(models.CatalogTitle.kind)).all()
        assert [(r.kind, r.tmdb_id, r.title, r.year, r.genres) for r in rows] == [("movie", 603, "The Matrix", 1999, ["Action"]), ("tv", 1396, "Breaking Bad", 2008, ["Crime"])]


def test_a_title_sheet_has_the_credits(api):
    sheet = api.get("/api/catalog/movie/603").json()
    assert (sheet["title"], sheet["year"], sheet["runtime"], sheet["rating"], sheet["genres"]) == ("The Matrix", 1999, 136, 8.2, ["Action"])
    assert (sheet["directors"], sheet["cast"], sheet["poster"]) == (["Lana Wachowski"], ["Keanu Reeves"], "https://image.tmdb.org/t/p/w500/m.jpg")
    assert api.get("/api/catalog/tv/1396").json()["title"] == "Breaking Bad"
    assert api.get("/api/catalog/movie/1").status_code == 404


def test_without_a_key_or_with_tmdb_down_it_says_so(api, monkeypatch):
    api.fake.status = 500
    assert api.get("/api/catalog", params={"kind": "movie"}).status_code == 502
    assert api.get("/api/catalog/genres", params={"kind": "movie"}).status_code == 502
    monkeypatch.delenv("TMDB_API_KEY")
    assert api.get("/api/catalog", params={"kind": "movie"}).status_code == 501


def test_an_unknown_kind_is_refused(api):
    assert api.get("/api/catalog", params={"kind": "book"}).status_code == 422


GB = 1024**3


def release(title, year, resolution, seeders=50, size=2 * GB, provider="A"):
    return {"id": f"{provider}:{title}", "title": title, "year": year, "resolution": resolution, "size": size, "seeders": seeders, "peers": 20,
            "provider": provider, "cover": None, "link": f"http://jackett/{title}"}


@pytest.fixture
def providers(api, monkeypatch):
    """The providers' answer to any name: `asked` records the names."""
    fake = type("Providers", (), {"asked": [], "found": [], "error": None})()

    async def search(q):
        fake.asked.append(q)
        if fake.error:
            raise fake.error
        return fake.found

    monkeypatch.setattr(jackett, "search", search)
    api.providers = fake
    return api


def test_a_film_opens_on_the_copies_the_providers_have(providers):
    providers.providers.found = [
        release("The.Matrix.1999.1080p.BluRay", 1999, "1080p", seeders=300),
        release("The.Matrix.1999.2160p.UHD", 1999, "2160p", seeders=40, provider="B"),
        release("The.Matrix.1999.CAM", 1999, None),  # a recording from the cinema
        release("The.Matrix.Reloaded.2003.1080p", 2003, "1080p"),  # another film that has the words
        release("The.Matrix.1980.1080p", 1980, "1080p"),  # another year
        release("The Matrix", None, None, provider="C"),  # a provider that does not write the year
    ]
    film = providers.get("/api/catalog/movie/603/copies").json()
    assert providers.providers.asked == ["The Matrix"]  # TMDb's name, not the year
    assert film["title"] == "The.Matrix.1999.2160p.UHD"  # 4K first, then 1080p, then the rest
    assert [(s["provider"], s["resolution"], s["tier"]) for s in film["sources"]] == [("B", "2160p", "4K"), ("A", "1080p", "1080p"), ("C", None, "720p")]
    assert film["tier"] == "4K"  # the quality tab the front opens on
    assert "link" not in film  # the provider link never leaves the server


def test_the_first_opening_already_has_tmdbs_poster_and_details(providers):
    # the copies are new rows: without this the poster (TMDb's, the indexers have none) only showed from the second opening
    providers.providers.found = [release("The.Matrix.1999.1080p.BluRay", 1999, "1080p")]
    film = providers.get("/api/catalog/movie/603/copies").json()
    assert (film["cover"], film["rating"]) == ("https://image.tmdb.org/t/p/w500/m.jpg", 8.2)
    detail = providers.get(f"/api/movies/{film['id']}").json()
    assert (detail["overview"], detail["directors"], detail["cast"]) == ("A hacker learns the truth.", ["Lana Wachowski"], ["Keanu Reeves"])
    assert not [c for c in providers.fake.calls if "/search/" in c.url.path]  # the film is not looked up again by its torrent name
    assert providers.get("/api/catalog/movie/603/copies").json()["cover"] == film["cover"]  # asking again changes nothing


def test_a_film_nobody_has_is_null(providers):
    providers.providers.found = [release("The.Matrix.1999.CAM", 1999, None), release("Other.Film.1999", 1999, None)]
    response = providers.get("/api/catalog/movie/603/copies")
    assert (response.status_code, response.json()) == (200, None)


def test_a_copy_is_a_movie_like_any_other(providers):
    providers.providers.found = [release("The.Matrix.1999.720p", 1999, "720p")]
    film = providers.get("/api/catalog/movie/603/copies").json()
    assert providers.get(f"/api/movies/{film['id']}").status_code == 200  # so it plays, downloads and goes in the lists


def test_the_original_name_is_asked_too(providers, monkeypatch):
    async def sheet(kind, tmdb_id, language):
        assert language == "en-US"
        return {"title": "Parasite", "original_title": "기생충", "year": 2019}

    monkeypatch.setattr(tmdb, "title_sheet", sheet)
    providers.providers.found = [release("Parasite.2019.1080p", 2019, "1080p")]
    assert providers.get("/api/catalog/movie/496243/copies").json()["title"] == "Parasite.2019.1080p"
    assert providers.providers.asked == ["Parasite", "기생충"]


def test_copies_need_tmdb_and_the_providers(providers, monkeypatch):
    providers.providers.error = jackett.JackettError("Jackett unavailable")
    assert providers.get("/api/catalog/movie/603/copies").status_code == 502
    assert providers.get("/api/catalog/movie/1/copies").status_code == 404
    monkeypatch.delenv("TMDB_API_KEY")
    assert providers.get("/api/catalog/movie/603/copies").status_code == 501


def test_a_catalogue_title_goes_to_the_list_and_the_favorites_and_comes_back(api):
    api.get("/api/catalog?kind=movie")  # the catalogue keeps what it showed
    assert api.put("/api/catalog/movie/603/bookmarks/favorite").status_code == 204
    assert api.put("/api/catalog/movie/603/bookmarks/favorite").status_code == 204  # twice: nothing changes
    item = api.get("/api/catalog?kind=movie").json()["items"][0]
    assert (item["favorite"], item["listed"]) == (True, False)
    assert [t["id"] for t in api.get("/api/catalog/bookmarks/favorite").json()] == [603]
    assert api.get("/api/catalog/bookmarks/list").json() == []
    assert api.delete("/api/catalog/movie/603/bookmarks/favorite").status_code == 204
    assert api.get("/api/catalog/bookmarks/favorite").json() == []
    assert api.put("/api/catalog/movie/999/bookmarks/list").status_code == 404  # never shown by the catalogue


def test_a_shelf_says_its_titles_in_the_members_language(api):
    api.get("/api/catalog?kind=movie")
    api.put("/api/catalog/movie/603/bookmarks/list")
    assert api.patch("/api/users/me", json={"language": "fr"}).status_code == 200
    [item] = api.get("/api/catalog/bookmarks/list").json()
    assert item["overview"] == DETAILS["overview"] and item["genres"] == ["Action"]
    asked = [r.url.params["language"] for r in api.fake.calls if r.url.path.endswith("/movie/603")]
    assert asked == ["fr-FR"]
    api.get("/api/catalog/bookmarks/list")
    assert len([r for r in api.fake.calls if r.url.path.endswith("/movie/603")]) == 1  # asked once, then remembered


def test_the_french_genres_of_series_have_no_english_left_over():
    assert tmdb._genre("Kids", "fr-FR") == "Enfants" and tmdb._genre("Action & Adventure", "fr-FR") == "Action & Aventure"
    assert tmdb._genre("Kids", "en-US") == "Kids" and tmdb._genre("Drame", "fr-FR") == "Drame"


def test_a_typo_finds_the_closest_title_the_catalogue_knows(session_factory):
    with session_factory() as s:
        s.add_all([models.CatalogTitle(kind="movie", tmdb_id=1, title="Spider-Man: Brand New Day"), models.CatalogTitle(kind="movie", tmdb_id=2, title="The Matrix")])
        s.commit()
        assert catalog._closest(s, "movie", "spidermann") == "spider man"
        assert catalog._closest(s, "movie", "matirx") == "matrix"
        assert catalog._closest(s, "movie", "zzzzzz") is None
        assert catalog._closest(s, "tv", "spidermann") is None  # series are another list
