import json

import httpx
import pytest

from app import sources

CATALOGUE = [
    {"id": "zeta", "name": "Zeta", "description": "d", "language": "en-US", "type": "public", "configured": False},
    {"id": "alpha", "name": "Alpha", "description": "d", "language": "en-US", "type": "public", "configured": True},
]
FIELDS = [
    {"id": "sitelink", "type": "inputstring", "name": "Site Link", "value": "https://x/"},
    {"id": "sort", "type": "inputselect", "name": "Sort", "value": "seeders", "options": {"seeders": "Seeders", "date": "Date"}},
    {"id": "info", "type": "displayinfo", "name": "Info", "value": "text"},
]


@pytest.fixture
def jackett_api(logged_in, monkeypatch):
    """A fake Jackett: `calls` records (method, path, json)."""
    fake = type("Fake", (), {"calls": [], "status": 200})()

    def handler(request):
        if request.url.path == "/UI/Dashboard":
            return httpx.Response(200, text="ok")
        body = request.read()
        fake.calls.append((request.method, request.url.path, body.decode()))
        if fake.status != 200:
            return httpx.Response(fake.status, json={"error": "Nope\nstack trace"})
        path = request.url.path.removeprefix("/api/v2.0/indexers")
        if request.method == "GET" and path == "":
            return httpx.Response(200, json=CATALOGUE)
        if request.method == "GET" and path.endswith("/config"):
            return httpx.Response(200, json=FIELDS)
        return httpx.Response(200)

    monkeypatch.setattr(sources, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://jackett", follow_redirects=True))
    logged_in.fake = fake
    return logged_in


def test_the_indexers_are_listed_by_name_with_whether_they_are_configured(jackett_api):
    got = jackett_api.get("/api/sources").json()
    assert [(i["id"], i["configured"]) for i in got] == [("alpha", True), ("zeta", False)]


def test_the_form_has_only_the_fields_a_member_can_fill(jackett_api):
    got = jackett_api.get("/api/sources/zeta/config").json()
    assert [f["id"] for f in got] == ["sort"]  # not the site link, not a text to read


def test_adding_sends_the_form_values_over_the_defaults(jackett_api):
    assert jackett_api.put("/api/sources/zeta", json={"values": {"sort": "date"}}).status_code == 204
    method, path, body = jackett_api.fake.calls[-1]
    assert (method, path) == ("POST", "/api/v2.0/indexers/zeta/config")
    sent = {f["id"]: f["value"] for f in json.loads(body)}
    assert sent == {"sitelink": "https://x/", "sort": "date", "info": "text"}  # the form's value, the others as Jackett has them


def test_an_indexer_is_removed_and_tested(jackett_api):
    assert jackett_api.delete("/api/sources/zeta").status_code == 204
    assert jackett_api.fake.calls[-1][:2] == ("DELETE", "/api/v2.0/indexers/zeta")
    assert jackett_api.post("/api/sources/zeta/test").json() == {"ok": True}
    jackett_api.fake.status = 500
    assert jackett_api.post("/api/sources/zeta/test").json() == {"ok": False, "error": "Nope"}


def test_a_jackett_error_is_a_502_with_its_first_line(jackett_api):
    jackett_api.fake.status = 500
    res = jackett_api.put("/api/sources/zeta", json={"values": {}})
    assert res.status_code == 502 and res.json()["detail"] == "Nope"


def test_an_odd_id_is_refused(jackett_api):
    assert jackett_api.delete("/api/sources/a%2F..%2Fb").status_code in (404, 422)
    assert jackett_api.delete("/api/sources/" + "x" * 80).status_code == 422
