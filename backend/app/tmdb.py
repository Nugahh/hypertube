"""What TMDb knows about a movie: summary, casting, length, rating, poster. Needs TMDB_API_KEY in .env, else nothing is added."""
import asyncio
import logging
import os
import re
import time

import httpx
from sqlalchemy.exc import IntegrityError

from app.models import MovieInfo

API = "https://api.themoviedb.org/3"
IMAGES = "https://image.tmdb.org/t/p/w500"
CAST_SIZE = 8
PAUSE = 60  # seconds before asking again about a movie TMDb failed on
BATCH = 16  # movies looked up (and kept) at a time

# movie id -> when it may be asked again. shortcut: kept in memory, a restart forgets it; fine for a pause this short
_retry_after = {}

_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
# what a release name adds after the title: the resolution, the source, the codec
_TAGS = re.compile(
    r"\b(?:(?:480|576|720|1080|2160)[pi]|4k|uhd|blu ?ray|bd ?rip|br ?rip|dvd ?rip|dvd ?scr|web ?rip|web[ -]?dl|hd ?rip|hdtv|hd ?cam|remux"
    r"|x ?264|x ?265|h ?264|h ?265|hevc|xvid|divx)\b",
    re.I,
)
_EDGE = re.compile(r"^[\s\-\u2013\u2014:,;|/+~]+|[\s\-\u2013\u2014:,;|/+~]+$")  # separators left at either end


class TmdbError(Exception):
    pass


def _client():
    return httpx.AsyncClient(timeout=8)


def clean_title(raw):
    """'Heat.1995.1080p.BluRay.x264-GROUP' -> 'Heat': what a torrent calls a movie, as words: dots and underscores are
    spaces, and the year, the resolution, the source and the codec (everything after them) are gone."""
    s = re.sub(r"[._]+", " ", raw)
    s = re.sub(r"[\[(].*?[\])]", " ", s)
    # the last year or the first tag starts the tail ("2001 A Space Odyssey 1968" keeps its first 2001)
    cut = min((m.start() for m in _TAGS.finditer(s)), default=len(s))
    years = list(_YEAR.finditer(s))
    if years:
        cut = min(cut, years[-1].start())
    return _EDGE.sub("", re.sub(r"\s+", " ", s[:cut] if cut > 0 else s))


async def _get(client, path, **params):
    key = os.getenv("TMDB_API_KEY", "")
    headers = {"Authorization": f"Bearer {key}"} if key.startswith("eyJ") else {}  # v4 read token, else v3 key
    if not headers:
        params["api_key"] = key
    res = await client.get(f"{API}{path}", params=params, headers=headers)
    res.raise_for_status()
    return res.json()


def _year(date):
    return int(date[:4]) if date and date[:4].isdigit() else None


def _normalize(kind, d, tmdb_id):
    crew = (d.get("credits") or {}).get("crew", [])
    cast = (d.get("credits") or {}).get("cast", [])
    if kind == "movie":
        directors, runtime, date = [c["name"] for c in crew if c.get("job") == "Director"], d.get("runtime"), d.get("release_date")
    else:
        directors, runtime, date = [c["name"] for c in d.get("created_by", [])], (d.get("episode_run_time") or [None])[0], d.get("first_air_date")
    return {
        "tmdb_id": tmdb_id,
        "kind": kind,
        "overview": d.get("overview") or None,
        "runtime": runtime or None,
        # TMDb says 0.0 for a title nobody rated
        "rating": round(d["vote_average"], 1) if d.get("vote_count") and d.get("vote_average") else None,
        "year": _year(date),
        "poster": IMAGES + d["poster_path"] if d.get("poster_path") else None,
        "language": d.get("original_language"),
        "genres": [g["name"] for g in d.get("genres", [])],
        "directors": directors,
        "producers": [c["name"] for c in crew if c.get("job") == "Producer"],
        "cast": [c["name"] for c in cast[:CAST_SIZE]],
    }


async def lookup(title, year):
    """The info of a movie (else of a series) with this name; None when TMDb has nothing, TmdbError when it cannot be asked."""
    if not os.getenv("TMDB_API_KEY"):
        return None
    name = clean_title(title)
    try:
        async with _client() as client:
            for kind in ("movie", "tv"):
                params = {"query": name, "include_adult": "false"}
                if year and kind == "movie":
                    params["year"] = year
                found = (await _get(client, f"/search/{kind}", **params))["results"]
                if found:
                    details = await _get(client, f"/{kind}/{found[0]['id']}", append_to_response="credits")
                    return _normalize(kind, details, found[0]["id"])
    except (httpx.HTTPError, KeyError, ValueError) as e:
        # never forward or log str(e): httpx errors embed the URL, API key included
        logging.getLogger("uvicorn.error").warning("TMDb request failed: %s", type(e).__name__)
        raise TmdbError("TMDb unavailable") from e
    return None


