"""Background upkeep: notice finished downloads, erase movies nobody watched for a month."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from app import movies
from app.db import SessionLocal
from app.engine import get_engine
from app.models import Movie

MAX_AGE = timedelta(days=30)  # the subject: a movie unwatched for a month is erased
EVERY = 60  # seconds between two rounds


def sync_downloads(db, engine, now=None):
    for movie in db.scalars(select(Movie).where(Movie.status == "downloading")).all():
        movies.sync(db, engine, movie, now)


def _aware(moment):
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)  # SQLite hands back naive datetimes


def purge_unwatched(db, engine, now=None, max_age=MAX_AGE):
    """Erase the files of movies not watched for `max_age` (counted from the download if never watched).

    Returns how many movies were erased; they go back to `idle` and can be downloaded again.
    """
    now = now or datetime.now(timezone.utc)
    kept_folders, stale = set(), []
    for movie in db.scalars(select(Movie).where(Movie.status.in_(("ready", "downloading")))).all():
        last = movie.last_watched_at or movie.ready_at or movie.created_at
        if now - _aware(last) > max_age:
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
            await asyncio.to_thread(_round)
        except Exception:
            logging.getLogger("uvicorn.error").exception("maintenance round failed")
        await asyncio.sleep(EVERY)


def _round():
    with SessionLocal() as db:
        engine = get_engine()
        sync_downloads(db, engine)
        purge_unwatched(db, engine)
