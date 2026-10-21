import pytest
from fastapi.testclient import TestClient

from app import jackett, main
from tests.conftest import USER
from tests.test_jackett import FEED


def token_request(client, **form):
    return client.post("/api/oauth/token", data={"grant_type": "client_credentials", **form})


@pytest.fixture
def credentials(logged_in):
    """A client id and secret created by Ada in her profile."""
    res = logged_in.post("/api/clients", json={"name": "my script"})
    assert res.status_code == 201
    return res.json()


@pytest.fixture
def api(credentials):
    """A program with no cookie: it logs in with its client id and secret and sends the Bearer token."""
    program = TestClient(main.app)
    token = token_request(program, client_id=credentials["client_id"], client_secret=credentials["client_secret"]).json()["access_token"]
    program.headers["Authorization"] = f"Bearer {token}"
    return program


def test_credentials_are_created_by_a_logged_in_member_and_the_secret_is_shown_once(logged_in, client):
    assert TestClient(main.app).post("/api/clients", json={"name": "x"}).status_code == 401
    created = logged_in.post("/api/clients", json={"name": "my script"})
    body = created.json()
    assert created.headers["location"] == f"/api/clients/{body['id']}" and body["client_secret"] and body["client_id"]
    listed = logged_in.get("/api/clients").json()
    assert [(c["name"], c["client_id"]) for c in listed] == [("my script", body["client_id"])]
    assert "client_secret" not in listed[0] and body["client_secret"] not in str(listed)


def test_a_member_has_at_most_five_clients_and_deletes_their_own_only(logged_in):
    ids = [logged_in.post("/api/clients", json={"name": f"c{i}"}).json()["id"] for i in range(5)]
    assert logged_in.post("/api/clients", json={"name": "one too many"}).status_code == 409
    assert logged_in.delete(f"/api/clients/{ids[0]}").status_code == 204
    assert logged_in.delete(f"/api/clients/{ids[0]}").status_code == 404
    assert logged_in.post("/api/clients", json={"name": "again"}).status_code == 201


def test_the_token_endpoint_trades_client_and_secret_for_a_bearer_token(credentials):
    res = token_request(TestClient(main.app), client_id=credentials["client_id"], client_secret=credentials["client_secret"])
    assert res.status_code == 200 and res.headers["cache-control"] == "no-store"
    assert res.json()["token_type"] == "Bearer" and res.json()["expires_in"] == 3600 and res.json()["access_token"]


def test_the_token_endpoint_also_takes_http_basic(credentials):
    res = TestClient(main.app).post(
        "/api/oauth/token", data={"grant_type": "client_credentials"}, auth=(credentials["client_id"], credentials["client_secret"])
    )
    assert res.status_code == 200


def test_a_wrong_secret_or_client_is_refused_the_same_way(credentials):
    anyone = TestClient(main.app)
    wrong = token_request(anyone, client_id=credentials["client_id"], client_secret="nope")
    unknown = token_request(anyone, client_id="nobody", client_secret=credentials["client_secret"])
    assert (wrong.status_code, wrong.json()) == (401, {"error": "invalid_client"})
    assert (unknown.status_code, unknown.json()) == (401, {"error": "invalid_client"})


def test_bad_token_requests_are_400s(credentials):
    anyone = TestClient(main.app)
    assert anyone.post("/api/oauth/token", data={"grant_type": "password", "client_id": "a", "client_secret": "b"}).json() == {"error": "unsupported_grant_type"}
    assert token_request(anyone).status_code == 400  # no client at all


def test_a_bearer_token_gives_access_without_any_cookie(api):
    users = api.get("/api/users")
    assert users.status_code == 200 and [u["username"] for u in users.json()] == ["ada_l"]
    assert api.get("/api/comments").status_code == 200


def test_a_garbage_token_and_a_session_cookie_value_are_not_bearer_tokens(logged_in):
    other = TestClient(main.app)
    assert other.get("/api/users", headers={"Authorization": "Bearer junk"}).status_code == 401
    session = logged_in.cookies.get("session")
    assert other.get("/api/users", headers={"Authorization": f"Bearer {session}"}).status_code == 401


def test_an_api_token_is_not_a_session_cookie(api):
    token = api.headers["Authorization"].removeprefix("Bearer ")
    assert TestClient(main.app, cookies={"session": token}).get("/api/auth/me").json() is None


def test_deleting_the_client_revokes_its_tokens_and_a_token_cannot_create_clients(api, logged_in, credentials):
    assert api.post("/api/clients", json={"name": "escalation"}).status_code == 401  # only the website session can
    assert logged_in.delete(f"/api/clients/{credentials['id']}").status_code == 204
    assert api.get("/api/users").status_code == 401


