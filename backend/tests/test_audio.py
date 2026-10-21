import asyncio
import json
import shutil
import subprocess

import pytest

from app import engine as engine_module
from app import jackett, main, stream, transcode
from tests.fakes import TORRENT_A, FakeEngine
from tests.test_jackett import FEED

needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which(transcode.FFMPEG) and shutil.which(transcode.FFPROBE)), reason="ffmpeg is not installed"
)


@pytest.fixture(scope="module")
def clips(tmp_path_factory):
    """Real 3-second clips: H.264 with an English (440 Hz) and a French (880 Hz) audio track, in mkv and in mp4, and one without sound."""
    root = tmp_path_factory.mktemp("audio")
    video = ["-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=25"]
    tones = ["-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-f", "lavfi", "-i", "sine=frequency=880:duration=3"]
    maps = ["-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-metadata:s:a:0", "language=eng", "-metadata:s:a:1", "language=fre"]
    run = lambda *args: subprocess.run([transcode.FFMPEG, "-v", "error", "-y", *args], check=True)
    run(*video, *tones, *maps, str(root / "two.mkv"))
    run(*video, *tones, *maps, str(root / "two.mp4"))
    run(*video, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(root / "silent.mp4"))
    return {name: root / f"{name}" for name in ("two.mkv", "two.mp4", "silent.mp4")}


def streams_of(data, tmp_path, entries="stream=codec_type:stream_tags=language:format=duration"):
    path = tmp_path / "out.mp4"
    path.write_bytes(data)
    out = subprocess.run([transcode.FFPROBE, "-v", "error", "-show_entries", entries, "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


@needs_ffmpeg
def test_the_audio_tracks_of_a_file_are_listed_with_their_language(clips):
    tracks = asyncio.run(transcode.probe_audio(stream.FileSource(clips["two.mkv"])))
    assert [(t["index"], t["lang"], t["label"], t["codec"]) for t in tracks] == [(0, "en", "English", "aac"), (1, "fr", "Français", "aac")]
    assert all(t["channels"] == 1 for t in tracks)
    assert asyncio.run(transcode.probe_audio(stream.FileSource(clips["silent.mp4"]))) == []


@needs_ffmpeg
@pytest.mark.parametrize("audio, tag", [(0, "eng"), (1, "fre")])
def test_the_chosen_audio_track_is_the_one_in_the_converted_video(clips, tmp_path, audio, tag):
    async def run():
        return b"".join([c async for c in await transcode.convert(stream.FileSource(clips["two.mkv"]), audio=audio)])
    info = streams_of(asyncio.run(run()), tmp_path)
    audios = [s for s in info["streams"] if s["codec_type"] == "audio"]
    assert len(audios) == 1 and audios[0]["tags"]["language"] == tag


@needs_ffmpeg
def test_the_conversion_can_start_later_in_the_movie(clips, tmp_path):
    async def run():
        return b"".join([c async for c in await transcode.convert(stream.FileSource(clips["two.mkv"]), start=2)])
    duration = float(streams_of(asyncio.run(run()), tmp_path)["format"]["duration"])
    assert 0.4 < duration < 1.6  # about the last second of a 3 second clip


def library_with(logged_in, monkeypatch, tmp_path, clip, name):
    async def fetch_xml(q):
        return FEED

    async def fetch_torrent(link):
        return TORRENT_A

    monkeypatch.setattr(jackett, "fetch_xml", fetch_xml)
    monkeypatch.setattr(jackett, "fetch_torrent", fetch_torrent)
    main.app.dependency_overrides[engine_module.get_engine] = lambda: FakeEngine(tmp_path / "dl", {TORRENT_A: (name, clip.read_bytes())})
    return next(m["id"] for m in logged_in.get("/api/search").json() if m["title"] == "Sintel.2010.720p")


def test_the_audio_routes_are_closed_to_visitors(client):
    assert client.get("/api/movies/1/audio").status_code == 401


@needs_ffmpeg
def test_the_route_lists_the_audio_tracks_of_the_movie(logged_in, clips, monkeypatch, tmp_path):
    movie = library_with(logged_in, monkeypatch, tmp_path, clips["two.mp4"], "movie.mp4")
    tracks = logged_in.get(f"/api/movies/{movie}/audio").json()
    assert [(t["index"], t["lang"]) for t in tracks] == [(0, "en"), (1, "fr")]
    assert logged_in.get("/api/movies/999/audio").status_code == 404


@needs_ffmpeg
def test_another_audio_track_of_an_mp4_comes_through_the_converter(logged_in, clips, monkeypatch, tmp_path):
    movie = library_with(logged_in, monkeypatch, tmp_path, clips["two.mp4"], "movie.mp4")
    plain = logged_in.get(f"/api/movies/{movie}/stream", headers={"Range": "bytes=0-9"})
    assert plain.status_code == 206 and plain.headers["accept-ranges"] == "bytes"  # track 0 of an mp4: played as it is
    other = logged_in.get(f"/api/movies/{movie}/stream", params={"audio": 1})
    assert other.status_code == 200 and other.headers["accept-ranges"] == "none"
    audios = [s for s in streams_of(other.content, tmp_path)["streams"] if s["codec_type"] == "audio"]
    assert [a["tags"]["language"] for a in audios] == ["fre"]


@pytest.mark.parametrize("params", [{"audio": -1}, {"audio": 32}, {"start": -1}, {"start": 90000}])
def test_nonsense_audio_parameters_are_refused(logged_in, monkeypatch, tmp_path, params):
    async def fetch_xml(q):
        return FEED

    monkeypatch.setattr(jackett, "fetch_xml", fetch_xml)
    movie = next(m["id"] for m in logged_in.get("/api/search").json() if m["title"] == "Sintel.2010.720p")
    assert logged_in.get(f"/api/movies/{movie}/stream", params=params).status_code == 422


@pytest.mark.parametrize("name, native", [("movie.mp4", True), ("movie.mkv", False)])
def test_the_sheet_says_whether_the_browser_plays_the_file_as_it_is(logged_in, monkeypatch, tmp_path, name, native):
    clip = tmp_path / "clip.bin"
    clip.write_bytes(b"x" * 100)
    movie = library_with(logged_in, monkeypatch, tmp_path, clip, name)
    assert logged_in.get(f"/api/movies/{movie}").json()["native"] is None  # nothing downloaded yet: the file is unknown
    logged_in.post(f"/api/movies/{movie}/download")
    assert logged_in.get(f"/api/movies/{movie}").json()["native"] is native
