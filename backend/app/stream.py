"""Serving a video that may still be downloading: HTTP ranges, available bytes, waiting for pieces.

A *source* is anything with `size`, `prioritize(pos)`, `available_until(pos)` and `read(pos, n)`:
a torrent being downloaded (app/engine.py) or a complete file (FileSource).
"""
import asyncio
import re
import time

CHUNK = 256 * 1024
STALL_TIMEOUT = 120  # seconds without a single new byte before giving up on a request


class RangeNotSatisfiable(Exception):
    pass


class StreamStalled(Exception):
    pass


def parse_range(header, size):
    """(start, end) inclusive for a `Range: bytes=…` header, None to send the whole file."""
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", (header or "").strip())
    if not match:  # no header, unknown unit, several ranges: the whole file is a valid answer
        return None
    first, last = match.groups()
    if first == "":  # "-N": the last N bytes
        n = int(last or 0)
        if n == 0:
            raise RangeNotSatisfiable
        return max(0, size - n), size - 1
    start = int(first)
    end = size - 1 if last == "" else min(int(last), size - 1)
    if start >= size or end < start:
        raise RangeNotSatisfiable
    return start, end


def contiguous_end(have, piece_length, file_offset, file_size, pos):
    """End (exclusive, in file bytes) of the downloaded bytes that start at `pos`; `pos` itself if none."""
    if pos >= file_size:
        return file_size
    file_end = file_offset + file_size
    piece = (file_offset + pos) // piece_length
    if not have(piece):
        return pos
    while (piece + 1) * piece_length < file_end and have(piece + 1):
        piece += 1
    return min((piece + 1) * piece_length, file_end) - file_offset


async def iter_bytes(source, start, end, chunk_size=CHUNK, poll=0.1, stall_timeout=STALL_TIMEOUT):
    """The bytes start..end (inclusive) of the source, waiting for the download when they are not there yet."""
    pos, last_progress = start, time.monotonic()
    while pos <= end:
        source.prioritize(pos)  # tell the downloader what is urgent: the playback position
        available = source.available_until(pos)
        if available <= pos:
            if time.monotonic() - last_progress > stall_timeout:
                raise StreamStalled(f"no data for {stall_timeout}s at byte {pos}")
            await asyncio.sleep(poll)
            continue
        last_progress = time.monotonic()
        n = min(available, end + 1, pos + chunk_size) - pos
        yield await asyncio.to_thread(source.read, pos, n)
        pos += n


class FileSource:
    """A complete file on disk."""

    def __init__(self, path):
        self.path = path
        self.size = path.stat().st_size

    def prioritize(self, pos):
        pass

    def available_until(self, pos):
        return self.size

    def read(self, pos, n):
        with open(self.path, "rb") as f:
            f.seek(pos)
            return f.read(n)
