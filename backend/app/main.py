import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import auth, captions, catalog, comments, jackett, maintenance, movies, settings, sources, tmdb, users
from app.db import get_db, init_db
from app.engine import get_engine
from app.models import Bookmark, Movie, User, Watched


@asynccontextmanager
async def lifespan(_):
    init_db()
    upkeep = asyncio.create_task(maintenance.loop())  # finished downloads, one-month cleanup
    yield
    upkeep.cancel()


app = FastAPI(title="Hypertube API", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(movies.router)
app.include_router(movies.front_page)
app.include_router(comments.router)
app.include_router(captions.router)
app.include_router(catalog.router)
app.include_router(settings.router)
app.include_router(sources.router)


async def _shelf(db, user, rows, limit, others=True):
    """The thumbnails of these movies (in this order), one per film. With `others`, the other copies of those films come
    along, so the sheet offers every provider."""
    ids = {m.id for m in rows}
    rest = [m for m in db.scalars(select(Movie)) if m.id not in ids] if others else []
    films = [f for f in movies.group(rows + rest) if f.first.id in ids][:limit]
    best = [f.best for f in films]
    await tmdb.enrich(db, best)
    return films, best


@app.get("/api/continue")
async def continue_watching(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    """The films the member started, the latest first: the row "continue watching"."""
    seen = db.scalars(select(Movie).join(Watched, Watched.movie_id == Movie.id).where(Watched.user_id == user.id).order_by(Watched.watched_at.desc())).all()
    films, best = await _shelf(db, user, seen, 40)
    items = movies.present(db, user, best, None, {f.best.id: f for f in films})
    # a film watched to the end is done; the others show how far the member is (0 to 1, none when nothing was saved)
    return [{**i, "played": i["resume"] and min(1.0, i["resume"]["position"] / i["resume"]["duration"])} for i in items if not i["finished"]][:20]


@app.get("/api/bookmarks/{kind}")
async def bookmarks(kind: movies.Shelf, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    """My list, or the favorites: the films the member put there, the latest first."""
    rows = db.scalars(
        select(Movie).join(Bookmark, Bookmark.movie_id == Movie.id)
        .where(Bookmark.user_id == user.id, Bookmark.kind == kind).order_by(Bookmark.added_at.desc(), Movie.id.desc())
    ).all()
    films, best = await _shelf(db, user, list(rows), 200)
    return movies.present(db, user, best, None, {f.best.id: f for f in films})


@app.get("/api/downloads")
async def downloads(user: User = Depends(auth.current_user), db: Session = Depends(get_db), engine=Depends(get_engine)):
    """What the server is downloading or has downloaded (they are the same for every member): the films that play at once."""
    rows = db.scalars(select(Movie).where(Movie.kept, Movie.status.in_(["downloading", "ready"]))).all()
    for movie in rows:
        movies.sync(db, engine, movie)  # a finished download becomes "ready"
    rows = sorted(rows, key=lambda m: (m.status != "downloading", -(m.ready_at.timestamp() if m.ready_at else 0), m.id))
    films, best = await _shelf(db, user, rows, 200, others=False)  # only the copies the server has
    items = movies.present(db, user, best, None, {f.best.id: f for f in films})
    return [{**item, "state": m.status, "progress": movies.progress(engine, m)} for item, m in zip(items, best)]


@app.get("/api/search")
async def search(
    q: str = Query("", max_length=100),
    limit: int = Query(100, ge=1, le=100),
    user: User = Depends(auth.current_user),
    db: Session = Depends(get_db),
):
    """What the providers (Jackett) have for these words, as thumbnails. The site itself goes through TMDb's catalogue and
    asks the providers for one film at a time (see catalog.py)."""
    try:
        found = movies.upsert_results(db, await jackett.search(q))
    except jackett.JackettError as e:
        raise HTTPException(status_code=502, detail=str(e))
    films = movies.group(found)[:limit]
    found = [f.best for f in films]
    await tmdb.enrich(db, found)  # ratings and posters for the thumbnails
    return movies.present(db, user, found, None, {f.best.id: f for f in films})
