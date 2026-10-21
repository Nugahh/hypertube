import pytest

from app import opensubtitles, subtitles
from tests.test_movies import library, sintel  # noqa: F401  (Jackett's sample feed + fake downloads)

SRT = b"1\n00:00:01,000 --> 00:00:02,500\nHello, world\n\n2\n00:00:03,000 --> 00:00:04,000\nBye\n"


def upload(client, mid, data=SRT, name="my.fr.srt", lang=None):
    form = {"lang": lang} if lang else {}
    return client.post(f"/api/movies/{mid}/subtitles", files={"file": (name, data)}, data=form)


def refs(client, mid):
    return [(s["ref"], s["lang"], s["source"]) for s in client.get(f"/api/movies/{mid}/subtitles").json()]


def test_importing_is_closed_to_visitors(client):
    assert client.post("/api/movies/1/subtitles", files={"file": ("a.srt", SRT)}).status_code == 401
    assert client.delete("/api/movies/1/subtitles/1").status_code == 401
    assert client.get("/api/movies/1/subtitles/search").status_code == 401
    assert client.post("/api/movies/1/subtitles/opensubtitles", json={"file_id": 1, "lang": "en"}).status_code == 401


def test_a_member_imports_an_srt_and_everyone_gets_it_as_webvtt(library):  # noqa: F811
    mid = sintel(library)
    res = upload(library, mid)
    assert res.status_code == 201
    body = res.json()
    assert (body["lang"], body["source"], body["mine"]) == ("fr", "upload", True)  # the language comes from the file name
    assert res.headers["location"] == f"/api/movies/{mid}/subtitles/{body['ref']}"
    assert refs(library, mid) == [(body["ref"], "fr", "upload")]
    vtt = library.get(f"/api/movies/{mid}/subtitles/{body['ref']}")
    assert vtt.headers["content-type"].startswith("text/vtt") and vtt.headers["x-content-type-options"] == "nosniff"
    assert vtt.text.startswith("WEBVTT") and "00:00:01.000 --> 00:00:02.500" in vtt.text


def test_the_language_can_be_chosen_when_the_name_does_not_say(library):  # noqa: F811
    mid = sintel(library)
    assert upload(library, mid, name="subtitles.srt").status_code == 422
    assert upload(library, mid, name="subtitles.srt", lang="de").json()["lang"] == "de"
    assert upload(library, mid, name="subtitles.srt", lang="xx").status_code == 422


@pytest.mark.parametrize("data", [b"just some text", b"", b"\x00\x01\x02" * 100])
def test_a_file_that_is_not_a_subtitle_file_is_refused(library, data):  # noqa: F811
    assert upload(library, sintel(library), data=data).status_code == 415


def test_a_huge_file_is_refused(library):  # noqa: F811
    assert upload(library, sintel(library), data=SRT * 100_000).status_code == 413


def test_a_movie_keeps_at_most_ten_imported_subtitles(library):  # noqa: F811
    mid = sintel(library)
    assert all(upload(library, mid).status_code == 201 for _ in range(10))
    assert upload(library, mid).status_code == 409


def test_only_the_member_who_imported_a_subtitle_deletes_it(library):  # noqa: F811
    from fastapi.testclient import TestClient

    from app import main

    mid = sintel(library)
    ref = upload(library, mid).json()["ref"]
    other = TestClient(main.app)
    other.post("/api/auth/register", json={"email": "b@example.com", "username": "bob", "first_name": "B", "last_name": "B", "password": "Builder pass 1!"})
    assert other.delete(f"/api/movies/{mid}/subtitles/{ref}").status_code == 403
    assert [s["mine"] for s in other.get(f"/api/movies/{mid}/subtitles").json()] == [False]
    assert library.delete(f"/api/movies/{mid}/subtitles/{ref}").status_code == 204
    assert library.get(f"/api/movies/{mid}/subtitles/{ref}").status_code == 404
    assert library.delete(f"/api/movies/{mid}/subtitles/{ref}").status_code == 404


def test_the_list_mixes_torrent_and_imported_subtitles_english_first(library):  # noqa: F811
    library.engine.subs = {"Sintel.en.srt": (SRT, True), "Sintel.fr.srt": (SRT, True)}
    mid = sintel(library)
    library.post(f"/api/movies/{mid}/download")
    extra = upload(library, mid, name="x.de.srt").json()["ref"]
    expected = [("en", "en", "torrent"), (extra, "de", "upload"), ("fr", "fr", "torrent")]  # English, then by language code
    assert refs(library, mid) == expected
    assert [s["ref"] for s in library.get(f"/api/movies/{mid}").json()["subtitles"]] == [r for r, _, _ in expected]  # the sheet too


