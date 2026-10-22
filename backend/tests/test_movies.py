import asyncio
import threading
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import engine as engine_module
from app import jackett, main, models, movies
from tests.fakes import TORRENT_A, TORRENT_B, FakeEngine
from tests.test_jackett import FEED

VIDEO = bytes(range(256)) * 40  # 10 240 bytes, every position distinguishable


@pytest.fixture
def library(logged_in, monkeypatch, tmp_path):
    """Logged in, with Jackett returning the sample feed and a fake download engine."""
    async def fetch_xml(q):
        return FEED

    fetched = []

    async def fetch_torrent(link):
        fetched.append(link)
        return TORRENT_A if "Sintel" in link else TORRENT_B

    monkeypatch.setattr(jackett, "fetch_xml", fetch_xml)
    monkeypatch.setattr(jackett, "fetch_torrent", fetch_torrent)
    engine = FakeEngine(tmp_path / "downloads", {TORRENT_A: ("sintel.mp4", VIDEO), TORRENT_B: ("bbb.mp4", VIDEO[:5000])})
    main.app.dependency_overrides[engine_module.get_engine] = lambda: engine
    logged_in.engine, logged_in.fetched = engine, fetched
    return logged_in


def movie_id(client, title):
    return next(m["id"] for m in client.get("/api/search").json() if m["title"] == title)


def sintel(client):
    return movie_id(client, "Sintel.2010.720p")


def test_search_gives_stable_numeric_ids(library):
    first = {m["title"]: m["id"] for m in library.get("/api/search").json()}
    again = {m["title"]: m["id"] for m in library.get("/api/search", params={"q": "sintel"}).json()}
    assert all(isinstance(i, int) for i in first.values())
    assert len(set(first.values())) == len(first)  # one id per result, from both sources
    assert again["Sintel.2010.720p"] == first["Sintel.2010.720p"]


def test_movie_details_show_the_state_and_never_the_provider_link(library):
    detail = library.get(f"/api/movies/{sintel(library)}").json()
    assert detail["title"] == "Sintel.2010.720p" and detail["year"] == 2010 and detail["resolution"] == "720p"
    assert detail["state"] == "idle" and detail["progress"] == 0
    assert "SECRETKEY" not in str(detail) and "link" not in detail


def test_an_unknown_movie_is_a_404(library):
    assert library.get("/api/movies/999").status_code == 404
    assert library.get("/api/movies/999/stream").status_code == 404


def test_the_first_stream_request_starts_the_download_from_the_providers_torrent(library):
    library.get(f"/api/movies/{sintel(library)}/stream", headers={"Range": "bytes=0-9"})
    assert library.fetched == ["http://jackett:9117/dl/internetarchive/?jackett_apikey=SECRETKEY&path=abc&file=Sintel"]
    assert library.engine.added == [TORRENT_A]
    library.get(f"/api/movies/{sintel(library)}/stream", headers={"Range": "bytes=0-9"})
    assert len(library.fetched) == 1  # already running: the provider is not asked again


def test_a_whole_file_request_answers_200(library):
    res = library.get(f"/api/movies/{sintel(library)}/stream")
    assert res.status_code == 200
    assert res.content == VIDEO
    assert res.headers["accept-ranges"] == "bytes"
    assert res.headers["content-type"] == "video/mp4"
    assert res.headers["content-length"] == str(len(VIDEO))


def test_a_range_request_answers_206_with_just_those_bytes(library):
    res = library.get(f"/api/movies/{sintel(library)}/stream", headers={"Range": "bytes=100-199"})
    assert res.status_code == 206
    assert res.content == VIDEO[100:200]
    assert res.headers["content-range"] == f"bytes 100-199/{len(VIDEO)}"
    assert res.headers["content-length"] == "100"


def test_open_ended_and_suffix_ranges(library):
    url = f"/api/movies/{sintel(library)}/stream"
    assert library.get(url, headers={"Range": "bytes=10000-"}).content == VIDEO[10000:]
    assert library.get(url, headers={"Range": "bytes=-50"}).content == VIDEO[-50:]


def test_a_range_past_the_end_answers_416(library):
    res = library.get(f"/api/movies/{sintel(library)}/stream", headers={"Range": "bytes=20000-"})
    assert res.status_code == 416
    assert res.headers["content-range"] == f"bytes */{len(VIDEO)}"


def test_the_stream_waits_for_the_download_instead_of_failing(library):
    library.engine.ready = 1000  # only the first 1000 bytes have arrived
    start = threading.Timer(0.4, lambda: setattr(next(iter(library.engine.torrents.values())), "ready", len(VIDEO)))
    start.start()
    res = library.get(f"/api/movies/{sintel(library)}/stream")
    start.join()
    assert res.content == VIDEO


def test_the_stream_asks_the_engine_for_the_bytes_the_player_wants(library):
    library.get(f"/api/movies/{sintel(library)}/stream", headers={"Range": "bytes=8000-8100"})
    assert library.engine.torrents["hash-torrent-a"].asked[0] == 8000


