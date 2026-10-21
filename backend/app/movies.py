import os
from collections import namedtuple
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm import Session

from app import engine as engine_module
from app import captions, jackett, picker, stream, tmdb, transcode
from app import textmatch as tm
from app.auth import current_user
from app.db import get_db
from app.engine import get_engine
from app.models import Bookmark, Comment, Movie, Progress, User, Watched

# what the browser may know about a movie: the provider link and the torrent never leave the server
PUBLIC = ("id", "title", "year", "resolution", "size", "seeders", "peers", "provider", "cover")
LISTS = ("directors", "producers", "cast", "genres")
MIME = {".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm"}

router = APIRouter(prefix="/api/movies", dependencies=[Depends(current_user)])
front_page = APIRouter(prefix="/api/movies")  # the one movie route open to everyone
TOP = 20


def public(movie):
    data = {k: getattr(movie, k) for k in PUBLIC}
    data["tier"] = picker.tier(movie.title)  # the quality tab of the copy: 4K, 1080p, 720p
    info = movie.info
    data["rating"] = info.rating if info else None
    if info:  # TMDb's poster is nicer than the provider's thumbnail, its year more reliable than the one in the title
        data["cover"] = info.poster or data["cover"]
        data["year"] = data["year"] or info.year
    return data


FINISHED = 0.95  # how far in a film counts as watched to the end


Shelf = Literal["favorite", "list"]  # the star, and the "+" that adds to my list
SOURCE = ("id", "provider", "resolution", "size", "seeders")
Film = namedtuple("Film", "best sources first")  # a film's results, best first; `first` is the one the search met first


def group(movies):
    """One entry per film: results with the same title (and the same year when both have one) are the same film
    offered by several providers. A copy already downloaded comes first, then the best seeded."""
    groups = []  # [title, year, [results]]
    for m in movies:
        title = tm.fold(tmdb.clean_title(m.title))
        for g in groups:
            if g[0] == title and (g[1] is None or m.year is None or g[1] == m.year):
                g[1] = g[1] or m.year
                g[2].append(m)
                break
        else:
            groups.append([title, m.year, [m]])
    films = []
    for _, _, results in groups:
        best_first = sorted(results, key=lambda m: (m.status != "ready", -m.seeders))
        # the year one provider knows, shown on the thumbnail. Not an assignment: that would make the row dirty and the next query
        # would write it, and two requests writing the same row at once lock each other (the whole server froze on PostgreSQL)
        set_committed_value(best_first[0], "year", best_first[0].year or next((m.year for m in results if m.year), None))
        films.append(Film(best_first[0], best_first, results[0]))
    return films


def present(db, user, movies, matches=None, films=None):
    """The thumbnails of these movies for one member: public fields, the providers offering it, whether they watched it
    (from any of them) and, for a search, why it matched. `films` maps a movie id to its Film."""
    films = films or {}
    sources = {m.id: films[m.id].sources if m.id in films else [m] for m in movies}
    ids = list({s.id for results in sources.values() for s in results})
    seen = set(db.scalars(select(Watched.movie_id).where(Watched.user_id == user.id, Watched.movie_id.in_(ids))))
    marked = {"favorite": set(), "list": set()}
    for movie_id, kind in db.execute(select(Bookmark.movie_id, Bookmark.kind).where(Bookmark.user_id == user.id, Bookmark.movie_id.in_(ids))):
        marked[kind].add(movie_id)
    saved = {p.movie_id: p for p in db.scalars(select(Progress).where(Progress.user_id == user.id, Progress.movie_id.in_(ids)))}
    matches = matches or {}
    items = []
    for m in movies:
        # where the member stopped: the copy they watched last gives it (it may not be the thumbnail's own copy)
        last = max((saved[s.id] for s in sources[m.id] if s.id in saved), key=lambda p: p.updated_at, default=None)
        done = last is not None and last.position >= FINISHED * last.duration
        items.append({
            **public(m),
            "resume": {"id": last.movie_id, "position": last.position, "duration": last.duration} if last and not done else None,
            "finished": done,
            "watched": any(s.id in seen for s in sources[m.id]),
            "favorite": any(s.id in marked["favorite"] for s in sources[m.id]),
            "listed": any(s.id in marked["list"] for s in sources[m.id]),
            "match": matches.get(m.id),
            "sources": [{**{k: getattr(s, k) for k in SOURCE}, "tier": picker.tier(s.title)} for s in sources[m.id]],
        })
    return items


def _year(movie):
    return movie.year or (movie.info.year if movie.info else None)


def _rating(movie):
    return movie.info.rating if movie.info else None


