import asyncio
import time

import pytest

from app import engine as engine_module
from app import subtitles
from tests.swarm import noise, seed
from tests.test_movies import library, sintel  # noqa: F401  (the sample library with a fake download engine)

SRT = b"1\n00:00:01,000 --> 00:00:02,500\nHello, world\n\n2\n00:00:03,000 --> 00:00:04,000\nBye\n"


@pytest.mark.parametrize(
    "path, lang",
    [
        ("pack/Sintel.fr.srt", "fr"),
        ("pack/Big Buck Bunny.en.srt", "en"),
        ("Subs/English.srt", "en"),
        ("pack/Movie.FRE.srt", "fr"),
        ("It.2017.en.srt", "en"),  # "it" in the title is not Italian
        ("Subs/French/2_Track.srt", "fr"),
        ("pack/movie.srt", None),
    ],
)
def test_the_language_comes_from_the_file_name(path, lang):
    assert subtitles.language_of(path) == lang


def test_an_srt_becomes_webvtt_without_touching_the_text():
    vtt = subtitles.to_vtt(SRT)
    assert vtt.startswith("WEBVTT\n\n")
    assert "00:00:01.000 --> 00:00:02.500" in vtt and "Hello, world" in vtt


def test_a_vtt_is_kept_and_odd_encodings_are_read():
    assert subtitles.to_vtt(b"WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHi\n").count("WEBVTT") == 1
    assert "café" in subtitles.to_vtt("1\n00:00:01,000 --> 00:00:02,000\ncafé\n".encode("cp1252"))
    assert "café" in subtitles.to_vtt(b"\xef\xbb\xbf1\n00:00:01,000 --> 00:00:02,000\ncaf\xc3\xa9\n")  # utf-8 with a BOM


def start(client, with_subs):
    client.engine.subs = with_subs
    mid = sintel(client)
    assert client.post(f"/api/movies/{mid}/download").status_code == 200
    return mid


def test_a_movie_nobody_started_has_no_subtitles_yet(library):  # noqa: F811
    assert library.get(f"/api/movies/{sintel(library)}/subtitles").json() == []


def test_the_downloaded_subtitles_are_listed_and_served_as_webvtt(library):  # noqa: F811
    mid = start(library, {"Sintel.fr.srt": (SRT, True), "Sintel.en.srt": (SRT, True), "notes.txt": (b"x", True)})
    listed = library.get(f"/api/movies/{mid}/subtitles").json()
    assert [(s["ref"], s["lang"], s["label"], s["source"]) for s in listed] == [("en", "en", "English", "torrent"), ("fr", "fr", "Français", "torrent")]
    res = library.get(f"/api/movies/{mid}/subtitles/fr")
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/vtt")
    assert res.text.startswith("WEBVTT") and "00:00:01.000 --> 00:00:02.500" in res.text
    assert library.get(f"/api/movies/{mid}/subtitles/de").status_code == 404
    assert library.get(f"/api/movies/{mid}/subtitles/f").status_code == 422  # not a language code
    assert [s["lang"] for s in library.get(f"/api/movies/{mid}").json()["subtitles"]] == ["en", "fr"]


def test_a_subtitle_still_downloading_is_not_offered(library):  # noqa: F811
    mid = start(library, {"Sintel.en.srt": (SRT, True), "Sintel.fr.srt": (b"", False)})
    assert [s["lang"] for s in library.get(f"/api/movies/{mid}/subtitles").json()] == ["en"]


def test_subtitles_are_still_there_once_the_download_is_finished_and_the_torrent_stopped(library):  # noqa: F811
    mid = start(library, {"Sintel.en.srt": (SRT, True)})
    assert library.get(f"/api/movies/{mid}").json()["state"] == "ready"  # the fake torrent is complete: it is dropped
    assert library.engine.removed
    assert [s["lang"] for s in library.get(f"/api/movies/{mid}/subtitles").json()] == ["en"]
    assert library.get(f"/api/movies/{mid}/subtitles/en").text.startswith("WEBVTT")


def test_the_engine_also_downloads_the_subtitle_files_of_the_torrent(tmp_path):
    video, srt = noise(150_000, 1), SRT * 20
    torrent_bytes, address, seeder = seed(tmp_path, {"movie.mp4": video, "movie.en.srt": srt, "poster.jpg": noise(90_000, 3)})
    engine = engine_module.Engine(tmp_path / "downloads", listen="127.0.0.1:0", dht=False)
    try:
        torrent = engine.add(torrent_bytes, peers=[address])
        deadline = time.time() + 30
        while time.time() < deadline and not (torrent.subtitle_files() and torrent.subtitle_files()[0][1]):
            time.sleep(0.2)
        [(path, complete)] = torrent.subtitle_files()
        assert path.endswith("movie.en.srt") and complete
        assert (engine.download_dir / path).read_bytes() == srt
    finally:
        engine.shutdown()
        del seeder


def test_a_subtitle_is_offered_only_once_its_file_is_on_the_disk(tmp_path):
    # libtorrent can report a piece as complete a moment before the file exists: the player would get a 404
    torrent_bytes, address, seeder = seed(tmp_path, {"movie.mp4": noise(150_000, 1), "movie.en.srt": SRT})
    engine = engine_module.Engine(tmp_path / "downloads", listen="127.0.0.1:0", dht=False)
    try:
        torrent = engine.add(torrent_bytes, peers=[address])
        deadline = time.time() + 30
        while time.time() < deadline and not (torrent.subtitle_files() and torrent.subtitle_files()[0][1]):
            time.sleep(0.2)
        [(path, complete)] = torrent.subtitle_files()
        assert complete
        (engine.download_dir / path).unlink()
        assert torrent.subtitle_files() == [(path, False)]
        assert not torrent.is_complete  # nor is the torrent finished while a wanted file is missing
    finally:
        engine.shutdown()
        del seeder
