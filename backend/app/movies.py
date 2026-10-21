import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import engine as engine_module
from app import captions, jackett, sources, stream, tmdb, transcode
from app.auth import current_user
from app.db import get_db
from app.engine import get_engine
from app.models import Comment, Movie, User, Watched

# what the browser may know about a movie: the provider link and the torrent never leave the server
PUBLIC = ("id", "title", "year", "resolution", "size", "seeders", "peers", "provider", "cover")
LISTS = ("directors", "producers", "cast", "genres")
MIME = {".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm"}

router = APIRouter(prefix="/api/movies", dependencies=[Depends(current_user)])
front_page = APIRouter(prefix="/api/movies")  # the one movie route open to everyone
TOP = 20


def public(movie):
    data = {k: getattr(movie, k) for k in PUBLIC}
    info = movie.info
    data["rating"] = info.rating if info else None
    if info:  # TMDb's poster is nicer than the provider's thumbnail, its year more reliable than the one in the title
        data["cover"] = info.poster or data["cover"]
        data["year"] = data["year"] or info.year
    return data


def present(db, user, movies, matches=None):
    """The thumbnails of these movies for one member: public fields, whether they watched it, and (for a search) why it matched."""
    seen = set(db.scalars(select(Watched.movie_id).where(Watched.user_id == user.id, Watched.movie_id.in_([m.id for m in movies]))))
    matches = matches or {}
    return [{**public(m), "watched": m.id in seen, "match": matches.get(m.id)} for m in movies]


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


def keep(movie, year_from, year_to, min_rating):
    year, rating = _year(movie), _rating(movie)
    return (
        (year_from is None or (year is not None and year >= year_from))
        and (year_to is None or (year is not None and year <= year_to))
        and (min_rating is None or (rating is not None and rating >= min_rating))
    )


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


def _details(engine, movie):
    torrent = engine.get(movie.infohash) if movie.status == "downloading" else None
    progress = 1 if movie.status == "ready" else torrent.progress if torrent else 0
    return {
        **public(movie),
        **_sheet(movie),
        "state": movie.status,
        # whether the browser plays the file as it is (else it is converted); unknown until the torrent has been opened
        "native": os.path.splitext(movie.file_path)[1].lower() in MIME if movie.file_path else None,
        "progress": progress,
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
            torrent = engine.add(await jackett.fetch_torrent(movie.link))
        except jackett.JackettError as e:
            raise HTTPException(status_code=502, detail=str(e))
        except engine_module.InvalidTorrent:
            raise HTTPException(status_code=502, detail="The provider sent an invalid torrent")
        except engine_module.NoVideo:
            raise HTTPException(status_code=422, detail="No video in this torrent")
        movie.status, movie.infohash, movie.file_path = "downloading", torrent.infohash, torrent.file_path
        db.commit()
    return torrent


@front_page.get("")
async def top_movies(db: Session = Depends(get_db)):
    """The front page: the most popular movies, by id and name (the details are for members)."""
    try:
        found = upsert_results(db, await sources.search("", None))
    except jackett.JackettError as e:
        raise HTTPException(status_code=502, detail=str(e))
    top = arrange(found, "popularity", "desc")[:TOP]
    await tmdb.enrich(db, top)
    return [{"id": m.id, "name": m.title, "year": _year(m), "rating": _rating(m)} for m in top]


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
    db.merge(Watched(user_id=user.id, movie_id=movie.id))  # one row per member and movie, however many ranges the player asks for
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
