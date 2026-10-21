import asyncio

import pytest

from app import finder, jackett, models, tmdb


def result(guid, title, year=None):
    return {"id": guid, "title": title, "year": year, "resolution": None, "size": 1, "seeders": 5, "peers": 5, "provider": "Internet Archive", "cover": None, "link": "http://x/" + guid}


@pytest.fixture
def web(monkeypatch):
    """Fake archive.org (through Jackett) and TMDb: set what each kind of query answers, read what was asked."""
    fake = type("Web", (), {})()
    fake.broad, fake.creator, fake.titles, fake.alias = [], [], [], {}
    fake.people, fake.names, fake.films = [], [], {"director": [], "cast": []}
    fake.lucene_calls, fake.alias_calls, fake.tmdb_calls = [], [], []

    async def lucene(query):
        fake.lucene_calls.append(query)
        if isinstance(fake.error, Exception):
            raise fake.error
        if query.startswith("creator:"):
            return fake.creator
        return fake.titles if "title:" in query else fake.broad

    async def search(q, genre=None):
        fake.alias_calls.append(q)
        return fake.alias.get(q, [])

    async def discover(query, language="en"):
        fake.tmdb_calls.append(("discover", query, language))
        return {"titles": fake.names, "people": fake.people}

    async def filmography(person_id):
        fake.tmdb_calls.append(("filmography", person_id))
        return fake.films

    fake.error = None
    monkeypatch.setattr(jackett, "lucene", lucene)
    monkeypatch.setattr(jackett, "search", search)
    monkeypatch.setattr(tmdb, "discover", discover)
    monkeypatch.setattr(tmdb, "filmography", filmography)
    return fake


def run(session_factory, q, genre=None, language="en"):
    with session_factory() as db:
        hits = asyncio.run(finder.find(db, q, genre, language))
        return [(h.movie.title, h.kind, h.label) for h in hits]


def titles(hits):
    return [t for t, _, _ in hits]


def test_the_exact_title_comes_before_the_other_titles_and_the_rest(web, session_factory):
    web.broad = [result("1", "Sintel Behind the Scenes"), result("2", "Somebody Else"), result("3", "Sintel Making Of Part 2")]
    hits = run(session_factory, "sintel")
    assert hits[0] == ("Sintel 2010", "title", None)  # the open movie of that name: exactly the title
    assert titles(hits)[1:3] == ["Sintel Behind the Scenes", "Sintel Making Of Part 2"]  # whole words of the title, by name
    assert titles(hits)[-1] == "Somebody Else"  # found by archive.org somewhere else than the title


def test_a_typo_still_finds_the_title_and_asks_archive_org_to_forgive_it(web, session_factory):
    web.broad = [result("1", "Charlie Chaplin Festival"), result("2", "Unrelated Thing")]
    hits = run(session_factory, "chapliin")
    assert hits[0] == ("Charlie Chaplin Festival", "title", None) and titles(hits)[1] == "Unrelated Thing"
    assert web.lucene_calls[0] == "(chapliin~2)" and web.lucene_calls[1] == "creator:(chapliin~2)"  # eight letters: two slips


def test_what_is_typed_while_typing_finds_the_title(web, session_factory):
    web.broad = [result("1", "Charlie Chaplin Festival")]
    assert titles(run(session_factory, "chap"))[0] == "Charlie Chaplin Festival"


def test_accents_and_capitals_do_not_matter(web, session_factory):
    web.broad = [result("1", "Amélie")]
    assert titles(run(session_factory, "AMELIE"))[0] == "Amélie"
    assert web.lucene_calls[0] == "(amelie~1)"  # asked as typed; one slip is forgiven, so a missing accent is too
    web.lucene_calls.clear()
    run(session_factory, "Amélie Poulain")
    assert web.lucene_calls[0] == "(amélie~1 AND poulain~1)"  # accents kept when typed


