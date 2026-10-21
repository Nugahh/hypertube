import asyncio
import time

import pytest

from app import blender, jackett, sources
from tests.test_jackett import FEED


def test_a_title_word_finds_the_film():
    [sintel] = blender.search("sintel")
    assert sintel["title"] == "Sintel 2010"
    assert (sintel["id"], sintel["provider"], sintel["year"]) == ("blender:sintel", "Blender Open Movies", 2010)
    assert sintel["link"] == "https://webtorrent.io/torrents/sintel.torrent"
    assert sintel["cover"] == "https://webtorrent.io/torrents/Sintel/poster.jpg"
    assert sintel["size"] == 129241752 and sintel["seeders"] >= 1  # the web seed is always there


def test_the_films_hosted_by_the_internet_archive_use_its_torrent_and_cover():
    [spring] = blender.search("spring")
    assert (spring["id"], spring["year"], spring["size"]) == ("blender:spring", 2019, 48274047)
    assert spring["link"] == "https://archive.org/download/spring_blenderopenmovie/spring_blenderopenmovie_archive.torrent"
    assert spring["cover"] == "https://archive.org/services/img/spring_blenderopenmovie"
    assert spring["provider"] == "Blender Open Movies"


def test_an_empty_query_lists_every_open_movie_and_a_miss_lists_none():
    assert len(blender.search("")) == len(blender.FILMS) == 9
    assert len({f["id"] for f in blender.search("")}) == 9  # no duplicate id
    assert blender.search("casablanca") == []


def test_the_open_movies_are_in_the_popular_row_and_their_own_and_in_no_other_fixed_row():
    assert len(blender.search("", "blender")) == 9  # its own row
    assert len(blender.search("", "populaires")) == 9
    assert blender.search("", "series") == []  # archive.org's row of classic TV
    assert blender.search("", "crime") == []  # a TMDb genre: the films come from the database, not from this source


def _jackett(monkeypatch, xml=FEED):
    async def fetch(q):
        if isinstance(xml, Exception):
            raise xml
        return xml

    monkeypatch.setattr(jackett, "fetch_xml", fetch)


def test_both_sources_answer_one_search(monkeypatch):
    _jackett(monkeypatch)
    providers = {r["provider"] for r in asyncio.run(sources.search(""))}
    assert "Blender Open Movies" in providers and len(providers) >= 2


def test_the_open_movies_row_never_asks_jackett(monkeypatch):
    _jackett(monkeypatch, AssertionError("Jackett must not be called"))
    assert len(asyncio.run(sources.search("", "blender"))) == 9


def test_a_failing_source_does_not_hide_the_other(monkeypatch):
    _jackett(monkeypatch, OSError("down"))
    assert [r["id"] for r in asyncio.run(sources.search("sintel"))] == ["blender:sintel"]


def test_a_failing_source_with_nothing_else_to_show_is_an_error(monkeypatch):
    _jackett(monkeypatch, OSError("down"))
    with pytest.raises(jackett.JackettError):
        asyncio.run(sources.search("casablanca"))


def test_results_are_sorted_by_name_when_searching(monkeypatch):
    _jackett(monkeypatch)
    titles = [r["title"].lower() for r in asyncio.run(sources.search("o"))]
    assert titles == sorted(titles)


def _slow_jackett(monkeypatch, answered):
    monkeypatch.setattr(sources, "SLOW", 0.05)

    async def fetch(q):
        await asyncio.sleep(0.3)
        answered.append(q)
        return FEED

    monkeypatch.setattr(jackett, "fetch_xml", fetch)


def test_a_slow_internet_archive_does_not_hold_back_the_open_movies(monkeypatch):
    answered = []
    _slow_jackett(monkeypatch, answered)

    async def scenario():
        first = await sources.search("")
        waited_for_it = bool(answered)
        await asyncio.sleep(0.5)  # the request was not dropped: its answer arrives and replaces the short one
        return first, waited_for_it, await sources.search("")

    first, waited_for_it, later = asyncio.run(scenario())
    assert not waited_for_it
    assert {r["provider"] for r in first} == {"Blender Open Movies"}
    assert answered and len({r["provider"] for r in later}) >= 2


def test_once_it_was_too_slow_the_internet_archive_is_not_waited_for_again_for_a_while(monkeypatch):
    asked = []
    monkeypatch.setattr(sources, "SLOW", 0.05)

    async def fetch(q):
        asked.append(q)
        await asyncio.sleep(0.3)
        return FEED

    monkeypatch.setattr(jackett, "fetch_xml", fetch)

    async def scenario():
        await sources.search("")  # too slow: it is now thought to be down
        started = time.monotonic()
        row = await sources.search("", "populaires")  # another row of the page
        quick = time.monotonic() - started < 0.04
        with pytest.raises(jackett.JackettError):
            await sources.search("casablanca")  # nothing to show without it: an error, at once
        await asyncio.sleep(0.5)  # it finally answers: it is trusted again
        await sources.search("", "populaires")
        return row, quick

    row, quick = asyncio.run(scenario())
    assert quick and row and {r["provider"] for r in row} == {"Blender Open Movies"}
    assert len(asked) == 2  # the first search, then the one made after it answered: nothing piled up in between


def test_a_slow_internet_archive_with_nothing_else_to_show_is_an_error(monkeypatch):
    _slow_jackett(monkeypatch, [])
    with pytest.raises(jackett.JackettError):
        asyncio.run(sources.search("casablanca"))
