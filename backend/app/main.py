import asyncio
from contextlib import asynccontextmanager

from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import auth, captions, clients, comments, finder, jackett, maintenance, movies, oauth, sources, tmdb, users
from app.db import get_db, init_db
from app.engine import get_engine
from app.models import Bookmark, Movie, Progress, User, Watched


@asynccontextmanager
async def lifespan(_):
    init_db()
    upkeep = asyncio.create_task(maintenance.loop())  # finished downloads, one-month cleanup
    yield
    upkeep.cancel()


app = FastAPI(title="Hypertube API", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(oauth.router)
app.include_router(users.router)
app.include_router(movies.router)
app.include_router(movies.front_page)
app.include_router(clients.router)
app.include_router(comments.router)
app.include_router(captions.router)

# the library is for authenticated users only
members_only = [Depends(auth.current_user)]


FINISHED = 0.95  # how far in a film is watched to the end
WARM = 12  # seconds the first visit waits for TMDb before showing what it has


async def _warm(db):
    """The genres come from what TMDb says about the films seen: look the popular films and the series up now, so even the
    first visit has rows."""
    answers = await asyncio.gather(sources.search("", None), sources.search("", "series"), return_exceptions=True)
    found = [m for a in answers if not isinstance(a, Exception) for m in movies.upsert_results(db, a)]  # a failed source: the genres seen before are still there
    try:
        await asyncio.wait_for(tmdb.enrich(db, found), WARM)
    except asyncio.TimeoutError:
        pass  # the batches done are kept, the next visit goes on


def _row(key):
    return {"id": key, "label": jackett.GENRES[key]["label"], "section": jackett.GENRES[key]["section"]}


@app.get("/api/genres", dependencies=members_only)
async def genres(db: Session = Depends(get_db)):
    """The rows of the site: popular, the open movies, then every genre TMDb gave to enough of the films seen; then the series
    tab and its own genres."""
    await _warm(db)
    films = [{"id": s, "label": name, "section": "films"} for s, name, _ in movies.known_genres(db)]
    series = [{"id": s, "label": name, "section": "series"} for s, name, _ in movies.known_genres(db, series=True)]
    return [_row("populaires"), _row("blender"), *films, _row("series"), *series]


def _tmdb_genre(genre):
    return genre is not None and genre not in jackett.GENRES


def _check_genre(genre, db):
    if _tmdb_genre(genre) and not movies.in_genre(db, genre):
        raise HTTPException(status_code=404, detail="Unknown genre")


async def _found(q, genre, db):
    if _tmdb_genre(genre):  # a genre TMDb gave: the films seen that have it
        found = movies.in_genre(db, genre)
        if not found:
            raise HTTPException(status_code=404, detail="Unknown genre")
        return found
    try:
        return movies.upsert_results(db, await sources.search(q, genre))
    except jackett.JackettError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/library")
async def library(
    q: str = Query("", max_length=100),
    genre: str | None = None,
    sort: Literal["relevance", "name", "year", "rating", "popularity"] | None = None,
    order: Literal["asc", "desc"] | None = None,
    year_from: int | None = Query(None, ge=1850, le=2100),
    year_to: int | None = Query(None, ge=1850, le=2100),
    min_rating: float | None = Query(None, ge=0, le=10),
    page: int = Query(1, ge=1),
    per_page: int = Query(24, ge=1, le=60),
    user: User = Depends(auth.current_user),
    db: Session = Depends(get_db),
):
    """One page of the library: searched, filtered and sorted on the server so the front can scroll through it.

    A search looks everywhere (titles, other names, directors, actors, summaries) and ranks by how it matched: the title
    first, then by name inside each level. `sort=name` and the others override that."""
    searching = bool(jackett.words(q))
    matches = {}
    if searching:
        _check_genre(genre, db)
        try:
            hits = await finder.find(db, q, None if _tmdb_genre(genre) else genre, user.language)
        except jackett.JackettError as e:
            raise HTTPException(status_code=502, detail=str(e))
        if _tmdb_genre(genre):  # the results are narrowed to the genre once TMDb has said what each one is
            await tmdb.enrich(db, [h.movie for h in hits])
            hits = [h for h in hits if movies.has_genre(h.movie, genre)]
        found = [h.movie for h in hits]
        matches = {h.movie.id: {"kind": h.kind, "label": h.label} for h in hits}
    else:
        found = await _found(q, genre, db)
    films = movies.group(found)  # the same film from several providers is one thumbnail
    found = [f.best for f in films]
    matches = {f.best.id: matches[f.first.id] for f in films if f.first.id in matches}
    sort = sort or ("relevance" if searching else "popularity")
    if sort == "relevance" and not searching:
        sort = "popularity"  # nothing was typed: the most popular films
    order = order or ("asc" if sort == "name" else "desc")
    if sort == "rating" or min_rating is not None:
        await tmdb.enrich(db, found)  # the rating of every result is needed, not only of this page
    wanted = [m for m in found if movies.keep(m, year_from, year_to, min_rating)]
    kept = wanted if sort == "relevance" else movies.arrange(wanted, sort, order)
    start = (page - 1) * per_page
    shown = kept[start : start + per_page]
    await tmdb.enrich(db, shown)
    return {"items": movies.present(db, user, shown, matches, {f.best.id: f for f in films}), "page": page, "per_page": per_page, "total": len(kept), "has_more": start + per_page < len(kept)}


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
    films, _ = await _shelf(db, user, seen, 40)
    saved = {p.movie_id: p for p in db.scalars(select(Progress).where(Progress.user_id == user.id))}

    def played(film):  # how far the member is in the film (the copy they played last gives it), 0 to 1
        last = max((saved[s.id] for s in film.sources if s.id in saved), key=lambda p: p.updated_at, default=None)
        return min(1.0, last.position / last.duration) if last else None

    kept = [(f, p) for f, p in ((f, played(f)) for f in films) if p is None or p < FINISHED][:20]  # a film watched to the end is done
    items = movies.present(db, user, [f.best for f, _ in kept], None, {f.best.id: f for f, _ in kept})
    return [{**item, "played": p} for item, (_, p) in zip(items, kept)]


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
    rows = db.scalars(select(Movie).where(Movie.status.in_(["downloading", "ready"]))).all()
    for movie in rows:
        movies.sync(db, engine, movie)  # a finished download becomes "ready"
    rows = sorted(rows, key=lambda m: (m.status != "downloading", -(m.ready_at.timestamp() if m.ready_at else 0), m.id))
    films, best = await _shelf(db, user, rows, 200, others=False)  # only the copies the server has
    items = movies.present(db, user, best, None, {f.best.id: f for f in films})
    return [{**item, "state": m.status, "progress": movies.progress(engine, m)} for item, m in zip(items, best)]


@app.get("/api/search")
async def search(
    q: str = Query("", max_length=100),
    genre: str | None = None,
    limit: int = Query(100, ge=1, le=100),
    user: User = Depends(auth.current_user),
    db: Session = Depends(get_db),
):
    films = movies.group(await _found(q, genre, db))[:limit]
    found = [f.best for f in films]
    await tmdb.enrich(db, found)  # ratings and posters for the thumbnails
    return movies.present(db, user, found, None, {f.best.id: f for f in films})