def test_progress_follows_the_download_and_a_finished_one_is_kept_on_disk(library):
    library.engine.ready = 2560
    movie = sintel(library)
    library.get(f"/api/movies/{movie}/stream", headers={"Range": "bytes=0-9"})
    detail = library.get(f"/api/movies/{movie}").json()
    assert (detail["state"], detail["progress"], detail["peers"]) == ("downloading", 0.25, 3)

    library.engine.torrents["hash-torrent-a"].ready = len(VIDEO)
    detail = library.get(f"/api/movies/{movie}").json()
    assert (detail["state"], detail["progress"]) == ("ready", 1)
    assert library.engine.removed == ["hash-torrent-a"]  # no more seeding once we have it


def test_a_downloaded_movie_is_served_from_disk_without_the_network(library):
    movie = sintel(library)
    library.get(f"/api/movies/{movie}/stream", headers={"Range": "bytes=0-9"})
    library.get(f"/api/movies/{movie}")  # finishes: ready
    library.engine.added.clear()
    library.fetched.clear()
    res = library.get(f"/api/movies/{movie}/stream", headers={"Range": "bytes=5-9"})
    assert res.content == VIDEO[5:10]
    assert library.engine.added == [] and library.fetched == []


def test_a_downloaded_file_that_vanished_is_downloaded_again(library):
    movie = sintel(library)
    library.get(f"/api/movies/{movie}/stream", headers={"Range": "bytes=0-9"})
    library.get(f"/api/movies/{movie}")
    (library.engine.download_dir / "pack" / "sintel.mp4").unlink()
    library.engine.torrents.clear()
    assert library.get(f"/api/movies/{movie}/stream", headers={"Range": "bytes=0-9"}).status_code == 206


def test_watching_is_recorded_for_the_one_month_cleanup(library, session_factory):
    movie = sintel(library)
    library.get(f"/api/movies/{movie}/stream", headers={"Range": "bytes=0-9"})
    with session_factory() as s:
        watched = s.get(models.Movie, movie).last_watched_at
    assert datetime.now(timezone.utc) - watched.replace(tzinfo=timezone.utc) < timedelta(seconds=30)


def test_download_starts_the_torrent_without_streaming(library):
    movie = sintel(library)
    res = library.post(f"/api/movies/{movie}/download")
    assert res.status_code == 200 and res.json()["state"] == "downloading"
    library.post(f"/api/movies/{movie}/download")
    assert library.engine.added == [TORRENT_A]  # twice, started once


def test_a_torrent_without_video_answers_422(library):
    library.engine.videos[TORRENT_A] = ("readme.txt", None)
    assert library.get(f"/api/movies/{sintel(library)}/stream").status_code == 422


def test_a_junk_torrent_from_the_provider_answers_502(library, monkeypatch):
    async def junk(link):
        return b"<html>not a torrent</html>"

    monkeypatch.setattr(jackett, "fetch_torrent", junk)
    assert library.get(f"/api/movies/{sintel(library)}/stream").status_code == 502


def test_fetch_torrent_returns_the_file_the_provider_sends(monkeypatch):
    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"data")), **kw)
    )
    assert asyncio.run(jackett.fetch_torrent("http://jackett:9117/dl/x/?jackett_apikey=SECRETKEY")) == b"data"


MAGNET = "magnet:?xt=urn:btih:" + "a" * 40 + "&dn=Sintel"


def answering(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


def test_a_magnet_link_is_its_own_torrent_and_nobody_is_asked(monkeypatch):
    def nobody(request):
        raise AssertionError("a magnet link is not fetched")

    answering(monkeypatch, nobody)
    assert asyncio.run(jackett.fetch_torrent(MAGNET)) == MAGNET


@pytest.mark.parametrize("answer", [httpx.Response(302, headers={"location": MAGNET}), httpx.Response(200, text=MAGNET)])
def test_fetch_torrent_gives_the_magnet_link_a_provider_answers_with(monkeypatch, answer):
    answering(monkeypatch, lambda request: answer)  # a redirect to the magnet link is not followed, its address is the answer
    assert asyncio.run(jackett.fetch_torrent("http://jackett:9117/dl/x/?jackett_apikey=SECRETKEY")) == MAGNET


def test_a_redirect_to_anything_else_is_an_error(monkeypatch):
    answering(monkeypatch, lambda request: httpx.Response(302, headers={"location": "http://elsewhere/x.torrent"}))
    with pytest.raises(jackett.JackettError):
        asyncio.run(jackett.fetch_torrent("http://jackett:9117/dl/x/?jackett_apikey=SECRETKEY"))


def test_a_result_with_a_magnet_link_streams_once_the_swarm_has_given_its_files(library, monkeypatch):
    async def fetch_magnet(link):
        return MAGNET

    monkeypatch.setattr(jackett, "fetch_torrent", fetch_magnet)
    library.engine.magnets[MAGNET] = TORRENT_A
    res = library.get(f"/api/movies/{sintel(library)}/stream", headers={"Range": "bytes=0-9"})
    assert (res.status_code, res.content) == (206, VIDEO[:10])


def test_a_magnet_link_nobody_shares_answers_504(library, monkeypatch):
    async def fetch_magnet(link):
        return MAGNET

    monkeypatch.setattr(jackett, "fetch_torrent", fetch_magnet)
    res = library.get(f"/api/movies/{sintel(library)}/stream")
    assert (res.status_code, res.json()["detail"]) == (504, "Nobody is sharing this torrent right now")


def test_fetch_torrent_errors_never_leak_the_api_key(monkeypatch):
    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(500)), **kw)
    )
    with pytest.raises(jackett.JackettError) as err:
        asyncio.run(jackett.fetch_torrent("http://jackett:9117/dl/x/?jackett_apikey=SECRETKEY"))
    assert "SECRETKEY" not in str(err.value)


