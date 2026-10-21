"""The catalogue: the films and series TMDb lists (or finds for a search), to browse. A film opens on the torrents the providers have of it."""
import asyncio
import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import jackett, movies, picker, tmdb
from app import textmatch as tm
from app.auth import current_user
from app.db import get_db
from app.models import CatalogTitle, MovieInfo, User

router = APIRouter(prefix="/api/catalog", dependencies=[Depends(current_user)])
Kind = Literal["movie", "tv"]


def _language(user):
    if not os.getenv("TMDB_API_KEY"):
        raise HTTPException(status_code=501, detail="TMDb is not configured on this server")
    return tmdb.LANGUAGE_TAGS.get(user.language, "en-US")


async def _asked(call):
    try:
        return await call
    except tmdb.TmdbError:
        raise HTTPException(status_code=502, detail="TMDb is unreachable")
    except LookupError:
        raise HTTPException(status_code=404, detail="Not found")


@router.get("/genres")
async def genres(kind: Kind = "movie", user: User = Depends(current_user)):
    names = await _asked(tmdb.genre_names(kind, _language(user)))
    return [{"id": i, "name": n} for i, n in names.items()]


@router.get("")
async def page(
    kind: Kind = "movie",
    genre: int | None = Query(None, ge=1),
    q: str = Query("", max_length=100),
    page: int = Query(1, ge=1, le=tmdb.MAX_PAGES),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    found = await _asked(tmdb.browse(kind, genre, page, _language(user), q.strip()))
    for t in found["items"]:
        db.merge(CatalogTitle(kind=t["kind"], tmdb_id=t["id"], title=t["title"], year=t["year"], overview=t["overview"], poster=t["poster"], rating=t["rating"], genres=t["genres"]))
    db.commit()
    return {"items": found["items"], "page": page, "total": found["total"], "has_more": page < min(found["pages"], tmdb.MAX_PAGES)}


@router.get("/{kind}/{tmdb_id}")
async def sheet(kind: Kind, tmdb_id: int, user: User = Depends(current_user)):
    return await _asked(tmdb.title_sheet(kind, tmdb_id, _language(user)))


def _is_the_film(result, film):
    """Is this torrent that film: the same title (or original title), the same year give or take one?"""
    title = tm.fold(tmdb.clean_title(result["title"]))
    if title not in (tm.fold(film["title"]), tm.fold(film["original_title"])):
        return False
    return not (result["year"] and film["year"]) or abs(result["year"] - film["year"]) <= 1


@router.get("/movie/{tmdb_id}/copies")
async def copies(tmdb_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """What the providers have of a catalogue film, as the thumbnail to open (null when nobody has it): TMDb gives the
    names, the providers (through Jackett) the torrents, and the picker keeps the ones worth offering."""
    _language(user)  # TMDb must be configured
    film = await _asked(tmdb.title_sheet("movie", tmdb_id, "en-US"))  # torrents are named in English or in the original language
    names = list(dict.fromkeys([film["title"], film["original_title"]]))
    try:
        answers = await asyncio.gather(*(jackett.search(name) for name in names))
    except jackett.JackettError as e:
        raise HTTPException(status_code=502, detail=str(e))
    # searched by name only: the year is checked on the result (a provider may not write it, and "Heat" is not "Heat 2")
    picked = picker.pick({r["id"]: r for found in answers for r in found if _is_the_film(r, film)}.values())
    if not picked:
        return None
    rows = movies.upsert_results(db, picked)
    # the copies are known to be this film: give them what TMDb just said (the poster, the rating…) so the window opens complete
    details = {k: v for k, v in film.items() if k not in ("title", "original_title")}
    for row in rows:
        row.info = row.info or MovieInfo(**details)
    try:
        db.commit()
    except IntegrityError:  # another request stored the details of the same copy meanwhile
        db.rollback()
    return movies.present(db, user, rows[:1], None, {rows[0].id: movies.Film(rows[0], rows, rows[0])})[0]
