"""Where the films are: a streamed film is a cache copy, a film the member chose to download is moved to their library folder.

Both folders keep the torrent's own layout (`pack/film.mkv` is under either), so a film is found by looking in the library first,
then in the cache.
"""
import shutil
from pathlib import Path


def root_of(engine, relative):
    """The folder (library, else cache) that holds this relative path; the cache when it is in neither (still to come)."""
    return engine.library_dir if (engine.library_dir / relative).exists() else engine.download_dir


def locate(engine, relative):
    return root_of(engine, relative) / relative


def move_to_library(engine, relative):
    """Move the torrent's folder (or its single file) from the cache to the library; a no-op when it is not in the cache."""
    top = Path(relative).parts[0]
    source, target = engine.download_dir / top, engine.library_dir / top
    if source == target or not source.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir() and target.is_dir():  # a folder already there (another film of the same pack): merge, then drop the cache copy
        shutil.copytree(source, target, dirs_exist_ok=True)
        shutil.rmtree(source)
    else:
        shutil.move(str(source), str(target))
