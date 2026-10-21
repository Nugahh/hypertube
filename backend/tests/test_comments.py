import pytest
from fastapi.testclient import TestClient

from app import main, models

BOB = {"email": "bob@example.com", "username": "bob", "first_name": "Bob", "last_name": "Builder", "password": "builder pass 1"}


@pytest.fixture
def movie(session_factory):
    with session_factory() as s:
        m = models.Movie(source_id="m1", title="Sintel 2010", size=1, seeders=1, peers=1, provider="p", link="l", status="idle")
        s.add(m)
        s.commit()
        return m.id


@pytest.fixture
def bob(logged_in):
    """A second browser, logged in as Bob (Ada is logged in on `logged_in`)."""
    other = TestClient(main.app)
    assert other.post("/api/auth/register", json=BOB).status_code == 201
    return other


def post(client, movie, text="Great film"):
    return client.post(f"/api/movies/{movie}/comments", json={"comment": text})


def test_every_comment_route_is_closed_to_visitors(client, movie):
    assert client.get("/api/comments").status_code == 401
    assert client.get("/api/comments/1").status_code == 401
    assert client.post("/api/comments", json={"comment": "x", "movie_id": movie}).status_code == 401
    assert client.get(f"/api/movies/{movie}/comments").status_code == 401
    assert client.post(f"/api/movies/{movie}/comments", json={"comment": "x"}).status_code == 401
    assert client.patch("/api/comments/1", json={"comment": "x"}).status_code == 401
    assert client.delete("/api/comments/1").status_code == 401


def test_a_member_comments_a_movie(logged_in, movie):
    res = post(logged_in, movie)
    assert res.status_code == 201
    body = res.json()
    assert res.headers["location"] == f"/api/comments/{body['id']}"
    assert (body["username"], body["content"], body["movie_id"]) == ("ada_l", "Great film", movie)
    assert body["date"] and body["user_id"] == 1


def test_the_flat_post_route_takes_the_movie_in_the_payload(logged_in, movie):
    res = logged_in.post("/api/comments", json={"comment": "Hello", "movie_id": movie})
    assert res.status_code == 201 and res.json()["movie_id"] == movie


def test_commenting_an_unknown_movie_is_a_404(logged_in):
    assert post(logged_in, 999).status_code == 404
    assert logged_in.post("/api/comments", json={"comment": "x", "movie_id": 999}).status_code == 404
    assert logged_in.get("/api/movies/999/comments").status_code == 404


@pytest.mark.parametrize("text", ["", "   ", "x" * 1001])
def test_a_comment_must_have_1_to_1000_characters(logged_in, movie, text):
    assert post(logged_in, movie, text).status_code == 422


def test_comments_are_listed_newest_first_per_movie_and_overall(logged_in, bob, movie):
    post(logged_in, movie, "first")
    post(bob, movie, "second")
    assert [c["content"] for c in logged_in.get(f"/api/movies/{movie}/comments").json()] == ["second", "first"]
    latest = logged_in.get("/api/comments", params={"limit": 1}).json()
    assert [(c["content"], c["username"]) for c in latest] == [("second", "bob")]
    assert logged_in.get("/api/comments", params={"limit": 0}).status_code == 422


def test_one_comment_can_be_read(logged_in, movie):
    cid = post(logged_in, movie).json()["id"]
    assert logged_in.get(f"/api/comments/{cid}").json()["content"] == "Great film"
    assert logged_in.get("/api/comments/999").status_code == 404


def test_only_the_author_edits_a_comment(logged_in, bob, movie):
    cid = post(logged_in, movie).json()["id"]
    assert bob.patch(f"/api/comments/{cid}", json={"comment": "hacked"}).status_code == 403
    res = logged_in.patch(f"/api/comments/{cid}", json={"comment": "Better", "username": "ada_l"})
    assert res.status_code == 200 and res.json()["content"] == "Better" and res.json()["edited"] is True
    # the username in the payload cannot be used to speak as someone else
    assert logged_in.patch(f"/api/comments/{cid}", json={"comment": "x", "username": "bob"}).status_code == 403
    assert logged_in.get(f"/api/comments/{cid}").json()["content"] == "Better"


def test_only_the_author_deletes_a_comment(logged_in, bob, movie):
    cid = post(logged_in, movie).json()["id"]
    assert bob.delete(f"/api/comments/{cid}").status_code == 403
    assert logged_in.get(f"/api/comments/{cid}").status_code == 200
    assert logged_in.delete(f"/api/comments/{cid}").status_code == 204
    assert logged_in.get(f"/api/comments/{cid}").status_code == 404
    assert logged_in.delete(f"/api/comments/{cid}").status_code == 404


def test_the_movie_sheet_counts_its_comments(logged_in, movie):
    assert logged_in.get(f"/api/movies/{movie}").json()["comments"] == 0
    post(logged_in, movie)
    post(logged_in, movie)
    assert logged_in.get(f"/api/movies/{movie}").json()["comments"] == 2
