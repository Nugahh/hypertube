import pytest

from app import models, security
from tests.conftest import USER


@pytest.fixture
def bob(logged_in, session_factory):
    """Ada (id 1) is logged in; Bob (id 2) exists."""
    with session_factory() as s:
        s.add(
            models.User(
                email="bob@example.com",
                username="bob",
                first_name="Bob",
                last_name="Builder",
                password_hash=security.hash_password("builder pass 1"),
            )
        )
        s.commit()
    return logged_in


def test_every_users_route_is_closed_to_visitors(client):
    assert client.get("/api/users").status_code == 401
    assert client.get("/api/users/1").status_code == 401
    assert client.patch("/api/users/1", json={}).status_code == 401


def test_the_user_list_only_exposes_id_username_and_picture(bob):
    assert [set(u) for u in bob.get("/api/users").json()] == [{"id", "username", "avatar_url"}] * 2


def test_another_profile_never_shows_the_email(bob):
    profile = bob.get("/api/users/2").json()
    assert profile == {"id": 2, "username": "bob", "first_name": "Bob", "last_name": "Builder", "avatar_url": None}


def test_the_own_profile_shows_the_email(bob):
    assert bob.get("/api/users/1").json()["email"] == "ada@example.com"


def test_an_unknown_profile_is_a_404(bob):
    assert bob.get("/api/users/999").status_code == 404


def test_patch_updates_the_own_profile(bob):
    res = bob.patch(
        "/api/users/1",
        json={"email": "ADA.new@Example.com", "first_name": " Augusta ", "last_name": "King", "language": "fr"},
    )
    assert res.status_code == 200
    assert res.json()["email"] == "ada.new@example.com"
    assert res.json()["first_name"] == "Augusta"
    assert bob.get("/api/auth/me").json()["language"] == "fr"


def test_patch_with_only_some_fields_keeps_the_others(bob):
    assert bob.patch("/api/users/1", json={"language": "fr"}).json()["last_name"] == "Lovelace"


def test_patching_someone_else_is_forbidden_and_changes_nothing(bob):
    assert bob.patch("/api/users/2", json={"first_name": "Hacked"}).status_code == 403
    assert bob.get("/api/users/2").json()["first_name"] == "Bob"


@pytest.mark.parametrize(
    "body",
    [{"language": "xx"}, {"email": "nope"}, {"first_name": "   "}, {"last_name": "x" * 51}, {"username": "a b"}, {"username": "ab"}, {"welcomed": False}],
)
def test_patch_rejects_invalid_values(bob, body):
    assert bob.patch("/api/users/1", json=body).status_code == 422


def test_patch_changes_the_username_and_the_login_follows(bob):
    res = bob.patch("/api/users/1", json={"username": " Ada_New "})
    assert res.status_code == 200
    assert res.json()["username"] == "ada_new"
    bob.post("/api/auth/logout")
    assert bob.post("/api/auth/login", json={"username": "ada_new", "password": USER["password"]}).status_code == 200


def test_patch_rejects_a_username_already_used_whatever_its_case(bob):
    assert bob.patch("/api/users/1", json={"username": "BOB"}).status_code == 409
    assert bob.get("/api/auth/me").json()["username"] == "ada_l"


def test_a_new_account_has_not_seen_the_welcome_page(logged_in):
    assert logged_in.get("/api/auth/me").json()["welcomed"] is False


def test_the_welcome_page_is_done_once_and_for_that_member_only(bob, session_factory):
    res = bob.patch("/api/users/1", json={"username": "ada_2", "welcomed": True})
    assert res.json()["welcomed"] is True
    assert bob.get("/api/auth/me").json()["welcomed"] is True
    with session_factory() as s:
        assert s.get(models.User, 2).welcomed is False


def test_patch_rejects_an_email_already_used_by_someone_else(bob):
    assert bob.patch("/api/users/1", json={"email": "BOB@example.com"}).status_code == 409


def test_patch_cannot_set_fields_it_does_not_expose(bob, session_factory):
    # the picture URL and the username are editable (the subject's PATCH /users/:id), the id and the stored hash are not
    bob.patch("/api/users/1", json={"id": 99, "password_hash": "x", "created_at": "2000-01-01"})
    with session_factory() as s:
        user = s.get(models.User, 1)
        assert user.password_hash.startswith("$argon2id$")
        assert user.created_at.year != 2000
    assert bob.get("/api/auth/me").json()["id"] == 1
