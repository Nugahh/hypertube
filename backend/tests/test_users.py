import io

import pytest
from PIL import Image

from app import models, security, users
from tests.conftest import USER


@pytest.fixture(autouse=True)
def avatar_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(users, "AVATAR_DIR", tmp_path / "avatars")


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


def png(size=(600, 400), color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def upload(client, content, name="me.png", mime="image/png"):
    return client.post("/api/users/me/avatar", files={"file": (name, content, mime)})


def test_every_users_route_is_closed_to_visitors(client):
    assert client.get("/api/users").status_code == 401
    assert client.get("/api/users/1").status_code == 401
    assert client.patch("/api/users/1", json={}).status_code == 401
    assert client.post("/api/users/me/avatar").status_code == 401
    assert client.get("/api/avatars/1.jpg").status_code == 401


def test_the_user_list_only_exposes_id_and_username(bob):
    assert bob.get("/api/users").json() == [{"id": 1, "username": "ada_l"}, {"id": 2, "username": "bob"}]


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
    [{"language": "xx"}, {"email": "nope"}, {"first_name": "   "}, {"last_name": "x" * 51}],
)
def test_patch_rejects_invalid_values(bob, body):
    assert bob.patch("/api/users/1", json=body).status_code == 422


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


def test_an_uploaded_photo_becomes_a_small_square_jpeg(bob):
    res = upload(bob, png())
    assert res.status_code == 200
    url = res.json()["avatar_url"]
    assert url.startswith("/api/avatars/1.jpg")
    served = bob.get(url.split("?")[0])
    assert served.headers["content-type"] == "image/jpeg"
    image = Image.open(io.BytesIO(served.content))
    assert (image.format, image.size) == ("JPEG", (256, 256))


def test_a_file_that_is_not_an_image_is_refused(bob):
    assert upload(bob, b"just some text", "me.png").status_code == 415


def test_an_svg_with_a_script_is_refused(bob):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    assert upload(bob, svg, "me.svg", "image/svg+xml").status_code == 415


def test_a_photo_over_2_mb_is_refused(bob):
    assert upload(bob, b"\0" * (2 * 1024 * 1024 + 1)).status_code == 413


def test_the_avatar_route_only_serves_avatar_files(bob):
    assert bob.get("/api/avatars/2.jpg").status_code == 404  # nothing uploaded for user 2
    assert bob.get("/api/avatars/secret.txt").status_code == 404
    assert bob.get("/api/avatars/..%2Fusers.py").status_code == 404
