import asyncio
import json

import httpx
import pytest

from app import opensubtitles

def _hit(file_id, release, downloads, title="Sintel", year=2010, **flags):
    return {
        "id": str(file_id),
        "attributes": {
            "language": "fr", "release": release, "download_count": downloads, "machine_translated": flags.get("machine", False),
            "feature_details": {"title": title, "year": year}, "files": [{"file_id": file_id, "file_name": f"{file_id}.srt"}],
        },
    }


SEARCH = {
    "data": [
        _hit(111, "Sintel.2010.720p", 50),
        _hit(222, "Sintel.BluRay", 900),
        _hit(333, "Sintel.machine", 5000, machine=True),
        _hit(444, "Another.Film.2010", 99999, title="Another Film"),  # the search is fuzzy: a more popular film is not the one asked for
        _hit(555, "Sintel.1999", 7000, year=1999),
        {"id": "6", "attributes": {"language": "fr", "release": "no files", "download_count": 5, "feature_details": {"title": "Sintel"}, "files": []}},
    ]
}
SRT = b"1\n00:00:01,000 --> 00:00:02,000\nBonjour\n"


@pytest.fixture(autouse=True)
def fresh_login():
    opensubtitles._token = None


@pytest.fixture
def api(monkeypatch):
    """A fake OpenSubtitles: `calls` records the requests, `download_link` is what /download answers."""
    monkeypatch.setenv("OPENSUBTITLES_API_KEY", "osk")
    monkeypatch.delenv("OPENSUBTITLES_USERNAME", raising=False)
    monkeypatch.delenv("OPENSUBTITLES_PASSWORD", raising=False)
    fake = type("Fake", (), {"calls": [], "download_link": "https://dl.opensubtitles.com/en/download/x.srt", "status": 200})()

    def handler(request):
        fake.calls.append(request)
        if fake.status != 200:
            return httpx.Response(fake.status, json={"message": "nope"})
        path = request.url.path
        if path == "/api/v1/subtitles":
            return httpx.Response(200, json=SEARCH)
        if path == "/api/v1/login":
            return httpx.Response(200, json={"token": "jwt-token"})
        if path == "/api/v1/download":
            return httpx.Response(200, json={"link": fake.download_link, "file_name": "a.srt", "remaining": 4})
        if request.url.host == "dl.opensubtitles.com":
            return httpx.Response(200, content=SRT)
        return httpx.Response(404)

    monkeypatch.setattr(opensubtitles, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5))
    return fake


def test_it_is_configured_by_an_api_key(monkeypatch):
    monkeypatch.setenv("OPENSUBTITLES_API_KEY", "")
    assert not opensubtitles.configured()
    monkeypatch.setenv("OPENSUBTITLES_API_KEY", "k")
    assert opensubtitles.configured()


def test_search_sends_the_key_and_a_user_agent_and_sorts_by_downloads(api):
    found = asyncio.run(opensubtitles.search("Sintel", "fr", tmdb_id=45, year=2010))
    # the right film and year first, most downloaded first, machine translations last; other films and entries without a file are dropped
    assert [(f["file_id"], f["title"], f["year"], f["downloads"]) for f in found] == [
        (222, "Sintel", 2010, 900), (111, "Sintel", 2010, 50), (333, "Sintel", 2010, 5000), (555, "Sintel", 1999, 7000),
    ]
    assert found[0] == {"file_id": 222, "lang": "fr", "release": "Sintel.BluRay", "downloads": 900, "title": "Sintel", "year": 2010}
    request = api.calls[0]
    assert request.headers["api-key"] == "osk" and "Hypertube" in request.headers["user-agent"]
    assert dict(request.url.params) == {"query": "Sintel", "languages": "fr", "tmdb_id": "45", "year": "2010"}
    assert "authorization" not in request.headers  # no account configured: anonymous