def test_a_language_code_also_finds_an_imported_subtitle(library):  # noqa: F811
    mid = sintel(library)
    upload(library, mid, name="a.fr.srt")
    assert library.get(f"/api/movies/{mid}/subtitles/fr").text.startswith("WEBVTT")
    assert library.get(f"/api/movies/{mid}/subtitles/de").status_code == 404
    assert library.get(f"/api/movies/{mid}/subtitles/999").status_code == 404


@pytest.fixture
def opensub(monkeypatch):
    monkeypatch.setenv("OPENSUBTITLES_API_KEY", "osk")
    fake = type("Fake", (), {"asked": [], "downloaded": []})()

    async def search(query, lang, tmdb_id=None, year=None):
        fake.asked.append((query, lang, tmdb_id, year))
        return [{"file_id": 7, "lang": lang, "release": "Sintel.BluRay", "downloads": 10, "title": "Sintel", "year": 2010}]

    async def download(file_id):
        fake.downloaded.append(file_id)
        return SRT

    monkeypatch.setattr(opensubtitles, "search", search)
    monkeypatch.setattr(opensubtitles, "download", download)
    return fake


def test_opensubtitles_results_for_a_movie(library, opensub):  # noqa: F811
    mid = sintel(library)
    res = library.get(f"/api/movies/{mid}/subtitles/search", params={"lang": "fr"})
    assert res.status_code == 200 and res.json() == [{"file_id": 7, "lang": "fr", "release": "Sintel.BluRay", "downloads": 10, "title": "Sintel", "year": 2010}]
    assert opensub.asked == [("Sintel", "fr", None, 2010)]  # the name without year and resolution, and the year
    assert library.get(f"/api/movies/{mid}/subtitles/search", params={"lang": "xx"}).status_code == 422


def test_an_opensubtitles_subtitle_is_downloaded_once_and_kept(library, opensub):  # noqa: F811
    mid = sintel(library)
    res = library.post(f"/api/movies/{mid}/subtitles/opensubtitles", json={"file_id": 7, "lang": "fr", "release": "Sintel.BluRay"})
    assert res.status_code == 201 and (res.json()["source"], res.json()["label"]) == ("opensubtitles", "Sintel.BluRay")
    assert library.get(f"/api/movies/{mid}/subtitles/{res.json()['ref']}").text.startswith("WEBVTT")
    assert opensub.downloaded == [7]


def test_without_a_key_opensubtitles_is_a_501_and_a_failure_a_502(library, monkeypatch, opensub):  # noqa: F811
    mid = sintel(library)
    monkeypatch.setenv("OPENSUBTITLES_API_KEY", "")
    assert library.get(f"/api/movies/{mid}/subtitles/search").status_code == 501
    assert library.post(f"/api/movies/{mid}/subtitles/opensubtitles", json={"file_id": 7, "lang": "fr"}).status_code == 501
    monkeypatch.setenv("OPENSUBTITLES_API_KEY", "osk")

    async def broken(*args, **kwargs):
        raise opensubtitles.OpenSubtitlesError("OpenSubtitles unavailable")

    monkeypatch.setattr(opensubtitles, "search", broken)
    assert library.get(f"/api/movies/{mid}/subtitles/search").status_code == 502


def test_an_opensubtitles_answer_that_is_not_a_subtitle_is_refused(library, monkeypatch, opensub):  # noqa: F811
    async def junk(file_id):
        return b"<html>quota exceeded</html>"

    monkeypatch.setattr(opensubtitles, "download", junk)
    res = library.post(f"/api/movies/{sintel(library)}/subtitles/opensubtitles", json={"file_id": 7, "lang": "fr"})
    assert res.status_code == 502


def test_a_used_up_quota_is_a_429_with_its_own_message(library, monkeypatch, opensub):  # noqa: F811
    async def refused(file_id):
        raise opensubtitles.OpenSubtitlesQuota("OpenSubtitles download quota reached")

    monkeypatch.setattr(opensubtitles, "download", refused)
    res = library.post(f"/api/movies/{sintel(library)}/subtitles/opensubtitles", json={"file_id": 7, "lang": "fr"})
    assert res.status_code == 429 and "quota" in res.json()["detail"]
