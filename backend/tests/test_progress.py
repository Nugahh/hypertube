import pytest
from fastapi.testclient import TestClient

from app import main
from tests.test_continue import seen, titles  # noqa: F401  (Ada has the films of the feed in her library)
from tests.test_shelves import BOB

METRO = "Metropolis.1927.1080p"


def played(client):
    return {m["title"]: m["played"] for m in client.get("/api/continue").json()}


def save(client, movie_id, position, duration):
    return client.put(f"/api/movies/{movie_id}/progress", json={"position": position, "duration": duration})


def test_saving_a_position_is_closed_to_visitors(client):
    assert client.put("/api/movies/1/progress", json={"position": 1, "duration": 2}).status_code == 401


def test_the_position_is_kept_and_follows_the_film(seen):
    seen.watch(METRO)
    assert played(seen) == {METRO: None}  # nothing saved yet: no bar
    assert save(seen, seen.ids[METRO], 30, 120).status_code == 204
    assert played(seen) == {METRO: 0.25}
    save(seen, seen.ids[METRO], 90, 120)
    assert played(seen) == {METRO: 0.75}


def test_a_film_watched_to_the_end_leaves_continue_watching(seen):
    seen.watch(METRO)
    seen.watch("Dracula 1958")
    save(seen, seen.ids[METRO], 119, 120)
    assert titles(seen) == ["Dracula 1958"]


def test_the_copy_played_last_gives_the_position_of_the_film(seen):
    [card] = [m for m in seen.get("/api/search", params={"limit": 100}).json() if m["title"] == METRO]
    best, other = [s["id"] for s in card["sources"]]
    seen.watch(best)
    seen.watch(other)
    save(seen, best, 10, 100)
    save(seen, other, 40, 100)
    assert played(seen) == {METRO: 0.4}


@pytest.mark.parametrize("body", [{"position": -1, "duration": 100}, {"position": 5, "duration": 0}, {"position": 1e9, "duration": 100}, {"duration": 100}, {"position": "x", "duration": 100}])
def test_nonsense_positions_are_refused(seen, body):
    assert seen.put(f"/api/movies/{seen.ids[METRO]}/progress", json=body).status_code == 422


def test_an_unknown_film_is_a_404(seen):
    assert save(seen, 999, 1, 2).status_code == 404


def test_each_member_has_their_own_position(seen):
    seen.watch(METRO)
    bob = TestClient(main.app)
    assert bob.post("/api/auth/register", json={**BOB, "email": "carol@example.com", "username": "carol"}).status_code == 201
    save(bob, seen.ids[METRO], 100, 120)
    assert played(seen) == {METRO: None}
