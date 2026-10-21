import pytest

from app import blender, jackett, tmdb
from tests.test_movies import library, movie_id, sintel  # noqa: F401  (Jackett's sample feed + fake downloads)

RATINGS = {"Tears of Steel": 8.0, "Sintel": 7.5}
# the sample feed has 3 films, plus every open movie; Big Buck Bunny and Sintel are in both, so each is one film with two sources
ALL = 3 + len(blender.FILMS) - 2
YEARS = sorted(f["year"] for f in blender.FILMS)  # the feed adds one film without a year


@pytest.fixture(autouse=True)
def fresh_pauses():
    tmdb._retry_after.clear()


@pytest.fixture
def rated(monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "key")

    async def lookup(title, year):
        name = tmdb.clean_title(title)
        return {"tmdb_id": 1, "kind": "movie", "rating": RATINGS[name], "year": year, "poster": None, "directors": [], "producers": [], "cast": [], "genres": []} if name in RATINGS else None

    monkeypatch.setattr(tmdb, "lookup", lookup)


def get(client, **params):
    res = client.get("/api/library", params=params)
    assert res.status_code == 200, res.text
    return res.json()


def titles(page):
    return [m["title"] for m in page["items"]]


def test_the_library_is_closed_to_visitors(client):
    assert client.get("/api/library").status_code == 401


def test_the_list_is_cut_in_pages_that_cover_everything_once(library):  # noqa: F811
    first, second, third, beyond = (get(library, per_page=4, page=p) for p in (1, 2, 3, 4))
    assert (first["total"], first["page"], first["has_more"]) == (ALL, 1, True)
    assert (len(first["items"]), len(second["items"]), len(third["items"])) == (4, 4, ALL - 8)
    assert (second["has_more"], third["has_more"]) == (True, False)
    ids = [m["id"] for p in (first, second, third) for m in p["items"]]
    assert len(set(ids)) == ALL
    assert beyond["items"] == [] and beyond["has_more"] is False


def test_without_a_search_the_most_popular_come_first_and_a_search_is_sorted_by_name(library):  # noqa: F811
    popular = get(library)
    assert titles(popular)[:2] == ["Big Buck Bunny", "Sintel.2010.720p"] and titles(popular)[-1] == "Old Silent Film"  # seeders 52, 47 … 0
    found = titles(get(library, q="s"))
    assert found == sorted(found, key=str.lower) and len(found) >= 3


def test_sorting_by_year_puts_unknown_years_last_in_both_directions(library):  # noqa: F811
    known = sorted(YEARS, reverse=True)
    assert [m["year"] for m in get(library, sort="year")["items"]] == known + [None]
    assert [m["year"] for m in get(library, sort="year", order="asc")["items"]] == known[::-1] + [None]


def test_sorting_and_filtering_by_rating(library, rated):  # noqa: F811
    best = get(library, sort="rating")
    assert [m["rating"] for m in best["items"]] == [8.0, 7.5] + [None] * (ALL - 2)
    assert titles(get(library, min_rating=8)) == ["Tears of Steel 2012"]
    assert len(get(library, min_rating=7)["items"]) == 2


def test_filtering_by_production_year(library):  # noqa: F811
    assert sorted(m["year"] for m in get(library, year_from=2011)["items"]) == [y for y in YEARS if y >= 2011]
    assert sorted(titles(get(library, year_to=2008))) == ["Big Buck Bunny", "Elephants Dream 2006"]
    assert sorted(m["year"] for m in get(library, year_from=2010, year_to=2012)["items"]) == [2010, 2012]


def test_a_fixed_row_is_passed_to_the_sources(library):  # noqa: F811
    found = titles(get(library, genre="series"))
    assert "Sintel.2010.720p" in found and "Tears of Steel 2012" not in found  # the open movies are not classic TV
    assert library.get("/api/library", params={"genre": "nope"}).status_code == 404


@pytest.mark.parametrize("params", [{"page": 0}, {"per_page": 0}, {"per_page": 61}, {"sort": "color"}, {"order": "sideways"}, {"min_rating": 11}])
def test_nonsense_parameters_are_refused(library, params):  # noqa: F811
    assert library.get("/api/library", params=params).status_code == 422


def test_a_source_failure_without_anything_else_to_show_is_a_502(library, monkeypatch):  # noqa: F811
    async def down(q):
        raise OSError("down")

    monkeypatch.setattr(jackett, "fetch_xml", down)
    assert library.get("/api/library", params={"q": "casablanca"}).status_code == 502


def test_watched_movies_are_marked_for_the_member_who_watched(library):  # noqa: F811
    assert all(m["watched"] is False for m in get(library)["items"])
    mid = sintel(library)
    assert library.get(f"/api/movies/{mid}/stream", headers={"Range": "bytes=0-9"}).status_code == 206
    marks = {m["id"]: m["watched"] for m in get(library)["items"]}
    assert marks[mid] is True and sum(marks.values()) == 1
    assert next(m for m in library.get("/api/search").json() if m["id"] == mid)["watched"] is True  # the rows too


# --- the search box: ranked by priority, and the reason is told ---
from tests.test_finder import result, web  # noqa: E402,F401  (fake archive.org and TMDb)


def chaplin(web):
    web.broad = [result("1", "Charlie Chaplin Festival")]
    web.people = [{"id": 1, "name": "Charles Chaplin", "department": "Directing"}]
    web.films = {"director": [{"title": "Aaa Film", "original_title": "Aaa Film", "year": 1936}], "cast": []}
    web.titles = [result("t3", "Aaa Film", 1936)]


def test_a_search_puts_the_title_first_then_the_other_reasons_and_says_why(library, web):  # noqa: F811
    chaplin(web)
    items = get(library, q="chapliin")["items"]
    assert [m["title"] for m in items][:2] == ["Charlie Chaplin Festival", "Aaa Film"]  # the title before the director, whatever the names
    assert items[0]["match"] == {"kind": "title", "label": None}
    assert items[1]["match"] == {"kind": "director", "label": "Charles Chaplin"}


def test_the_name_sort_is_still_there(library, web):  # noqa: F811
    chaplin(web)
    items = get(library, q="chapliin", sort="name")["items"]
    names = [m["title"].lower() for m in items]
    assert names == sorted(names) and names.index("aaa film") < names.index("charlie chaplin festival")  # by name, the reason ignored
    assert get(library, q="chapliin", sort="relevance")["items"] == get(library, q="chapliin")["items"]


def test_relevance_without_a_search_is_popularity_and_nothing_is_explained(library):  # noqa: F811
    assert titles(get(library, sort="relevance")) == titles(get(library))
    assert all(m["match"] is None for m in get(library)["items"])


def test_a_search_with_an_unknown_genre_is_a_404_and_with_nothing_to_show_a_failure_is_a_502(library, web):  # noqa: F811
    assert library.get("/api/library", params={"q": "x", "genre": "nope"}).status_code == 404
    web.error = jackett.JackettError("Jackett unavailable")
    assert library.get("/api/library", params={"q": "casablanca"}).status_code == 502
