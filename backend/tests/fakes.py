"""A download engine that needs no network: the torrent's bytes become available when the test says so."""
from pathlib import Path

from app import engine as engine_module

TORRENT_A, TORRENT_B = b"torrent-a", b"torrent-b"


class FakeTorrent:
    def __init__(self, data, file_path, infohash, download_dir, ready, subs=None):
        self.data, self.size, self.ready = data, len(data), ready
        self.subs = {}
        self.file_path, self.infohash = file_path, infohash
        self.peers, self.rate = 3, 2048
        self.asked = []
        path = Path(download_dir) / file_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)  # on disk from the start; `ready` decides what the player may see
        for name, (content, complete) in (subs or {}).items():
            (path.parent / name).write_bytes(content)
            self.subs[f"{path.parent.name}/{name}"] = complete

    def subtitle_files(self):
        return list(self.subs.items())

    def prioritize(self, pos):
        self.asked.append(pos)

    def available_until(self, pos):
        return max(pos, self.ready)

    def read(self, pos, n):
        return self.data[pos : pos + n]

    @property
    def progress(self):
        return self.ready / self.size

    @property
    def is_complete(self):
        return self.ready >= self.size


class FakeEngine:
    """What the routes need from app.engine.Engine. `videos` maps .torrent bytes to (file name, content)."""

    def __init__(self, download_dir, videos, ready=None):
        self.download_dir = Path(download_dir)
        self.videos, self.ready = videos, ready
        self.subs = {}  # file name -> (content, complete): subtitle files that come with the torrent
        self.added, self.removed, self.torrents = [], [], {}
        self.magnets = {}  # magnet link -> the .torrent bytes (a key of `videos`) the swarm would give for it

    async def add_magnet(self, uri, peers=()):
        if uri not in self.magnets:
            raise engine_module.NoMetadata("nobody shares it")
        return self.add(self.magnets[uri], peers)

    def add(self, data, peers=()):
        if data not in self.videos:
            raise engine_module.InvalidTorrent("not a torrent")
        name, content = self.videos[data]
        if content is None:
            raise engine_module.NoVideo("no video")
        self.added.append(data)
        infohash = "hash-" + data.decode()
        if infohash not in self.torrents:
            ready = len(content) if self.ready is None else self.ready
            self.torrents[infohash] = FakeTorrent(content, f"pack/{name}", infohash, self.download_dir, ready, self.subs)
        return self.torrents[infohash]

    def get(self, infohash):
        return self.torrents.get(infohash)

    def remove(self, infohash):
        self.removed.append(infohash)
        self.torrents.pop(infohash, None)