SORTS = {
    "name": lambda m: m.title.lower(),
    "year": _year,
    "rating": _rating,
    "popularity": lambda m: m.seeders,
}


def arrange(movies, sort, order):
    """Sorted by the chosen criterion; the movies that do not have it (no year, no rating) always come last."""
    key = SORTS[sort]
    known = sorted((m for m in movies if key(m) is not None), key=key, reverse=order == "desc")
    return known + [m for m in movies if key(m) is None]


def _sheet(movie):
    """Summary, casting, length… everything TMDb gave, empty when it knows nothing."""
    info = movie.info
    return {
        "overview": info.overview if info else None,
        "runtime": info.runtime if info else None,
        "language": info.language if info else None,
        **{k: (getattr(info, k) if info else None) or [] for k in LISTS},
    }


def upsert_results(db, results):
    """Remember search results (one row per provider id) and return them as Movie rows, in the same order."""
    existing = {m.source_id: m for m in db.scalars(select(Movie).where(Movie.source_id.in_([r["id"] for r in results])))}
    movies = []
    for r in results:
        movie = existing.get(r["id"]) or Movie(source_id=r["id"], status="idle")
        for field in ("title", "year", "resolution", "size", "seeders", "peers", "provider", "cover", "link"):
            setattr(movie, field, r[field])
        db.add(movie)
        existing[r["id"]] = movie
        movies.append(movie)
    db.commit()
    return movies


def _movie(db, movie_id):
    movie = db.get(Movie, movie_id)
    if movie is None:
        raise HTTPException(status_code=404, detail="Movie not found")
    return movie


def sync(db, engine, movie, now=None):
    """A finished download becomes `ready`: the file stays, the torrent stops (no seeding)."""
    torrent = engine.get(movie.infohash) if movie.status == "downloading" else None
    if torrent is not None and torrent.is_complete:
        movie.status, movie.ready_at = "ready", now or datetime.now(timezone.utc)
        engine.remove(movie.infohash)
        db.commit()


def progress(engine, movie):
    """How much of the movie the server has, 0 to 1."""
    torrent = engine.get(movie.infohash) if movie.status == "downloading" else None
    return 1 if movie.status == "ready" else torrent.progress if torrent else 0


def _details(engine, movie):
    torrent = engine.get(movie.infohash) if movie.status == "downloading" else None
    return {
        **public(movie),
        **_sheet(movie),
        "state": movie.status,
        # whether the browser plays the file as it is (else it is converted); unknown until the torrent has been opened
        "native": os.path.splitext(movie.file_path)[1].lower() in MIME if movie.file_path else None,
        "progress": progress(engine, movie),
        "peers": torrent.peers if torrent else movie.peers,
        "rate": torrent.rate if torrent else 0,
    }


async def _open_source(db, engine, movie):
    """The stream source of the movie: its file when downloaded, else its running (or freshly started) torrent."""
    if movie.status == "ready":
        path = engine.download_dir / movie.file_path
        if path.is_file():
            return stream.FileSource(path)
        movie.status = "idle"  # the file disappeared: fall through and download it again
    torrent = engine.get(movie.infohash) if movie.infohash else None
    if torrent is None:
        try:
            found = await jackett.fetch_torrent(movie.link)
            torrent = await engine.add_magnet(found) if isinstance(found, str) else engine.add(found)
        except jackett.JackettError as e:
            raise HTTPException(status_code=502, detail=str(e))
        except engine_module.InvalidTorrent:
            raise HTTPException(status_code=502, detail="The provider sent an invalid torrent")
        except engine_module.NoMetadata:
            raise HTTPException(status_code=504, detail="Nobody is sharing this torrent right now")
        except engine_module.NoVideo:
            raise HTTPException(status_code=422, detail="No video in this torrent")
        movie.status, movie.infohash, movie.file_path = "downloading", torrent.infohash, torrent.file_path
        db.commit()
    return torrent


@front_page.get("")
async def top_movies(db: Session = Depends(get_db)):
    """The front page: the most popular of the movies the site knows (found for a member before), by id and name (the
    details are for members)."""
    top = arrange([f.best for f in group(db.scalars(select(Movie)).all())], "popularity", "desc")[:TOP]
    await tmdb.enrich(db, top)
    return [{"id": m.id, "name": m.title, "year": _year(m), "rating": _rating(m)} for m in top]


MAX_SECONDS = 48 * 3600  # no film is longer, whatever the player says


class Position(BaseModel):
    position: float = Field(ge=0, le=MAX_SECONDS)  # seconds
    duration: float = Field(gt=0, le=MAX_SECONDS)


