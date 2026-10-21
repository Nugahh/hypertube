import asyncio
import json
import os
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


def test_h264_is_repackaged_and_everything_else_is_reencoded():
    assert transcode.video_args("h264") == ["-c:v", "copy"]
    for codec in ("hevc", "mpeg4", "vp9", "wmv3", None):
        args = transcode.video_args(codec)
        assert "libx264" in args and "copy" not in args


@pytest.fixture(scope="module")
def videos(tmp_path_factory):
    """Real 3-second clips: an mkv with H.264 + AAC, and an avi with MPEG-4 video."""
    root = tmp_path_factory.mktemp("clips")
    lavfi = ["-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=25", "-f", "lavfi", "-i", "sine=frequency=440:duration=3"]
    run = lambda *args: subprocess.run([transcode.FFMPEG, "-v", "error", "-y", *args], check=True)
    run(*lavfi, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(root / "clip.mkv"))
    run("-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=25", "-c:v", "mpeg4", str(root / "clip.avi"))
    return {"mkv": root / "clip.mkv", "avi": root / "clip.avi"}


def probe(data, tmp_path):
    path = tmp_path / "out.mp4"
    path.write_bytes(data)
    out = subprocess.run(
        [transcode.FFPROBE, "-v", "error", "-show_entries", "stream=codec_type,codec_name:format=format_name,duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    info = json.loads(out)
    codecs = {s["codec_type"]: s["codec_name"] for s in info["streams"]}
    return info["format"]["format_name"], codecs, float(info["format"]["duration"])


async def converted(source):
    return b"".join([c async for c in await transcode.convert(source)])


@needs_ffmpeg
def test_an_mkv_becomes_an_mp4_a_browser_can_play(videos, tmp_path):
    fmt, codecs, duration = probe(asyncio.run(converted(stream.FileSource(videos["mkv"]))), tmp_path)
    assert "mp4" in fmt
    assert codecs == {"video": "h264", "audio": "aac"}
    assert 2 < duration < 4


@needs_ffmpeg
def test_an_avi_with_mpeg4_video_is_reencoded_to_h264(videos, tmp_path):
    fmt, codecs, _ = probe(asyncio.run(converted(stream.FileSource(videos["avi"]))), tmp_path)
    assert "mp4" in fmt and codecs["video"] == "h264"


@needs_ffmpeg
def test_the_codec_is_read_from_the_start_of_the_file(videos):
    assert asyncio.run(transcode.probe_codec(stream.FileSource(videos["mkv"]))) == "h264"
    assert asyncio.run(transcode.probe_codec(stream.FileSource(videos["avi"]))) == "mpeg4"


def test_closing_the_playback_kills_ffmpeg_even_if_it_would_run_forever(tmp_path, monkeypatch):
    # a stand-in ffmpeg that prints something and then lives for a minute, like a long conversion
    pidfile = tmp_path / "pid"
    fake_ffmpeg, fake_ffprobe = tmp_path / "ffmpeg", tmp_path / "ffprobe"
    fake_ffmpeg.write_text(f'#!/bin/sh\necho $$ > {pidfile}\nprintf hello\nexec sleep 60\n')
    fake_ffprobe.write_text("#!/bin/sh\necho h264\n")
    fake_ffmpeg.chmod(0o755)
    fake_ffprobe.chmod(0o755)
    monkeypatch.setattr(transcode, "FFMPEG", str(fake_ffmpeg))
    monkeypatch.setattr(transcode, "FFPROBE", str(fake_ffprobe))
    movie = tmp_path / "movie.mkv"
    movie.write_bytes(b"x" * 1000)

    async def run():
        chunks = await transcode.convert(stream.FileSource(movie))
        async for first in chunks:
            assert first == b"hello"
            break  # the viewer closed the tab after the first bytes
        await chunks.aclose()

    asyncio.run(run())
    pid = int(pidfile.read_text())
    try:
        with pytest.raises(ProcessLookupError):  # killed and reaped, not just abandoned
            os.kill(pid, 0)
    finally:
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass


@needs_ffmpeg
def test_the_route_converts_a_movie_that_browsers_cannot_play(logged_in, videos, monkeypatch, tmp_path):
    async def fetch_xml(q):
        return FEED

    async def fetch_torrent(link):
        return TORRENT_A

    monkeypatch.setattr(jackett, "fetch_xml", fetch_xml)
    monkeypatch.setattr(jackett, "fetch_torrent", fetch_torrent)
    engine = FakeEngine(tmp_path / "dl", {TORRENT_A: ("movie.mkv", videos["mkv"].read_bytes())})
    main.app.dependency_overrides[engine_module.get_engine] = lambda: engine
    movie = next(m["id"] for m in logged_in.get("/api/search").json() if m["title"] == "Sintel.2010.720p")

    res = logged_in.get(f"/api/movies/{movie}/stream", headers={"Range": "bytes=0-"})
    assert res.status_code == 200  # a live conversion cannot be sliced: the whole stream is the answer
    assert res.headers["content-type"] == "video/mp4"
    assert res.headers["accept-ranges"] == "none"
    assert "mp4" in probe(res.content, tmp_path)[0]


def test_a_missing_ffmpeg_is_reported_not_crashed(logged_in, monkeypatch, tmp_path):
    async def fetch_xml(q):
        return FEED

    async def fetch_torrent(link):
        return TORRENT_A

    monkeypatch.setattr(jackett, "fetch_xml", fetch_xml)
    monkeypatch.setattr(jackett, "fetch_torrent", fetch_torrent)
    monkeypatch.setattr(transcode, "FFPROBE", "/nonexistent/ffprobe")
    engine = FakeEngine(tmp_path / "dl", {TORRENT_A: ("movie.mkv", b"not really a video")})
    main.app.dependency_overrides[engine_module.get_engine] = lambda: engine
    movie = next(m["id"] for m in logged_in.get("/api/search").json() if m["title"] == "Sintel.2010.720p")
    assert logged_in.get(f"/api/movies/{movie}/stream").status_code == 501
