from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app import models, security
from tests.conftest import USER


def register(client, **changes):
    return client.post("/api/auth/register", json={**USER, **changes})


def test_register_returns_the_account_without_its_password_and_logs_in(client):
    res = register(client)
    assert res.status_code == 201
    assert res.json() == {
        "id": 1,
        "email": "ada@example.com",  # emails and usernames are stored lower case
        "username": "ada_l",
        "first_name": "Ada",
        "last_name": "Lovelace",
        "language": "en",
        "avatar_url": None,
        "welcomed": False,
    }
    assert client.get("/api/auth/me").json()["username"] == "ada_l"


def test_the_password_is_stored_hashed_never_in_clear(client, session_factory):
    register(client)
    with session_factory() as s:
        stored = s.get(models.User, 1).password_hash
    assert USER["password"] not in stored
    assert stored.startswith("$argon2id$")


def test_the_session_cookie_is_httponly_and_samesite(client):
    cookie = register(client).headers["set-cookie"].lower()
    assert "session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie


@pytest.mark.parametrize(
    "changes",
    [
        {"password": "short1"},  # under 8 characters
        {"password": "onlyletters"},  # no digit
        {"password": "12345678"},  # no letter
        {"password": "all lower 9!"},  # no capital letter
        {"password": "No Special 9"},  # no special character (a space is not one)
        {"password": "No Digit here!"},
        {"email": "not-an-email"},
        {"username": "a"},  # too short
        {"username": "bad name!"},  # characters outside a-z 0-9 _
        {"first_name": "   "},
        {"last_name": ""},
    ],
)
def test_register_rejects_invalid_fields(client, changes):
    assert register(client, **changes).status_code == 422


@pytest.mark.parametrize("password", ["Str0ng!pass", "Un_derscore9", "Ünïcode 9é€", "a Very-long pass 1" * 5])
def test_register_accepts_a_password_with_a_capital_a_digit_and_a_special_character(client, password):
    assert register(client, password=password).status_code == 201


def test_an_account_with_an_older_weaker_password_can_still_log_in(client, session_factory):
    with session_factory() as s:
        s.add(models.User(email="old@example.com", username="old_timer", first_name="O", last_name="T", password_hash=security.hash_password("weak legacy 1")))
        s.commit()
    assert client.post("/api/auth/login", json={"username": "old_timer", "password": "weak legacy 1"}).status_code == 200


def test_register_rejects_a_taken_email_or_username_whatever_the_case(client):
    register(client)
    assert register(client, username="other", email="ADA@example.com").status_code == 409
    assert register(client, email="other@example.com", username="ADA_L").status_code == 409


def test_me_is_null_for_a_visitor_so_the_browser_console_stays_clean(client):
    res = client.get("/api/auth/me")
    assert res.status_code == 200
    assert res.json() is None


def test_login_with_username_and_password_then_logout_in_one_call(client):
    register(client)
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").json() is None

    res = client.post("/api/auth/login", json={"username": "Ada_L", "password": USER["password"]})
    assert res.status_code == 200
    assert client.get("/api/auth/me").json()["username"] == "ada_l"

    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").json() is None


def test_login_failures_do_not_reveal_whether_the_username_exists(client):
    register(client)
    wrong_password = client.post("/api/auth/login", json={"username": "ada_l", "password": "nope nope 1"})
    unknown_user = client.post("/api/auth/login", json={"username": "ghost", "password": "nope nope 1"})
    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()


def test_a_tampered_session_cookie_is_rejected(client):
    register(client)
    client.cookies.set("session", "forged.token.value")
    assert client.get("/api/auth/me").json() is None
    assert client.get("/api/downloads").status_code == 401


def test_an_expired_session_is_rejected(client):
    register(client)
    expired = jwt.encode(
        {"sub": "1", "exp": datetime.now(timezone.utc) - timedelta(seconds=1)}, security.SECRET_KEY, algorithm="HS256"
    )
    client.cookies.set("session", expired)
    assert client.get("/api/auth/me").json() is None


def test_an_oauth_account_without_password_cannot_log_in_with_one(client, session_factory):
    with session_factory() as s:
        s.add(models.User(email="o@example.com", username="oauth_user", first_name="O", last_name="Auth"))
        s.commit()
    for password in ("", "anything 1", "dummy password"):
        res = client.post("/api/auth/login", json={"username": "oauth_user", "password": password})
        assert res.status_code == 401


def test_a_session_for_a_deleted_account_is_rejected(client, session_factory):
    register(client)
    with session_factory() as s:
        s.delete(s.get(models.User, 1))
        s.commit()
    assert client.get("/api/auth/me").json() is None
    assert client.get("/api/downloads").status_code == 401
