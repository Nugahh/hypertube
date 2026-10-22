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


def card(client, title=METRO):
    return next(m for m in client.get("/api/search", params={"limit": 100}).json() if m["title"] == title)


def test_a_thumbnail_says_where_the_member_stopped(seen):
    assert (card(seen)["resume"], card(seen)["finished"]) == (None, False)
    save(seen, seen.ids[METRO], 30, 120)
    assert card(seen)["resume"] == {"id": seen.ids[METRO], "position": 30, "duration": 120} and card(seen)["finished"] is False


def test_the_copy_the_member_watched_is_the_one_the_film_resumes_on(seen):
    best, other = [s["id"] for s in card(seen)["sources"]]
    save(seen, other, 50, 100)
    assert card(seen)["resume"]["id"] == other  # the thumbnail is the best copy, the position belongs to the other one
    save(seen, best, 10, 100)  # watched later
    assert card(seen)["resume"] == {"id": best, "position": 10, "duration": 100}


def test_a_film_watched_to_the_end_starts_again_from_the_beginning(seen):
    save(seen, seen.ids[METRO], 119, 120)
    assert (card(seen)["resume"], card(seen)["finished"]) == (None, True)
