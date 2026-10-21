import asyncio

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


def test_the_genre_keeps_the_matching_films():
    assert [m["id"] for m in blender.search("", "horreur")] == ["blender:tears-of-steel", "blender:elephants-dream"]  # sci-fi
    assert len(blender.search("", "blender")) == 9  # its own row
    assert len(blender.search("", "populaires")) == 9
    assert "blender:sintel" in [m["id"] for m in blender.search("", "animation")]
    assert blender.search("", "western") == []


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
