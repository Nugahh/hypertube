import pytest

from app import picker

GB = 1024**3


def result(title, seeders=50, peers=20, size=2 * GB, provider="A"):
    return {"id": f"{provider}:{title}", "title": title, "seeders": seeders, "peers": peers, "size": size, "provider": provider}


def titles(results):
    return [r["title"] for r in results]


def test_cinema_recordings_are_dropped():
    found = [result("Film.2020.CAM"), result("Film 2020 TS"), result("Film.2020.TELESYNC"), result("Film.2020.SCREENER"), result("Film.2020.1080p.WEB")]
    assert titles(picker.pick(found)) == ["Film.2020.1080p.WEB"]
    assert picker.pick([result("Camera.Obscura.1080p")]) != []  # CAM is a word, not a part of one


def test_the_same_release_from_two_providers_is_one_and_the_best_seeded_stays():
    found = [result("Film.2020.1080p.BluRay", seeders=20, provider="A"), result("Film 2020 1080p BluRay", seeders=90, provider="B"), result("Film.2020.1080p.BluRay", seeders=5, provider="C", size=3 * GB)]
    assert [(r["provider"], r["seeders"]) for r in picker.pick(found)] == [("B", 90), ("C", 5)]  # another size is another release


def test_the_resolutions_come_4k_then_1080p_then_the_rest_and_three_of_each():
    found = [result(f"Film.2020.1080p.v{i}", seeders=100 + i) for i in range(5)]
    found += [result("Film.2020.2160p.HDR"), result("Film.2020.4K.WEB"), result("Film.2020.720p"), result("Film.2020.DVDRip", seeders=60)]
    picked = titles(picker.pick(found))
    assert picked[:2] == ["Film.2020.2160p.HDR", "Film.2020.4K.WEB"]  # same score: the order they came in
    assert picked[2:5] == ["Film.2020.1080p.v4", "Film.2020.1080p.v3", "Film.2020.1080p.v2"]  # the best seeded first
    assert sorted(picked[5:]) == ["Film.2020.720p", "Film.2020.DVDRip"]
    assert len(picked) == 7


@pytest.mark.parametrize(
    "title, expected",
    [("Film.2020.2160p.HDR", "4K"), ("Film 2020 4K WEB", "4K"), ("Film.2020.1080p.WEB", "1080p"), ("Film.2020.720p", "720p"), ("Film.2020.DVDRip", "720p")],
)
def test_a_release_is_listed_under_its_quality(title, expected):
    assert picker.tier(title) == expected


def test_a_well_seeded_film_sized_copy_beats_a_poor_one():
    good, few, huge = (result("good", seeders=80, peers=40, size=3 * GB), result("few", seeders=2, peers=40, size=3 * GB), result("huge", seeders=80, peers=40, size=15 * GB))
    assert picker.score(good) > picker.score(huge) > picker.score(few)


def test_x265_and_a_swarm_with_leechers_score_higher():
    assert picker.score(result("Film x265", peers=20)) == picker.score(result("Film", peers=20)) + 150
    assert picker.score(result("Film", seeders=50, peers=0)) < picker.score(result("Film", seeders=50, peers=20))  # nobody else downloading


def test_nothing_found_is_nothing_picked():
    assert picker.pick([]) == []