def test_a_download_can_be_cancelled_and_started_again(library):
    movie = sintel(library)
    library.post(f"/api/movies/{movie}/download")
    assert any(library.engine.download_dir.rglob("*.mp4"))
    res = library.delete(f"/api/movies/{movie}/download")
    assert res.status_code == 200 and res.json()["state"] == "idle"
    assert library.engine.removed == ["hash-torrent-a"]
    assert not any(library.engine.download_dir.rglob("*.mp4"))  # what had arrived is gone
    assert library.delete(f"/api/movies/{movie}/download").json()["state"] == "idle"  # nothing running: nothing changes
    assert library.post(f"/api/movies/{movie}/download").json()["state"] == "downloading"


def test_a_downloaded_movie_can_be_erased_from_the_server_and_downloaded_again(library):
    movie = sintel(library)
    library.get(f"/api/movies/{movie}/stream", headers={"Range": "bytes=0-9"})
    assert library.get(f"/api/movies/{movie}").json()["state"] == "ready"
    assert any(library.engine.download_dir.rglob("*.mp4"))
    res = library.delete(f"/api/movies/{movie}/file")
    assert res.status_code == 200 and (res.json()["state"], res.json()["progress"]) == ("idle", 0)
    assert not any(library.engine.download_dir.rglob("*.mp4"))
    assert library.post(f"/api/movies/{movie}/download").json()["state"] == "downloading"


def test_the_states_of_all_the_copies_come_in_one_call(library):
    library.engine.ready = 2560
    movie = sintel(library)
    library.post(f"/api/movies/{movie}/download")
    got = library.get(f"/api/movies/states?ids={movie},99999").json()
    assert got == {str(movie): {"state": "downloading", "progress": 0.25}}  # an unknown id is just left out
    assert library.get("/api/movies/states?ids=abc").status_code == 422


def test_a_downloaded_film_ends_in_the_library_and_a_streamed_one_stays_in_the_cache(library):
    streamed, chosen = sintel(library), None
    library.get(f"/api/movies/{streamed}/stream", headers={"Range": "bytes=0-9"})
    library.get(f"/api/movies/{streamed}")  # finished
    assert library.get(f"/api/movies/states?ids={streamed}").json()[str(streamed)]["state"] == "idle"  # only streamed: not a download
    assert any(library.engine.download_dir.rglob("*.mp4")) and not any(library.engine.library_dir.rglob("*.mp4"))

    library.post(f"/api/movies/{streamed}/download")  # now the member wants it
    assert library.get(f"/api/movies/states?ids={streamed}").json()[str(streamed)]["state"] == "ready"
    assert any(library.engine.library_dir.rglob("*.mp4")) and not any(library.engine.download_dir.rglob("*.mp4"))
    assert library.get(f"/api/movies/{streamed}/stream", headers={"Range": "bytes=0-9"}).status_code == 206  # played from the library
    assert [m["id"] for m in library.get("/api/downloads").json()] == [streamed]

    library.delete(f"/api/movies/{streamed}/file")
    assert not any(library.engine.library_dir.rglob("*.mp4"))


def test_the_cache_setting_is_kept(library, monkeypatch):
    monkeypatch.delenv("LIBRARY_LABEL", raising=False)  # set by docker compose
    assert library.get("/api/settings").json()["cache_days"] == 3
    assert library.patch("/api/settings", json={"cache_days": 7}).json()["cache_days"] == 7
    assert library.get("/api/settings").json() == {"cache_days": 7, "library_dir": str(library.engine.library_dir)}
    assert library.patch("/api/settings", json={"cache_days": -1}).status_code == 422


def test_a_download_the_member_asked_for_starts_again_after_a_restart(library, session_factory):
    library.engine.ready = 1000  # not finished
    kept, streamed = sintel(library), movie_id(library, "Big Buck Bunny")
    library.post(f"/api/movies/{kept}/download")
    library.get(f"/api/movies/{streamed}/stream", headers={"Range": "bytes=0-9"})
    library.engine.torrents.clear()
    library.engine.added.clear()  # the app was closed
    with session_factory() as s:
        asyncio.run(movies.resume(s, library.engine))
    assert library.engine.added == [TORRENT_A]  # only the film the member chose to download