def test_a_director_brings_their_films_tagged_with_their_name(web, session_factory):
    web.people = [{"id": 1, "name": "Charles Chaplin", "department": "Directing"}]
    web.films = {"director": [{"title": "The Kid", "original_title": "The Kid", "year": 1921}, {"title": "Modern Times", "original_title": "Modern Times", "year": 1936}], "cast": []}
    web.titles = [result("t1", "The Kid (1921)", 1921), result("t2", "Billy the Kid Returns", 1938), result("t3", "Modern Times", 1936), result("t4", "The Kid", 2005)]
    web.broad = [result("b1", "Charlie Chaplin Festival")]
    hits = run(session_factory, "chapliin")
    assert hits[0][0] == "Charlie Chaplin Festival"  # the title of that name first
    assert [(t, k, l) for t, k, l in hits if k == "director"] == [("Modern Times", "director", "Charles Chaplin"), ("The Kid (1921)", "director", "Charles Chaplin")]
    assert "Billy the Kid Returns" not in titles(hits) and "The Kid" not in titles(hits)  # not in their filmography / another year
    assert web.lucene_calls[-1].startswith('(title:"The Kid" OR title:"Modern Times")')


def test_an_actor_brings_the_films_they_acted_in(web, session_factory):
    web.people = [{"id": 2, "name": "Boris Karloff", "department": "Acting"}]
    web.films = {"director": [{"title": "Not Used", "original_title": "Not Used", "year": 1900}], "cast": [{"title": "Frankenstein", "original_title": "Frankenstein", "year": 1931}]}
    web.titles = [result("t1", "Frankenstein 1931", 1931)]
    assert ("Frankenstein 1931", "cast", "Boris Karloff") in run(session_factory, "karloff")


def test_a_person_who_does_not_look_like_the_query_is_ignored(web, session_factory):
    web.people = [{"id": 3, "name": "Somebody Entirely Different", "department": "Acting"}]
    run(session_factory, "karloff")
    assert not [c for c in web.tmdb_calls if c[0] == "filmography"]


def test_a_title_in_another_language_finds_the_film_under_its_other_name(web, session_factory):
    web.names = [{"id": 914, "year": 1940, "names": ["Le Dictateur", "The Great Dictator"]}]
    web.alias = {"The Great Dictator": [result("d1", "The Great Dictator 1940", 1940)]}
    hits = run(session_factory, "le dictateur", language="fr")
    assert hits[0] == ("The Great Dictator 1940", "alias", "Le Dictateur")  # tagged with the name that was typed
    assert web.alias_calls == ["The Great Dictator"] and ("discover", "le dictateur", "fr") in web.tmdb_calls


def test_the_summary_the_cast_and_the_director_of_known_films_are_searched_too(web, session_factory):
    with session_factory() as db:
        movie = models.Movie(source_id="m", title="Sintel 2010", size=1, seeders=1, peers=1, provider="p", link="l", status="idle")
        movie.info = models.MovieInfo(overview="A girl befriends a baby dragon named Scales.", directors=["Colin Levy"], cast=["Halina Reijn"])
        db.add(movie)
        db.commit()
    assert ("Sintel 2010", "overview", None) in run(session_factory, "scales")
    assert ("Sintel 2010", "director", "Colin Levy") in run(session_factory, "colin levy")
    assert ("Sintel 2010", "cast", "Halina Reijn") in run(session_factory, "halina reijn")
    assert ("Sintel 2010", "director", "Colin Levy") in run(session_factory, "collin levi")  # typos in a name too


def test_one_film_found_in_several_ways_appears_once_with_its_best_reason(web, session_factory):
    web.broad = [result("1", "Charlie Chaplin Festival")]
    web.creator = [result("1", "Charlie Chaplin Festival"), result("2", "The Tramp")]
    hits = run(session_factory, "chaplin")
    assert titles(hits).count("Charlie Chaplin Festival") == 1 and hits[0][1] == "title"
    assert ("The Tramp", "creator", None) in hits


def test_levels_decide_then_names(web, session_factory):
    web.broad = [result("1", "Zebra Chaplin"), result("2", "Alpha Chaplin")]
    web.creator = [result("3", "Aaa Creator Film")]
    assert titles(run(session_factory, "chaplin"))[:3] == ["Alpha Chaplin", "Zebra Chaplin", "Aaa Creator Film"]