async def enrich(db, movies):
    """Ask TMDb about the movies it has not been asked about yet, at most 8 at a time, and keep the answers."""
    if not os.getenv("TMDB_API_KEY"):
        return
    now = time.monotonic()
    todo = [m for m in movies if m.info is None and _retry_after.get(m.id, 0) <= now]
    if not todo:
        return
    gate = asyncio.Semaphore(8)

    async def ask(movie):
        async with gate:
            try:
                return await lookup(movie.title, movie.year)
            except TmdbError:
                _retry_after[movie.id] = now + PAUSE
                raise

    for start in range(0, len(todo), BATCH):  # kept batch by batch: a caller that gives up halfway keeps what was done
        batch = todo[start : start + BATCH]
        answers = await asyncio.gather(*(ask(m) for m in batch), return_exceptions=True)
        for movie, info in zip(batch, answers):
            if not isinstance(info, Exception):  # a failed one is simply asked again after the pause
                movie.info = MovieInfo(**(info or {}))  # nothing found is remembered too, as an empty row
                db.add(movie)
        try:
            db.commit()
        except IntegrityError:  # another request stored the answer for the same movie meanwhile
            db.rollback()


LANGUAGE_TAGS = {"fr": "fr-FR", "en": "en-US"}
MAX_PAGES = 500  # TMDb lists no further
_genres = {}  # (kind, language) -> {genre id: name}. shortcut: kept in memory, a restart asks again


# TMDb's French list of series genres keeps some English names
FR_GENRES = {
    "Action & Adventure": "Action & Aventure", "Kids": "Enfants", "News": "Actualités", "Reality": "Téléréalité",
    "Soap": "Feuilleton", "Talk": "Talk-show", "War & Politics": "Guerre & Politique",
}


def _genre(name, language):
    return FR_GENRES.get(name, name) if language.startswith("fr") else name


async def _call(path, **params):
    """One TMDb request: its JSON. LookupError when TMDb has no such thing, TmdbError when it cannot be asked."""
    try:
        async with _client() as client:
            return await _get(client, path, **params)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise LookupError(path) from e
        logging.getLogger("uvicorn.error").warning("TMDb request failed: %s", type(e).__name__)
        raise TmdbError("TMDb unavailable") from e
    except (httpx.HTTPError, KeyError, ValueError) as e:
        logging.getLogger("uvicorn.error").warning("TMDb request failed: %s", type(e).__name__)
        raise TmdbError("TMDb unavailable") from e


async def genre_names(kind, language):
    """TMDb's genres of films (kind "movie") or series ("tv"), in that language: {id: name}."""
    if (kind, language) not in _genres:
        found = await _call(f"/genre/{kind}/list", language=language)
        _genres[(kind, language)] = {g["id"]: _genre(g["name"], language) for g in found["genres"]}
    return _genres[(kind, language)]


async def browse(kind, genre, page, language, q=None):
    """One page of the catalogue: the films or series TMDb lists by popularity (of a genre, or all), or the ones that answer
    the search `q` (best match first; TMDb does not filter a search by genre), as thumbnails."""
    names = await genre_names(kind, language)
    params = {"language": language, "page": page, "include_adult": "false"}
    if q:
        path, params["query"] = f"/search/{kind}", q
    else:
        path = f"/discover/{kind}"
        params |= {"sort_by": "popularity.desc", "vote_count.gte": 100}  # nobody-rated titles are no catalogue
        if genre:
            params["with_genres"] = genre
    found = await _call(path, **params)
    items = [
        {
            "kind": kind,
            "id": d["id"],
            "title": d.get("title") or d.get("name") or "",
            "year": _year(d.get("release_date") or d.get("first_air_date")),
            "rating": round(d["vote_average"], 1) if d.get("vote_count") and d.get("vote_average") else None,
            "poster": IMAGES + d["poster_path"] if d.get("poster_path") else None,
            "overview": d.get("overview") or None,
            "genres": [names[i] for i in d.get("genre_ids", []) if i in names],
        }
        for d in found["results"]
    ]
    return {"items": items, "total": found["total_results"], "pages": found["total_pages"]}


_words = {}  # (kind, tmdb id, language) -> title, summary and genres in that language. shortcut: kept in memory, a restart asks again


async def in_language(kind, tmdb_id, language):
    """What a stored title says in the member's language (the rows keep the language they were first asked in); None when TMDb cannot say."""
    key = (kind, tmdb_id, language)
    if key not in _words:
        try:
            d = await title_sheet(kind, tmdb_id, language)
        except (TmdbError, LookupError):
            return None
        _words[key] = {k: d[k] for k in ("title", "overview", "genres")}
    return _words[key]


async def title_sheet(kind, tmdb_id, language):
    """Everything TMDb has on one film or series: summary, length, rating, genres, directors, cast."""
    d = await _call(f"/{kind}/{tmdb_id}", language=language, append_to_response="credits")
    title = d.get("title") or d.get("name") or ""
    sheet = _normalize(kind, d, tmdb_id)
    sheet["genres"] = [_genre(g, language) for g in sheet["genres"]]
    return {**sheet, "title": title, "original_title": d.get("original_title") or d.get("original_name") or title}
