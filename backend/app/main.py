import asyncio
from contextlib import asynccontextmanager

from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.orm import Session

from app import auth, captions, clients, comments, finder, jackett, maintenance, movies, oauth, sources, tmdb, users
from app.db import get_db, init_db
from app.models import User


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


@app.get("/api/genres", dependencies=members_only)
async def genres():
    return [{"id": k, "label": g["label"], "section": g["section"]} for k, g in jackett.GENRES.items()]


def _check_genre(genre):
    if genre is not None and genre not in jackett.GENRES:
        raise HTTPException(status_code=404, detail="Unknown genre")


async def _found(q, genre, db):
    _check_genre(genre)
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
        _check_genre(genre)
        try:
            hits = await finder.find(db, q, genre, user.language)
        except jackett.JackettError as e:
            raise HTTPException(status_code=502, detail=str(e))
        found = [h.movie for h in hits]
        matches = {h.movie.id: {"kind": h.kind, "label": h.label} for h in hits}
    else:
        found = await _found(q, genre, db)
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
    return {"items": movies.present(db, user, shown, matches), "page": page, "per_page": per_page, "total": len(kept), "has_more": start + per_page < len(kept)}


@app.get("/api/search")
async def search(
    q: str = Query("", max_length=100),
    genre: str | None = None,
    limit: int = Query(100, ge=1, le=100),
    user: User = Depends(auth.current_user),
    db: Session = Depends(get_db),
):
    found = (await _found(q, genre, db))[:limit]
    await tmdb.enrich(db, found)  # ratings and posters for the thumbnails
    return movies.present(db, user, found)