def test_with_an_account_it_logs_in_once_and_sends_the_token(api, monkeypatch):
    monkeypatch.setenv("OPENSUBTITLES_USERNAME", "me")
    monkeypatch.setenv("OPENSUBTITLES_PASSWORD", "secret")
    asyncio.run(opensubtitles.search("Sintel", "fr"))
    asyncio.run(opensubtitles.search("Sintel", "en"))
    logins = [c for c in api.calls if c.url.path == "/api/v1/login"]
    assert len(logins) == 1 and b'"username"' in logins[0].content
    assert all(c.headers["authorization"] == "Bearer jwt-token" for c in api.calls if c.url.path == "/api/v1/subtitles")


def test_download_asks_for_a_link_then_fetches_the_file(api):
    assert asyncio.run(opensubtitles.download(222)) == SRT
    post = api.calls[0]
    assert (post.method, post.url.path, json.loads(post.content)) == ("POST", "/api/v1/download", {"file_id": 222})
    assert api.calls[1].url.host == "dl.opensubtitles.com"
    assert "api-key" not in api.calls[1].headers  # the key is for the API, not for the file server


def test_a_download_link_on_another_host_is_refused(api):
    # the answer comes from the network: it must not make the server fetch an arbitrary address
    for link in ("https://evil.example/x.srt", "http://dl.opensubtitles.com/x.srt", "https://opensubtitles.com.evil.example/x.srt"):
        api.download_link = link
        with pytest.raises(opensubtitles.OpenSubtitlesError):
            asyncio.run(opensubtitles.download(1))


def test_provider_errors_become_one_generic_error(api):
    api.status = 429
    for call in (lambda: opensubtitles.search("x", "en"), lambda: opensubtitles.download(1)):
        with pytest.raises(opensubtitles.OpenSubtitlesError) as e:
            asyncio.run(call())
        assert "osk" not in str(e.value)


def test_the_official_docs_want_alphabetical_parameters_with_plus_for_spaces(api):
    asyncio.run(opensubtitles.search("Big Buck Bunny", "fr", tmdb_id=45, year=2008))
    assert api.calls[0].url.query == b"languages=fr&query=Big+Buck+Bunny&tmdb_id=45&year=2008"


def test_the_api_client_follows_redirects():
    # the API redirects a request whose parameters are not in its canonical form
    assert opensubtitles._client().follow_redirects


def test_a_redirect_of_the_subtitle_file_is_followed_only_inside_opensubtitles(api, monkeypatch):
    def handler(request):
        api.calls.append(request)
        if request.url.path == "/api/v1/download":
            return httpx.Response(200, json={"link": "https://dl.opensubtitles.com/a.srt", "remaining": 3})
        if request.url.path == "/a.srt":
            return httpx.Response(302, headers={"location": api.redirect_to})
        return httpx.Response(200, content=SRT)

    api.redirect_to = "https://cdn.opensubtitles.com/b.srt"
    monkeypatch.setattr(opensubtitles, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5))
    assert asyncio.run(opensubtitles.download(1)) == SRT
    api.redirect_to = "https://evil.example/b.srt"
    with pytest.raises(opensubtitles.OpenSubtitlesError):
        asyncio.run(opensubtitles.download(1))


def test_nothing_is_offered_when_no_result_is_the_film_asked_for(api):
    assert asyncio.run(opensubtitles.search("Completely Different Name", "fr")) == []


def test_a_shorter_or_longer_title_still_matches(api):
    # "Sintel" is what the API knows; the torrent may say "Sintel HD" or only "Sin"… the words of one must be in the other
    assert len(asyncio.run(opensubtitles.search("Sintel HD Remaster", "fr"))) == 4


@pytest.mark.parametrize("status", [406, 429])
def test_a_refused_download_is_reported_as_the_quota(api, status):
    api.status = status
    with pytest.raises(opensubtitles.OpenSubtitlesQuota):
        asyncio.run(opensubtitles.download(1))
    api.status = 500  # any other failure stays a plain error, not a quota message
    with pytest.raises(opensubtitles.OpenSubtitlesError) as e:
        asyncio.run(opensubtitles.download(1))
    assert not isinstance(e.value, opensubtitles.OpenSubtitlesQuota)
