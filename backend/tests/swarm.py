"""A real BitTorrent seeder on loopback, so the engine is tested against the real library without Internet."""
import warnings

import pytest

lt = pytest.importorskip("libtorrent")


def local_session():
    return lt.session(
        {
            "listen_interfaces": "127.0.0.1:0",  # any free port: read it back with listen_port()
            "enable_dht": False,
            "enable_lsd": False,
            "enable_upnp": False,
            "enable_natpmp": False,
            "allow_multiple_connections_per_ip": True,
        }
    )


def seed(root, files):
    """Write `files` ({name: bytes}) in root/pack, seed them. Returns (.torrent bytes, seeder address, session)."""
    pack = root / "pack"
    pack.mkdir(parents=True)
    for name, data in files.items():
        (pack / name).write_bytes(data)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)  # the replacements are not in every 2.x release
        storage = lt.file_storage()
        lt.add_files(storage, str(pack))
        builder = lt.create_torrent(storage, piece_size=16384)
        lt.set_piece_hashes(builder, str(root))
    torrent = lt.bencode(builder.generate())
    session = local_session()
    params = lt.add_torrent_params()
    params.ti = lt.torrent_info(torrent)
    params.save_path = str(root)
    session.add_torrent(params)
    return torrent, ("127.0.0.1", session.listen_port()), session


def noise(size, seed_byte=7):
    """Deterministic, non-repeating bytes: a wrong offset can never go unnoticed."""
    return bytes((i * 31 + seed_byte + (i >> 8)) % 256 for i in range(size))


