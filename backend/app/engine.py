"""The BitTorrent side: downloads the video of a torrent and exposes it as a stream source (see stream.py).

We drive libtorrent ourselves (piece priorities, reading what has arrived): it is a torrent client library,
not one of the "make a stream from a torrent" libraries the subject forbids (webtorrent, peerflix, …).
"""
import asyncio
import os
import time
from pathlib import Path

import libtorrent as lt

from app import stream, subtitles

NATIVE = (".mp4", ".m4v", ".webm")  # what browsers play as they are
OTHER_VIDEO = (".mkv", ".avi", ".mov", ".ogv", ".mpg", ".mpeg", ".wmv", ".flv", ".ts")
LOOKAHEAD_BYTES = 8 * 1024 * 1024  # how far ahead of the playback position pieces are made urgent
LOOKAHEAD_MAX_PIECES = 64
HIGH, SKIP = 4, 0  # libtorrent file priorities
METADATA_WAIT = 45  # seconds a magnet link gets to find the torrent's file list in the swarm


class NoVideo(Exception):
    pass


class NoMetadata(Exception):
    pass


class InvalidTorrent(Exception):
    pass


def pick_video(files):
    """Index of the file to play in [(path, size), …]: the biggest natively playable video, else the biggest video."""
    for kinds in (NATIVE, OTHER_VIDEO):
        pool = [i for i, (path, _) in enumerate(files) if os.path.splitext(path)[1].lower() in kinds]
        if pool:
            return max(pool, key=lambda i: files[i][1])
    return None


def subtitle_indexes(files):
    return [i for i in range(files.num_files()) if subtitles.is_subtitle(files.file_path(i)) and files.file_size(i) <= subtitles.MAX_BYTES]


