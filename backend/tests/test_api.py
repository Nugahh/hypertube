import httpx

from app import jackett
from tests.test_jackett import FEED


def _fake_fetch(xml):
    async def fetch(q):
        return xml

    return fetch


def test_the_library_is_closed_to_visitors(client):
    assert client.get("/api/search").status_code == 401


def test_search_never_leaks_the_jackett_api_key(logged_in, monkeypatch):
    monkeypatch.setattr(jackett, "fetch_xml", _fake_fetch(FEED))
    res = logged_in.get("/api/search", params={"q": "sintel"})
    assert res.status_code == 200
    assert "SECRETKEY" not in res.text
    assert all("link" not in m for m in res.json())


def test_search_limit_caps_the_number_of_results(logged_in, monkeypatch):
    monkeypatch.setattr(jackett, "fetch_xml", _fake_fetch(FEED))
    assert len(logged_in.get("/api/search", params={"limit": 2}).json()) == 2
    assert logged_in.get("/api/search", params={"limit": 0}).status_code == 422


def test_search_answers_502_when_jackett_rejects_the_request(logged_in, monkeypatch):
    bad = '<error code="100" description="Invalid API Key" />'
    monkeypatch.setattr(jackett, "fetch_xml", _fake_fetch(bad))
    assert logged_in.get("/api/search", params={"q": "casablanca"}).status_code == 502


def test_search_answers_502_without_leaking_the_key_when_jackett_errors(logged_in, monkeypatch):
    async def fail(q):
        # httpx puts the full URL, query string included, in its error message
        url = "http://jackett:9117/api/v2.0/indexers/x/results/torznab/api?apikey=SECRETKEY"
        request = httpx.Request("GET", url)
        raise httpx.HTTPStatusError(
            f"Client error '401' for url '{url}'",
            request=request,
            response=httpx.Response(401, request=request),
        )

    monkeypatch.setattr(jackett, "fetch_xml", fail)
    res = logged_in.get("/api/search", params={"q": "casablanca"})
    assert res.status_code == 502
    assert "SECRETKEY" not in res.text


def test_search_answers_502_when_jackett_is_unreachable(logged_in, monkeypatch):
    async def down(q):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(jackett, "fetch_xml", down)
    assert logged_in.get("/api/search", params={"q": "casablanca"}).status_code == 502
