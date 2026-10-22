from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import func, select

from app import auth, models, oauth
from tests.conftest import USER

CALLBACK = f"{auth.APP_URL}/api/auth/42/callback"
FT_PROFILE = {
    "id": 4242,
    "login": "ada42",
    "email": "ada@student.42.fr",
    "first_name": "Ada",
    "last_name": "Lovelace",
    "image": {"link": "https://cdn.intra.42.fr/users/ada.jpg"},
}
GOOGLE_PROFILE = {
    "sub": "109876",
    "email": "ada@example.com",
    "email_verified": True,
    "given_name": "Ada",
    "family_name": "Lovelace",
    "picture": "https://lh3.googleusercontent.com/a/ada",
}


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    for name in ("FORTYTWO", "GOOGLE"):
        monkeypatch.setenv(f"{name}_CLIENT_ID", f"{name.lower()}-id")
        monkeypatch.setenv(f"{name}_CLIENT_SECRET", f"{name.lower()}-secret")


@pytest.fixture
def provider(monkeypatch):
    """A fake provider: answers the token and profile requests, remembers what it was asked."""
    fake = type("Fake", (), {"profile": FT_PROFILE, "token_status": 200, "requests": []})()

    def handler(request):
        fake.requests.append(request)
        if request.url.path.endswith("/token"):
            if fake.token_status != 200:
                return httpx.Response(fake.token_status, json={"error": "server_error"})
            return httpx.Response(200, json={"access_token": "provider-token"})
        return httpx.Response(200, json=fake.profile)

    monkeypatch.setattr(oauth, "_http", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    return fake


def start(client, name="42"):
    """Click the 'log in with' button: the state the provider will send back."""
    r = client.get(f"/api/auth/{name}/login", follow_redirects=False)
    return parse_qs(urlparse(r.headers["location"]).query)["state"][0]


def finish(client, state, name="42", **params):
    return client.get(f"/api/auth/{name}/callback", params={"code": "abc", "state": state, **params}, follow_redirects=False)


def sign_in(client, name="42"):
    return finish(client, start(client, name), name)


def count(session_factory):
    with session_factory() as s:
        return s.scalar(select(func.count()).select_from(models.User))


def test_login_sends_the_browser_to_the_provider_with_a_state(client):
    r = client.get("/api/auth/42/login", follow_redirects=False)
    url = urlparse(r.headers["location"])
    query = parse_qs(url.query)
    assert (r.status_code, url.netloc, url.path) == (307, "api.intra.42.fr", "/oauth/authorize")
    assert query["client_id"] == ["fortytwo-id"]
    assert query["redirect_uri"] == [CALLBACK]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["public"]
    # the same random value goes to the provider and into a cookie only this browser has
    assert client.cookies.get("oauth_state") == query["state"][0] and len(query["state"][0]) >= 32


def test_unknown_provider_is_404(client):
    assert client.get("/api/auth/github/login", follow_redirects=False).status_code == 404
    assert client.get("/api/auth/github/callback", follow_redirects=False).status_code == 404


def test_a_provider_without_credentials_sends_the_visitor_back_with_an_error(client, monkeypatch):
    monkeypatch.setenv("FORTYTWO_CLIENT_ID", "")
    r = client.get("/api/auth/42/login", follow_redirects=False)
    assert r.headers["location"] == f"{auth.APP_URL}/?oauth_error=unavailable"


def test_42_callback_creates_a_member_and_signs_them_in(client, provider, session_factory):
    r = sign_in(client)
    assert (r.status_code, r.headers["location"]) == (307, f"{auth.APP_URL}/")

    token_request, profile_request = provider.requests
    assert token_request.url == "https://api.intra.42.fr/oauth/token"
    assert parse_qs(token_request.content.decode()) == {
        "grant_type": ["authorization_code"],
        "code": ["abc"],
        "redirect_uri": [CALLBACK],
        "client_id": ["fortytwo-id"],
        "client_secret": ["fortytwo-secret"],
    }
    assert profile_request.url == "https://api.intra.42.fr/v2/me"
    assert profile_request.headers["authorization"] == "Bearer provider-token"

    me = client.get("/api/auth/me").json()
    assert (me["username"], me["email"], me["first_name"], me["last_name"]) == ("ada42", "ada@student.42.fr", "Ada", "Lovelace")
    assert me["avatar_url"] is None  # the provider photo is not kept
    # no password exists, so the account cannot be entered with a guessed one
    assert client.post("/api/auth/login", json={"username": "ada42", "password": ""}).status_code == 401
    assert client.cookies.get("oauth_state") is None


def test_google_callback_maps_the_profile(client, provider):
    provider.profile = GOOGLE_PROFILE
    start_url = urlparse(client.get("/api/auth/google/login", follow_redirects=False).headers["location"])
    assert (start_url.netloc, parse_qs(start_url.query)["scope"]) == ("accounts.google.com", ["openid email profile"])

    assert sign_in(client, "google").headers["location"] == f"{auth.APP_URL}/"
    assert provider.requests[0].url == "https://oauth2.googleapis.com/token"
    assert provider.requests[1].url == "https://openidconnect.googleapis.com/v1/userinfo"
    me = client.get("/api/auth/me").json()
    assert (me["username"], me["email"], me["first_name"], me["last_name"]) == ("ada", "ada@example.com", "Ada", "Lovelace")
    assert me["avatar_url"] is None


def test_the_same_account_signs_in_to_the_same_member(client, provider, session_factory):
    sign_in(client)
    first = client.get("/api/auth/me").json()["id"]
    client.post("/api/auth/logout")
    sign_in(client)
    assert client.get("/api/auth/me").json()["id"] == first
    assert count(session_factory) == 1


def test_a_wrong_state_is_refused(client, provider, session_factory):
    start(client)
    r = finish(client, "not-the-state-we-sent")
    assert r.headers["location"] == f"{auth.APP_URL}/?oauth_error=failed"
    assert client.get("/api/auth/me").json() is None
    assert count(session_factory) == 0 and provider.requests == []  # the code is not even exchanged


def test_a_callback_without_the_state_cookie_is_refused(client, provider, session_factory):
    # someone else's authorization code pushed into this browser: it never went through /login here
    r = finish(client, "attacker-state")
    assert r.headers["location"] == f"{auth.APP_URL}/?oauth_error=failed"
    assert client.get("/api/auth/me").json() is None and count(session_factory) == 0


def test_the_provider_refusing_goes_back_with_denied(client, provider):
    state = start(client)
    r = client.get("/api/auth/42/callback", params={"error": "access_denied", "state": state}, follow_redirects=False)
    assert r.headers["location"] == f"{auth.APP_URL}/?oauth_error=denied"
    assert client.get("/api/auth/me").json() is None


def test_a_provider_failure_goes_back_with_failed_and_leaks_nothing(client, provider, session_factory):
    provider.token_status = 500
    r = sign_in(client)
    assert r.headers["location"] == f"{auth.APP_URL}/?oauth_error=failed"
    assert "secret" not in r.headers["location"] and count(session_factory) == 0


def test_a_verified_email_joins_the_existing_account(client, provider, session_factory):
    client.post("/api/auth/register", json={**USER, "email": "ada@example.com"})
    client.post("/api/auth/logout")
    provider.profile = GOOGLE_PROFILE
    sign_in(client, "google")
    me = client.get("/api/auth/me").json()
    assert (me["username"], count(session_factory)) == ("ada_l", 1)


def test_an_unverified_google_email_never_joins_an_account(client, provider, session_factory):
    # otherwise anyone could take over an account by creating a Google identity with its email
    client.post("/api/auth/register", json={**USER, "email": "ada@example.com"})
    client.post("/api/auth/logout")
    provider.profile = {**GOOGLE_PROFILE, "email_verified": False}
    r = sign_in(client, "google")
    assert r.headers["location"] == f"{auth.APP_URL}/?oauth_error=unverified"
    assert client.get("/api/auth/me").json() is None and count(session_factory) == 1


def test_a_taken_username_gets_a_suffix_and_the_other_member_is_untouched(client, provider, session_factory):
    client.post("/api/auth/register", json={**USER, "username": "ada42"})
    client.post("/api/auth/logout")
    sign_in(client)
    me = client.get("/api/auth/me").json()
    assert me["username"] != "ada42" and me["username"].startswith("ada42")
    with session_factory() as s:
        assert s.scalar(select(models.User).where(models.User.username == "ada42")).email == "ada@example.com"