def test_a_member_edits_only_their_own_profile_through_the_api(api, session_factory):
    from app import models, security

    with session_factory() as s:
        s.add(models.User(email="bob@example.com", username="bob", first_name="B", last_name="B", password_hash=security.hash_password("x pass 12")))
        s.commit()
    assert api.patch("/api/users/2", json={"first_name": "Hacked"}).status_code == 403
    assert api.patch("/api/users/1", json={"first_name": "Augusta"}).json()["first_name"] == "Augusta"
    assert api.get("/api/users/2").json() == {"id": 2, "username": "bob", "first_name": "B", "last_name": "B", "avatar_url": None}  # no email


def test_the_username_the_password_and_the_picture_url_can_be_changed(logged_in):
    assert logged_in.patch("/api/users/1", json={"username": "Countess_A"}).json()["username"] == "countess_a"
    assert logged_in.patch("/api/users/1", json={"username": "no spaces"}).status_code == 422
    assert logged_in.patch("/api/users/1", json={"avatar_url": "https://example.com/a.png"}).json()["avatar_url"] == "https://example.com/a.png"
    for bad in ("javascript:alert(1)", "http://example.com/a.png", "data:image/png;base64,AAAA", "https://" + "a" * 500):
        assert logged_in.patch("/api/users/1", json={"avatar_url": bad}).status_code == 422
    assert logged_in.patch("/api/users/1", json={"password": "short"}).status_code == 422
    assert logged_in.patch("/api/users/1", json={"password": "no capital or special 9"}).status_code == 422
    assert logged_in.patch("/api/users/1", json={"password": "A brand new pass 9!"}).status_code == 200
    other = TestClient(main.app)
    assert other.post("/api/auth/login", json={"username": "countess_a", "password": USER["password"]}).status_code == 401
    assert other.post("/api/auth/login", json={"username": "countess_a", "password": "A brand new pass 9!"}).status_code == 200


def test_a_taken_username_is_a_409(logged_in, session_factory):
    from app import models

    with session_factory() as s:
        s.add(models.User(email="bob@example.com", username="bob", first_name="B", last_name="B"))
        s.commit()
    assert logged_in.patch("/api/users/1", json={"username": "bob"}).status_code == 409


def test_the_front_page_is_empty_until_a_member_has_found_movies(client):
    assert client.get("/api/movies").json() == []


def test_the_front_page_is_public_and_lists_the_top_movies_by_id_and_name(logged_in, monkeypatch):
    async def fetch(q):
        return FEED

    monkeypatch.setattr(jackett, "fetch_xml", fetch)
    client = logged_in
    client.get("/api/search")  # a member finds the movies: the site knows them
    client.cookies.clear()
    res = client.get("/api/movies")  # no login
    assert res.status_code == 200
    top = res.json()
    assert [m["name"] for m in top][:2] == ["Big Buck Bunny", "Sintel.2010.720p"]
    assert all({"id", "name"} <= set(m) for m in top) and "SECRETKEY" not in res.text and "link" not in top[0]
    assert client.get(f"/api/movies/{top[0]['id']}").status_code == 401  # the details are for members


@pytest.mark.parametrize(
    "method, path, status",
    [
        ("get", "/api/nothing", 404),
        ("delete", "/api/movies/1", 405),
        ("put", "/api/users/1", 405),
        ("post", "/api/users", 405),
        ("delete", "/api/comments", 405),
        ("get", "/api/oauth/token", 405),
    ],
)
def test_any_other_call_is_refused_with_the_right_status(logged_in, method, path, status):
    assert getattr(logged_in, method)(path).status_code == status


@pytest.mark.parametrize("path", ["/avatars/warrior.svg", "/avatars/time-mage.svg", "/avatars/mine.png"])
def test_a_default_avatar_of_the_site_can_be_chosen(logged_in, path):
    assert logged_in.patch("/api/users/1", json={"avatar_url": path}).json()["avatar_url"] == path


@pytest.mark.parametrize(
    "path", ["/avatars/../secret.svg", "/avatars/Warrior.svg", "/api/avatars/2.jpg", "//evil.example/a.svg", "/avatars/a/b.svg", "/avatars/x.html", "/avatars/.svg"]
)
def test_only_the_sites_own_avatar_files_are_accepted_as_paths(logged_in, path):
    assert logged_in.patch("/api/users/1", json={"avatar_url": path}).status_code == 422
