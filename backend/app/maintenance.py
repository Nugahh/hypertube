"""Background upkeep: notice finished downloads, empty the cache of the films only streamed and not watched for a few days."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from app import movies, settings
from app.db import SessionLocal
from app.engine import get_engine
from app.models import Movie

EVERY = 60  # seconds between two rounds


def sync_downloads(db, engine, now=None):
    for movie in db.scalars(select(Movie).where(Movie.status == "downloading")).all():
        movies.sync(db, engine, movie, now)


def _aware(moment):
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)  # SQLite hands back naive datetimes


def purge_unwatched(db, engine, now=None, max_age=timedelta(days=settings.DEFAULT_CACHE_DAYS)):
    """Erase the cache copies (films only streamed, never downloaded by the member) not watched for `max_age`, counted from the
    download if never watched. The films the member keeps stay for good.

    Returns how many movies were erased; they go back to `idle` and can be streamed or downloaded again.
    """
    now = now or datetime.now(timezone.utc)
    kept_folders, stale = set(), []
    for movie in db.scalars(select(Movie).where(Movie.status.in_(("ready", "downloading")))).all():
        last = movie.last_watched_at or movie.ready_at or movie.created_at
        if not movie.kept and now - _aware(last) > max_age:
            stale.append(movie)
        elif movie.file_path:
            kept_folders.add(Path(movie.file_path).parts[0])
    for movie in stale:
        movies.erase_files(engine, movie, kept_folders)
    db.commit()
    return len(stale)


async def loop():
    while True:
        try:
            with SessionLocal() as db:
                await movies.resume(db, get_engine())  # before the cleanup: a download the member wants is not a cache copy
            await asyncio.to_thread(_round)
        except Exception:
            logging.getLogger("uvicorn.error").exception("maintenance round failed")
        await asyncio.sleep(EVERY)


def _round():
    with SessionLocal() as db:
        engine = get_engine()
        sync_downloads(db, engine)
        days = settings.cache_days(db)
        if days:  # 0: the cache is never cleaned up
            purge_unwatched(db, engine, max_age=timedelta(days=days))
