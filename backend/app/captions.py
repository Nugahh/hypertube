"""Subtitles of a movie: the ones that came with the torrent, the ones members import, those found on OpenSubtitles."""
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import opensubtitles, subtitles, tmdb
from app.auth import current_user
from app.db import get_db
from app.engine import get_engine
from app.models import ExtraSubtitle, Movie, User

MAX_EXTRAS = 10  # per movie

router = APIRouter(prefix="/api/movies/{movie_id}/subtitles", dependencies=[Depends(current_user)])
Lang = Annotated[str, Query(pattern=r"^[a-z]{2}$")]


def listing(db, engine, movie, user):
    """English first, then the other languages; for one language, the torrent's file before the imported ones."""
    items = [{"ref": lang, "lang": lang, "label": subtitles.LABELS[lang], "source": "torrent", "mine": False} for lang in subtitles.found(engine, movie)]
    for x in db.scalars(select(ExtraSubtitle).where(ExtraSubtitle.movie_id == movie.id).order_by(ExtraSubtitle.id)):
        items.append({"ref": str(x.id), "lang": x.lang, "label": x.label, "source": x.source, "mine": x.user_id == user.id})
    return sorted(items, key=lambda s: (s["lang"] != "en", s["lang"]))  # stable: the torrent's file stays before the others


def _movie(db, movie_id):
    movie = db.get(Movie, movie_id)
    if movie is None:
        raise HTTPException(status_code=404, detail="Movie not found")
    return movie


def _vtt(raw):
    vtt = subtitles.to_vtt(raw)
    return vtt if "-->" in vtt else None  # a subtitle file has at least one cue


def _store(db, movie, user, lang, label, source, vtt, response):
    if db.scalar(select(ExtraSubtitle.id).where(ExtraSubtitle.movie_id == movie.id).offset(MAX_EXTRAS - 1)) is not None:
        raise HTTPException(status_code=409, detail=f"At most {MAX_EXTRAS} imported subtitles per movie")
    extra = ExtraSubtitle(movie_id=movie.id, user_id=user.id, lang=lang, label=label[:120] or "Subtitles", source=source, content=vtt)
    db.add(extra)
    db.commit()
    response.status_code = 201
    response.headers["Location"] = f"/api/movies/{movie.id}/subtitles/{extra.id}"
    return {"ref": str(extra.id), "lang": lang, "label": extra.label, "source": source, "mine": True}


@router.get("")
def list_subtitles(movie_id: int, user: User = Depends(current_user), db: Session = Depends(get_db), engine=Depends(get_engine)):
    return listing(db, engine, _movie(db, movie_id), user)


@router.get("/search")
async def search_opensubtitles(movie_id: int, lang: Lang = "en", db: Session = Depends(get_db)):
    movie = _movie(db, movie_id)
    if not opensubtitles.configured():
        raise HTTPException(status_code=501, detail="OpenSubtitles is not configured on this server")
    if lang not in subtitles.LABELS:
        raise HTTPException(status_code=422, detail="Unknown language")
    info = movie.info
    try:
        return await opensubtitles.search(tmdb.clean_title(movie.title), lang, info.tmdb_id if info and info.kind == "movie" else None, movie.year)
    except opensubtitles.OpenSubtitlesError as e:
        raise HTTPException(status_code=502, detail=str(e))


class FromOpenSubtitles(BaseModel):
    file_id: int
    lang: str
    release: str = ""


@router.post("/opensubtitles")
async def import_from_opensubtitles(movie_id: int, data: FromOpenSubtitles, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    movie = _movie(db, movie_id)
    if not opensubtitles.configured():
        raise HTTPException(status_code=501, detail="OpenSubtitles is not configured on this server")
    if data.lang not in subtitles.LABELS:
        raise HTTPException(status_code=422, detail="Unknown language")
    try:
        vtt = _vtt(await opensubtitles.download(data.file_id))
    except opensubtitles.OpenSubtitlesQuota as e:
        raise HTTPException(status_code=429, detail=str(e))
    except opensubtitles.OpenSubtitlesError as e:
        raise HTTPException(status_code=502, detail=str(e))
    if vtt is None:
        raise HTTPException(status_code=502, detail="OpenSubtitles did not send a subtitle file")
    return _store(db, movie, user, data.lang, data.release.strip(), "opensubtitles", vtt, response)


@router.post("")
def import_file(
    movie_id: int,
    response: Response,
    file: UploadFile = File(...),
    lang: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    movie = _movie(db, movie_id)
    raw = file.file.read(subtitles.MAX_BYTES + 1)
    if len(raw) > subtitles.MAX_BYTES:
        raise HTTPException(status_code=413, detail="Subtitle file too large (2 MB max)")
    vtt = _vtt(raw)
    if vtt is None:
        raise HTTPException(status_code=415, detail="Not a subtitle file (.srt or .vtt)")
    lang = lang or subtitles.language_of(file.filename or "") or ""
    if lang not in subtitles.LABELS:
        raise HTTPException(status_code=422, detail="Choose the language of this subtitle file")
    return _store(db, movie, user, lang, (file.filename or "")[:120], "upload", vtt, response)


Ref = Path(pattern=r"^([a-z]{2}|\d{1,9})$")  # a language code (the torrent's file, else the first imported one) or an imported subtitle's id


@router.get("/{ref}")
def get_subtitle(movie_id: int, ref: str = Ref, db: Session = Depends(get_db), engine=Depends(get_engine)):
    movie = _movie(db, movie_id)
    vtt = None
    if ref.isdigit():
        extra = db.get(ExtraSubtitle, int(ref))
        vtt = extra.content if extra and extra.movie_id == movie.id else None
    else:
        path = subtitles.found(engine, movie).get(ref)
        vtt = subtitles.read_vtt(engine, path) if path else None
        if vtt is None:
            extra = db.scalar(select(ExtraSubtitle).where(ExtraSubtitle.movie_id == movie.id, ExtraSubtitle.lang == ref).order_by(ExtraSubtitle.id))
            vtt = extra.content if extra else None
    if vtt is None:
        raise HTTPException(status_code=404, detail="No such subtitles")
    return Response(vtt, media_type="text/vtt; charset=utf-8", headers={"X-Content-Type-Options": "nosniff"})


@router.delete("/{ref}", status_code=204)
def delete_subtitle(movie_id: int, ref: str = Path(pattern=r"^\d{1,9}$"), user: User = Depends(current_user), db: Session = Depends(get_db)):
    extra = db.get(ExtraSubtitle, int(ref))
    if extra is None or extra.movie_id != movie_id:
        raise HTTPException(status_code=404, detail="No such subtitles")
    if extra.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your subtitles")
    db.delete(extra)
    db.commit()
