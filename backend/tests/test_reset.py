import re
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app import mail, models, security
from tests.conftest import USER


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(mail, "send_email", lambda to, subject, body: sent.append((to, subject, body)))
    return sent


def token_from(mail_body):
    return re.search(r"/reset-password\?token=([\w.\-]+)", mail_body)[1]


def login(client, password):
    return client.post("/api/auth/login", json={"username": USER["username"], "password": password})


def reset(client, token, password="brand new pass 7"):
    return client.post("/api/auth/reset", json={"token": token, "password": password})


@pytest.fixture
def account(client):
    client.post("/api/auth/register", json=USER)
    client.post("/api/auth/logout")
    return client


def forgot(client, email=USER["email"]):
    return client.post("/api/auth/forgot", json={"email": email})


def test_forgot_emails_a_reset_link_to_the_account(account, outbox):
    assert forgot(account).status_code == 202
    [(to, subject, body)] = outbox
    assert to == "ada@example.com"
    assert "/reset-password?token=" in body


def test_forgot_answers_the_same_whether_or_not_the_account_exists(account, outbox):
    known = forgot(account)
    unknown = forgot(account, "nobody@example.com")
    assert (known.status_code, known.json()) == (unknown.status_code, unknown.json())
    assert len(outbox) == 1  # only the real account got an email


def test_the_reset_email_follows_the_language_of_the_account(account, outbox, session_factory):
    with session_factory() as s:
        s.get(models.User, 1).language = "fr"
        s.commit()
    forgot(account)
    assert "mot de passe" in outbox[0][1].lower()


def test_the_link_sets_a_new_password(account, outbox):
    forgot(account)
    assert reset(account, token_from(outbox[0][2])).status_code == 204
    assert login(account, "brand new pass 7").status_code == 200
    assert login(account, USER["password"]).status_code == 401


def test_the_link_works_only_once(account, outbox):
    forgot(account)
    token = token_from(outbox[0][2])
    assert reset(account, token).status_code == 204
    assert reset(account, token, "another pass 99").status_code == 400
    assert login(account, "brand new pass 7").status_code == 200


def test_an_expired_link_is_refused(account, outbox):
    forgot(account)
    token = token_from(outbox[0][2])
    claims = jwt.decode(token, security.SECRET_KEY, algorithms=["HS256"])
    claims["exp"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    expired = jwt.encode(claims, security.SECRET_KEY, algorithm="HS256")
    assert reset(account, expired).status_code == 400


def test_a_weak_new_password_is_refused_and_the_link_stays_usable(account, outbox):
    forgot(account)
    token = token_from(outbox[0][2])
    assert reset(account, token, "weak").status_code == 422
    assert reset(account, token).status_code == 204


def test_a_session_token_is_not_a_reset_link(account):
    assert reset(account, security.create_token(1)).status_code == 400
    assert reset(account, "garbage").status_code == 400


def test_a_reset_token_is_not_a_session(account, outbox):
    forgot(account)
    account.cookies.set("session", token_from(outbox[0][2]))
    assert account.get("/api/auth/me").json() is None
