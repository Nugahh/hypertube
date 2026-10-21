import asyncio

import pytest

from app import stream


@pytest.mark.parametrize(
    "header, expected",
    [
        (None, None),  # no Range header: the whole file
        ("bytes=0-99", (0, 99)),
        ("bytes=500-", (500, 999)),
        ("bytes=-100", (900, 999)),  # the last 100 bytes
        ("bytes=0-5000", (0, 999)),  # an end past the file is clamped
        ("bytes=-5000", (0, 999)),
        ("items=0-1", None),  # unknown unit: ignored, whole file
        ("bytes=0-1,5-6", None),  # several ranges: browsers never ask, whole file
        ("garbage", None),
    ],
)
def test_parse_range(header, expected):
    assert stream.parse_range(header, 1000) == expected


@pytest.mark.parametrize("header", ["bytes=1000-", "bytes=2000-3000", "bytes=5-2", "bytes=-0"])
def test_parse_range_refuses_what_cannot_be_satisfied(header):
    with pytest.raises(stream.RangeNotSatisfiable):
        stream.parse_range(header, 1000)


# a 1000-byte file, 64-byte pieces, starting 100 bytes into the torrent: pieces 1..16
def end_for(have_pieces, pos, offset=100, size=1000, piece_length=64):
    return stream.contiguous_end(lambda p: p in have_pieces, piece_length, offset, size, pos)


def test_nothing_is_available_without_the_piece():
    assert end_for(set(), 0) == 0
    assert end_for({2, 3}, 0) == 0  # the first piece of the file (1) is missing


def test_available_bytes_stop_at_the_end_of_the_last_consecutive_piece():
    # piece 1 covers torrent bytes 64..127, i.e. file bytes 0..27
    assert end_for({1}, 0) == 28
    assert end_for({1, 2, 3}, 0) == 28 + 64 * 2
    assert end_for({1, 3}, 0) == 28  # the hole at piece 2 stops it


def test_available_bytes_start_from_the_requested_position():
    assert end_for({2}, 28) == 28 + 64
    assert end_for({2}, 27) == 27  # byte 27 is still in piece 1


def test_available_bytes_never_go_past_the_end_of_the_file():
    everything = set(range(0, 20))
    assert end_for(everything, 0) == 1000
    assert end_for(everything, 999) == 1000
    assert end_for(everything, 1000) == 1000


class FakeSource:
    """A file whose bytes become available over time, like a download."""

    def __init__(self, data, ready=0):
        self.data, self.size, self.ready, self.asked = data, len(data), ready, []

    def prioritize(self, pos):
        self.asked.append(pos)

    def available_until(self, pos):
        return max(pos, self.ready)

    def read(self, pos, n):
        return self.data[pos : pos + n]


DATA = bytes(range(256)) * 4  # 1024 bytes, every position distinguishable


async def collect(source, start, end, **kwargs):
    return b"".join([chunk async for chunk in stream.iter_bytes(source, start, end, **kwargs)])


def test_iter_bytes_yields_the_requested_range_in_small_chunks():
    source = FakeSource(DATA, ready=len(DATA))
    chunks = []

    async def run():
        async for chunk in stream.iter_bytes(source, 100, 899, chunk_size=300):
            chunks.append(chunk)

    asyncio.run(run())
    assert b"".join(chunks) == DATA[100:900]
    assert [len(c) for c in chunks] == [300, 300, 200]


def test_iter_bytes_waits_for_bytes_that_have_not_arrived_yet():
    source = FakeSource(DATA, ready=100)

    async def run():
        async def deliver():
            await asyncio.sleep(0.3)
            source.ready = len(DATA)

        task = asyncio.create_task(deliver())
        data = await collect(source, 0, len(DATA) - 1, poll=0.02)
        await task
        return data

    assert asyncio.run(run()) == DATA


def test_iter_bytes_asks_the_source_for_the_position_it_is_waiting_on():
    source = FakeSource(DATA, ready=len(DATA))
    asyncio.run(collect(source, 500, 700))
    assert source.asked[0] == 500


def test_iter_bytes_gives_up_when_nothing_arrives():
    source = FakeSource(DATA, ready=0)
    with pytest.raises(stream.StreamStalled):
        asyncio.run(collect(source, 0, 10, poll=0.01, stall_timeout=0.2))


def test_file_source_serves_a_complete_file(tmp_path):
    path = tmp_path / "movie.bin"
    path.write_bytes(DATA)
    source = stream.FileSource(path)
    assert source.size == len(DATA)
    assert source.available_until(10) == len(DATA)
    assert asyncio.run(collect(source, 250, 260)) == DATA[250:261]
