"""The catalogue: the films and series TMDb lists (or finds for a search), to browse. A film opens on the torrents the providers have of it."""
import asyncio
import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import jackett, movies, picker, tmdb
from app import textmatch as tm
from app.auth import current_user
from app.db import get_db
from app.models import CatalogBookmark, CatalogTitle, MovieInfo, User

router = APIRouter(prefix="/api/catalog", dependencies=[Depends(current_user)])
Kind = Literal["movie", "tv"]
Shelf = Literal["favorite", "list"]  # the star, and the "+"


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


def _closest(db, kind, q):
    """A title we know that the typed words nearly spell (TMDb forgives nothing: "spidermann" finds no film), as the words to ask TMDb for.
    shortcut: only the titles the catalogue showed so far; a title nobody browsed is not found."""
    typed = tm.fold(q).replace(" ", "")
    best = None
    for (title,) in db.execute(select(CatalogTitle.title).where(CatalogTitle.kind == kind)):
        words = tm.tokens(title)
        for start in range(len(words)):
            for end in range(start + 1, len(words) + 1):
                joined = "".join(words[start:end])  # "spider", "spiderman"…: the typed words may be glued or split differently
                slip = tm.distance(typed, joined)
                if slip and tm.word_quality(typed, joined) == tm.TYPO and (best is None or slip < best[0]):
                    best = (slip, " ".join(words[start:end]))
    return best[1] if best else None


@router.get("")
async def page(
    kind: Kind = "movie",
    genre: int | None = Query(None, ge=1),
    q: str = Query("", max_length=100),
    sort: str = Query("popularity", pattern="^(popularity|rating|year|name)$"),
    year: int | None = Query(None, ge=1888, le=2100),
    rating: int | None = Query(None, ge=1, le=9),
    page: int = Query(1, ge=1, le=tmdb.MAX_PAGES),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    found = await _asked(tmdb.browse(kind, genre, page, _language(user), q.strip(), sort, year, rating))
    if q.strip() and not found["items"]:  # a typo: ask for the closest title we know instead
        near = _closest(db, kind, q)
        if near:
            found = await _asked(tmdb.browse(kind, genre, page, _language(user), near))
    for t in found["items"]:
        db.merge(CatalogTitle(kind=t["kind"], tmdb_id=t["id"], title=t["title"], year=t["year"], overview=t["overview"], poster=t["poster"], rating=t["rating"], genres=t["genres"]))
    db.commit()
    marks = {tuple(r) for r in db.execute(select(CatalogBookmark.media, CatalogBookmark.tmdb_id, CatalogBookmark.shelf).where(CatalogBookmark.user_id == user.id))}
    for t in found["items"]:
        t["favorite"] = (t["kind"], t["id"], "favorite") in marks
        t["listed"] = (t["kind"], t["id"], "list") in marks
    return {"items": found["items"], "page": page, "total": found["total"], "has_more": page < min(found["pages"], tmdb.MAX_PAGES)}


def _title(db, media, tmdb_id):
    title = db.get(CatalogTitle, (media, tmdb_id))
    if title is None:
        raise HTTPException(status_code=404, detail="Not found")
    return title


# declared before the sheet: "bookmarks" must not be read as a kind
@router.get("/bookmarks/{shelf}")
async def bookmarks(shelf: Shelf, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The titles the member put in this shelf from the catalogue, the latest first."""
    rows = db.execute(
        select(CatalogTitle, CatalogBookmark.shelf).join(
            CatalogBookmark, (CatalogBookmark.media == CatalogTitle.kind) & (CatalogBookmark.tmdb_id == CatalogTitle.tmdb_id)
        ).where(CatalogBookmark.user_id == user.id, CatalogBookmark.shelf == shelf).order_by(CatalogBookmark.added_at.desc())
    ).all()
    language = tmdb.LANGUAGE_TAGS.get(user.language, "en-US")
    # a row keeps the language it was first listed in: say it in the member's
    words = await asyncio.gather(*(tmdb.in_language(t.kind, t.tmdb_id, language) for t, _ in rows)) if os.getenv("TMDB_API_KEY") else [None] * len(rows)
    return [
        {"kind": t.kind, "id": t.tmdb_id, "title": (w or {}).get("title") or t.title, "year": t.year, "rating": t.rating, "poster": t.poster,
         "overview": (w or {}).get("overview") or t.overview, "genres": (w or {}).get("genres") or t.genres or [], "favorite": shelf == "favorite", "listed": shelf == "list"}
        for (t, _), w in zip(rows, words)
    ]


@router.put("/{media}/{tmdb_id}/bookmarks/{shelf}", status_code=204)
def add_bookmark(media: Kind, tmdb_id: int, shelf: Shelf, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _title(db, media, tmdb_id)
    db.merge(CatalogBookmark(user_id=user.id, media=media, tmdb_id=tmdb_id, shelf=shelf))  # already there: nothing changes
    db.commit()


@router.delete("/{media}/{tmdb_id}/bookmarks/{shelf}", status_code=204)
def remove_bookmark(media: Kind, tmdb_id: int, shelf: Shelf, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(delete(CatalogBookmark).where(CatalogBookmark.user_id == user.id, CatalogBookmark.media == media, CatalogBookmark.tmdb_id == tmdb_id, CatalogBookmark.shelf == shelf))
    db.commit()


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