class Torrent:
    """One torrent being downloaded, seen as the stream source of its video file."""

    def __init__(self, handle, info, index, download_dir):
        files = info.layout()
        self.handle, self.index = handle, index
        self.infohash = str(info.info_hashes().get_best())
        self.file_path = files.file_path(index)  # relative to the download directory
        self.size = files.file_size(index)
        self._dir = Path(download_dir)
        self._path = self._dir / self.file_path
        self._offset = files.file_offset(index)  # where the file starts inside the torrent's byte space
        self._piece_length = info.piece_length()
        self._last_piece, self._last_time = None, 0.0
        # the small subtitle files come along with the video
        self._subs = [(i, files.file_path(i), files.file_size(i)) for i in subtitle_indexes(files)]

    def prioritize(self, pos):
        first = (self._offset + pos) // self._piece_length
        now = time.monotonic()
        if first == self._last_piece and now - self._last_time < 1.0:
            return  # called for every chunk: no need to repeat the same request
        self._last_piece, self._last_time = first, now
        last = (self._offset + self.size - 1) // self._piece_length
        window = min(LOOKAHEAD_MAX_PIECES, max(4, LOOKAHEAD_BYTES // self._piece_length))
        urgency = 0
        for piece in range(first, min(first + window, last + 1)):
            if not self.handle.have_piece(piece):
                self.handle.set_piece_deadline(piece, 300 + urgency * 250)  # ms: the nearest piece first
                urgency += 1

    def available_until(self, pos):
        return stream.contiguous_end(self.handle.have_piece, self._piece_length, self._offset, self.size, pos)

    def read(self, pos, n):
        with open(self._path, "rb") as f:
            f.seek(pos)
            return f.read(n)

    @property
    def progress(self):
        return min(1.0, self.handle.file_progress()[self.index] / self.size) if self.size else 1.0

    def _subtitle_done(self, done, index, path, size):
        # libtorrent can report the pieces complete a moment before the file exists on the disk
        return done[index] >= size and (self._dir / path).is_file()

    @property
    def is_complete(self):
        done = self.handle.file_progress()
        return self.progress >= 1.0 and all(self._subtitle_done(done, i, path, size) for i, path, size in self._subs)

    def subtitle_files(self):
        """[(path relative to the download directory, fully downloaded)] of the subtitle files of the torrent."""
        done = self.handle.file_progress()
        return [(path, self._subtitle_done(done, i, path, size)) for i, path, size in self._subs]

    @property
    def peers(self):
        return self.handle.status().num_peers

    @property
    def rate(self):
        return self.handle.status().download_rate  # bytes per second


class Engine:
    def __init__(self, download_dir, listen="0.0.0.0:6881", dht=True, library_dir=None):
        self.download_dir = Path(download_dir)  # the cache: every film is downloaded here first
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.library_dir = Path(library_dir or download_dir)  # where the films the member keeps end up (see library.py)
        self.library_dir.mkdir(parents=True, exist_ok=True)
        self.session = lt.session(
            {
                "listen_interfaces": listen,
                "enable_dht": dht,
                # after a failed connection libtorrent waits 30 s before retrying a web seed: far too long
                # for someone waiting for a movie to start (a torrent with few peers depends on its web seeds)
                "urlseed_wait_retry": 5,
            }
        )
        self._torrents = {}

    @staticmethod
    def _plan(info):
        """(index of the video to play, file priorities): only that file and the subtitles are downloaded."""
        files = info.layout()
        listing = [(files.file_path(i), files.file_size(i)) for i in range(files.num_files())]
        index = pick_video(listing)
        if index is None:
            raise NoVideo("no video file in this torrent")
        wanted = {index, *subtitle_indexes(files)}
        return index, [HIGH if i in wanted else SKIP for i in range(len(listing))]

    def add(self, data, peers=()):
        """Start (or find) the download of the video inside a .torrent file. Only that file is downloaded."""
        try:
            info = lt.torrent_info(data)
        except (RuntimeError, ValueError, TypeError) as e:
            raise InvalidTorrent("not a valid .torrent file") from e
        infohash = str(info.info_hashes().get_best())
        if infohash in self._torrents:
            return self._torrents[infohash]
        index, priorities = self._plan(info)
        params = lt.add_torrent_params()
        params.ti = info
        params.save_path = str(self.download_dir)
        params.flags |= lt.torrent_flags.sequential_download  # the movie fills up in playing order
        params.file_priorities = priorities
        handle = self.session.add_torrent(params)
        for peer in peers:
            handle.connect_peer(peer)
        torrent = self._torrents[infohash] = Torrent(handle, info, index, self.download_dir)
        return torrent

    async def add_magnet(self, uri, peers=(), wait=METADATA_WAIT):
        """Same as `add` for a magnet link. It holds only the torrent's hash: the list of files comes from the swarm
        (trackers, DHT), so this waits for it; NoMetadata when nobody gave it in time."""
        try:
            params = lt.parse_magnet_uri(uri)
        except (RuntimeError, ValueError, TypeError) as e:
            raise InvalidTorrent("not a valid magnet link") from e
        infohash = str(params.info_hashes.get_best())
        if infohash in self._torrents:
            return self._torrents[infohash]
        params.save_path = str(self.download_dir)
        params.flags |= lt.torrent_flags.sequential_download | lt.torrent_flags.default_dont_download  # nothing is downloaded before the video is chosen
        handle = self.session.add_torrent(params)  # the player asks again while this waits: the same torrent comes back
        for peer in peers:
            handle.connect_peer(peer)
        deadline = time.monotonic() + wait
        while not handle.status().has_metadata:
            if time.monotonic() > deadline:
                self.session.remove_torrent(handle)
                raise NoMetadata("nobody gave this torrent's file list in time")
            await asyncio.sleep(0.25)
        info = handle.torrent_file()
        try:
            index, priorities = self._plan(info)
        except NoVideo:
            self.session.remove_torrent(handle)
            raise
        handle.prioritize_files(priorities)
        torrent = self._torrents[infohash] = Torrent(handle, info, index, self.download_dir)
        return torrent

    def get(self, infohash):
        return self._torrents.get(infohash)

    def remove(self, infohash):
        """Stop the download and the seeding; the files stay on disk."""
        torrent = self._torrents.pop(infohash, None)
        if torrent:
            self.session.remove_torrent(torrent.handle)

    def shutdown(self):
        for infohash in list(self._torrents):
            self.remove(infohash)


_engine = None


def get_engine():
    """The one libtorrent session of the process, created on first use."""
    global _engine
    if _engine is None:
        port = os.getenv("TORRENT_PORT", "6881")
        _engine = Engine(
            os.getenv("DOWNLOAD_DIR", "./data/downloads"),
            listen=f"0.0.0.0:{port},[::]:{port}",
            dht=os.getenv("TORRENT_DHT", "true") == "true",
            library_dir=os.getenv("LIBRARY_DIR") or None,
        )
    return _engine
