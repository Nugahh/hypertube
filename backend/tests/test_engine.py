import asyncio

import pytest

from app import engine as engine_module
from app import stream
from tests.swarm import lt, noise, seed

pytest.importorskip("libtorrent")

MP4, MKV = noise(150_000, 1), noise(400_000, 2)  # the mkv is bigger, but only the mp4 plays natively


@pytest.mark.parametrize(
    "files, expected",
    [
        ([("p/readme.txt", 10), ("p/m.mkv", 500), ("p/m.mp4", 100)], "p/m.mp4"),  # native beats bigger
        ([("p/small.mp4", 100), ("p/big.mp4", 900), ("p/x.ogv", 5000)], "p/big.mp4"),
        ([("p/a.mkv", 100), ("p/b.avi", 300)], "p/b.avi"),  # nothing native: the biggest
        ([("p/MOVIE.MP4", 100)], "p/MOVIE.MP4"),  # extensions are case-insensitive
        ([("p/readme.txt", 10), ("p/cover.jpg", 50)], None),
        ([], None),
    ],
)
def test_pick_video(files, expected):
    picked = engine_module.pick_video(files)
    assert (files[picked][0] if picked is not None else None) == expected


@pytest.fixture
def swarm(tmp_path):
    torrent, address, seeder = seed(tmp_path, {"readme.txt": b"hello", "movie.mkv": MKV, "movie.mp4": MP4})
    engine = engine_module.Engine(tmp_path / "downloads", listen="127.0.0.1:0", dht=False)
    yield engine, torrent, address
    engine.shutdown()
    del seeder


async def read_all(source, start, end):
    return b"".join([c async for c in stream.iter_bytes(source, start, end, stall_timeout=20)])


def test_the_engine_streams_the_native_video_of_a_torrent(swarm):
    engine, torrent_bytes, address = swarm
    torrent = engine.add(torrent_bytes, peers=[address])
    assert torrent.file_path.endswith("movie.mp4")
    assert torrent.size == len(MP4)
    assert asyncio.run(read_all(torrent, 0, torrent.size - 1)) == MP4


def magnet_of(torrent_bytes):
    return "magnet:?xt=urn:btih:" + str(lt.torrent_info(torrent_bytes).info_hashes().get_best())  # only the hash: no file list


def test_a_magnet_link_finds_the_file_list_in_the_swarm_and_streams_the_video(swarm):
    engine, torrent_bytes, address = swarm
    torrent = asyncio.run(engine.add_magnet(magnet_of(torrent_bytes), peers=[address]))
    assert torrent.file_path.endswith("movie.mp4")
    assert torrent.size == len(MP4)
    assert asyncio.run(read_all(torrent, 0, torrent.size - 1)) == MP4
    assert not (engine.download_dir / "pack" / "movie.mkv").exists()  # only the video (and subtitles) is downloaded, as with a .torrent file


def test_a_magnet_link_that_is_already_running_is_the_same_torrent(swarm):
    engine, torrent_bytes, address = swarm
    first = asyncio.run(engine.add_magnet(magnet_of(torrent_bytes), peers=[address]))
    assert asyncio.run(engine.add_magnet(magnet_of(torrent_bytes))) is first
    assert engine.add(torrent_bytes) is first


def test_a_magnet_link_nobody_shares_gives_up_and_leaves_nothing_running(swarm):
    engine, *_ = swarm
    with pytest.raises(engine_module.NoMetadata):
        asyncio.run(engine.add_magnet("magnet:?xt=urn:btih:" + "c" * 40, wait=0.5))
    assert engine.session.get_torrents() == []


def test_something_that_is_not_a_magnet_link_is_refused(swarm):
    engine, *_ = swarm
    with pytest.raises(engine_module.InvalidTorrent):
        asyncio.run(engine.add_magnet("not a magnet"))


def test_the_engine_serves_any_range_without_downloading_in_order(swarm):
    engine, torrent_bytes, address = swarm
    torrent = engine.add(torrent_bytes, peers=[address])
    tail = asyncio.run(read_all(torrent, len(MP4) - 5000, len(MP4) - 1))  # a player asks for the end first
    middle = asyncio.run(read_all(torrent, 70_000, 70_999))
    assert tail == MP4[-5000:]
    assert middle == MP4[70_000:71_000]


def test_progress_and_completion_are_about_the_chosen_file_only(swarm):
    engine, torrent_bytes, address = swarm
    torrent = engine.add(torrent_bytes, peers=[address])
    asyncio.run(read_all(torrent, 0, torrent.size - 1))
    assert torrent.is_complete  # although the 400 kB mkv was never wanted
    assert torrent.progress == pytest.approx(1.0)


def test_adding_the_same_torrent_twice_gives_the_same_download(swarm):
    engine, torrent_bytes, address = swarm
    first = engine.add(torrent_bytes, peers=[address])
    again = engine.add(torrent_bytes)
    assert again.infohash == first.infohash
    assert engine.get(first.infohash) is not None


def test_removing_a_torrent_keeps_the_downloaded_file(swarm, tmp_path):
    engine, torrent_bytes, address = swarm
    torrent = engine.add(torrent_bytes, peers=[address])
    asyncio.run(read_all(torrent, 0, torrent.size - 1))
    engine.remove(torrent.infohash)
    assert engine.get(torrent.infohash) is None
    assert (tmp_path / "downloads" / torrent.file_path).read_bytes() == MP4


def test_a_torrent_without_any_video_is_refused(tmp_path):
    torrent_bytes, address, seeder = seed(tmp_path, {"readme.txt": b"hello", "cover.jpg": noise(1000)})
    engine = engine_module.Engine(tmp_path / "downloads", listen="127.0.0.1:0", dht=False)
    try:
        with pytest.raises(engine_module.NoVideo):
            engine.add(torrent_bytes)
    finally:
        engine.shutdown()
        del seeder


def test_garbage_is_not_a_torrent(tmp_path):
    engine = engine_module.Engine(tmp_path / "downloads", listen="127.0.0.1:0", dht=False)
    try:
        with pytest.raises(engine_module.InvalidTorrent):
            engine.add(b"<html>not a torrent</html>")
    finally:
        engine.shutdown()