def test_a_genre_goes_to_archive_org_and_filters_the_open_movies(web, session_factory):
    run(session_factory, "o", genre="horreur")
    assert all("collection:SciFi_Horror" in q for q in web.lucene_calls)
    hits = run(session_factory, "tears", genre="horreur")
    assert ("Tears of Steel 2012", "title", None) in hits
    assert "Sintel 2010" not in titles(run(session_factory, "sintel", genre="horreur"))


def test_the_open_movies_row_asks_nobody_else(web, session_factory):
    web.error = AssertionError("archive.org must not be asked")
    assert run(session_factory, "sintel", genre="blender")[0][0] == "Sintel 2010"


def test_when_archive_org_fails_the_rest_is_still_shown_and_with_nothing_it_is_an_error(web, session_factory):
    web.error = jackett.JackettError("Jackett unavailable")
    assert titles(run(session_factory, "sintel"))[0] == "Sintel 2010"  # the open movies and what we know already
    with pytest.raises(jackett.JackettError):
        run(session_factory, "casablanca")


def test_a_failing_tmdb_never_breaks_the_search(web, session_factory, monkeypatch):
    async def broken(*args, **kwargs):
        raise tmdb.TmdbError("TMDb unavailable")

    monkeypatch.setattr(tmdb, "discover", broken)
    web.broad = [result("1", "Charlie Chaplin Festival")]
    assert titles(run(session_factory, "chaplin"))[0] == "Charlie Chaplin Festival"


def test_the_same_search_is_not_run_twice(web, session_factory):
    web.broad = [result("1", "Charlie Chaplin Festival")]
    run(session_factory, "chaplin")
    asked = len(web.lucene_calls)
    run(session_factory, "Chaplin ")
    assert len(web.lucene_calls) == asked


def test_nothing_typed_finds_nothing(web, session_factory):
    assert run(session_factory, "  !! ") == []
    assert web.lucene_calls == []


def test_a_title_tmdb_matched_loosely_is_not_used_to_search(web, session_factory):
    web.names = [{"id": 1, "year": 2000, "names": ["Completely Other", "Autre Chose"]}]
    run(session_factory, "karloff")
    assert web.alias_calls == []  # nothing in its names looks like what was typed


def test_an_answer_given_while_archive_org_was_down_is_not_remembered(web, session_factory):
    web.error = jackett.JackettError("Jackett unavailable")
    assert titles(run(session_factory, "sintel"))[0] == "Sintel 2010"
    web.error = None
    web.broad = [result("1", "Sintel Behind the Scenes")]
    assert "Sintel Behind the Scenes" in titles(run(session_factory, "sintel"))  # asked again, not served from memory


def test_a_person_known_as_an_actor_also_brings_the_films_they_directed(web, session_factory):
    # TMDb files Charlie Chaplin under "Acting", yet he directed his films
    web.people = [{"id": 1, "name": "Charlie Chaplin", "department": "Acting", "popularity": 2.7}]
    web.films = {"director": [{"title": "The Kid", "original_title": "The Kid", "year": 1921}], "cast": [{"title": "Limelight", "original_title": "Limelight", "year": 1952}]}
    web.titles = [result("t1", "The Kid 1921", 1921), result("t2", "Limelight (1952)", 1952)]
    hits = run(session_factory, "chaplin")
    assert ("The Kid 1921", "director", "Charlie Chaplin") in hits and ("Limelight (1952)", "cast", "Charlie Chaplin") in hits
    assert len([c for c in web.lucene_calls if "title:" in c]) == 1  # one query for the person, both lists in it


def test_among_people_of_that_name_the_three_best_known_are_used(web, session_factory):
    web.people = [{"id": i, "name": f"John Smith {i}", "department": "Acting", "popularity": float(i)} for i in range(1, 6)]
    run(session_factory, "smith")
    asked = [c[1] for c in web.tmdb_calls if c[0] == "filmography"]
    assert sorted(asked) == [3, 4, 5]  # the most popular, whatever the order TMDb answered in