@router.put("/{movie_id}/progress", status_code=204)
def save_progress(movie_id: int, data: Position, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The player says where the member is: one row per member and movie, always the latest position."""
    _movie(db, movie_id)
    db.merge(Progress(user_id=user.id, movie_id=movie_id, position=data.position, duration=data.duration, updated_at=datetime.now(timezone.utc)))
    db.commit()


def copies(db, movie):
    """Every copy of this film (the same film from other providers), the movie itself first."""
    others = [m for m in db.scalars(select(Movie)) if m.id != movie.id]
    return next(f.sources for f in group([movie] + others) if f.first.id == movie.id)


@router.put("/{movie_id}/bookmarks/{kind}", status_code=204)
def add_bookmark(movie_id: int, kind: Shelf, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _movie(db, movie_id)
    db.merge(Bookmark(user_id=user.id, movie_id=movie_id, kind=kind))  # already there: nothing changes
    db.commit()


@router.delete("/{movie_id}/bookmarks/{kind}", status_code=204)
def remove_bookmark(movie_id: int, kind: Shelf, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Out of the shelf, whichever copy of the film it was added from."""
    ids = [m.id for m in copies(db, _movie(db, movie_id))]
    db.execute(delete(Bookmark).where(Bookmark.user_id == user.id, Bookmark.kind == kind, Bookmark.movie_id.in_(ids)))
    db.commit()


@router.get("/{movie_id}")
async def get_movie(movie_id: int, user: User = Depends(current_user), db: Session = Depends(get_db), engine=Depends(get_engine)):
    movie = _movie(db, movie_id)
    await tmdb.enrich(db, [movie])
    sync(db, engine, movie)
    count = db.scalar(select(func.count()).select_from(Comment).where(Comment.movie_id == movie.id))
    return {**_details(engine, movie), "comments": count, "subtitles": captions.listing(db, engine, movie, user)}


_audio_cache = {}  # movie id -> its audio tracks. shortcut: per process, and probed once


@router.get("/{movie_id}/audio")
async def audio_tracks(movie_id: int, db: Session = Depends(get_db), engine=Depends(get_engine)):
    movie = _movie(db, movie_id)
    if movie.id not in _audio_cache:
        source = await _open_source(db, engine, movie)  # the player is open: the torrent is running anyway
        try:
            _audio_cache[movie.id] = await transcode.probe_audio(source)
        except FileNotFoundError:  # no ffprobe: the player just offers the default track
            return []
    return _audio_cache[movie.id]


@router.post("/{movie_id}/download")
async def download(movie_id: int, db: Session = Depends(get_db), engine=Depends(get_engine)):
    """Start downloading on the server without playing: the movie will be there for later."""
    movie = _movie(db, movie_id)
    await _open_source(db, engine, movie)
    return _details(engine, movie)


async def _guarded(chunks):
    try:
        async for chunk in chunks:
            yield chunk
    except stream.StreamStalled:
        pass  # nothing arrived for too long: end the response, the player will ask again


@router.get("/{movie_id}/stream")
async def stream_movie(
    movie_id: int,
    request: Request,
    audio: int = Query(0, ge=0, le=31),  # which audio track: another one than the first goes through the converter
    start: int = Query(0, ge=0, le=86400),  # seconds to skip (only for a converted stream, which cannot be seeked)
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    engine=Depends(get_engine),
):
    movie = _movie(db, movie_id)
    source = await _open_source(db, engine, movie)
    movie.last_watched_at = datetime.now(timezone.utc)  # a movie nobody watches for a month gets deleted
    # one row per member and movie, however many ranges the player asks for; its time is the last one ("continue watching")
    db.merge(Watched(user_id=user.id, movie_id=movie.id, watched_at=datetime.now(timezone.utc)))
    db.commit()

    extension = os.path.splitext(movie.file_path)[1].lower()
    if extension not in MIME or audio or start:  # mkv, avi, …, or another audio track: converted on the fly
        try:
            chunks = await transcode.convert(source, audio, start)
        except FileNotFoundError:
            raise HTTPException(status_code=501, detail="ffmpeg is not installed on the server")
        return StreamingResponse(
            _guarded(chunks), media_type="video/mp4", headers={"Accept-Ranges": "none", "Cache-Control": "no-store"}
        )

    size = source.size
    try:
        requested = stream.parse_range(request.headers.get("range"), size)
    except stream.RangeNotSatisfiable:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    start, end = requested or (0, size - 1)
    headers = {"Accept-Ranges": "bytes", "Content-Length": str(end - start + 1), "Cache-Control": "no-store"}
    if requested:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(
        _guarded(stream.iter_bytes(source, start, end)),
        status_code=206 if requested else 200,
        media_type=MIME[extension],
        headers=headers,
    )
