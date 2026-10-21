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
TOP_TITLES, TOP_PEOPLE, TOP_FILMS = 3, 8, 25


async def discover(query, language="en"):
    """What TMDb knows under this name, in the member's language and in English: the titles (with every name they go by)
    and the people (a director, an actor…, with how well known they are). It is how a foreign title leads to the film's other names."""
    if not os.getenv("TMDB_API_KEY"):
        return {"titles": [], "people": []}
    tags = list(dict.fromkeys([LANGUAGE_TAGS.get(language, "en-US"), "en-US"]))
    try:
        async with _client() as client:
            answers = await asyncio.gather(*(_get(client, "/search/multi", query=query, language=tag, include_adult="false") for tag in tags))
    except (httpx.HTTPError, KeyError, ValueError) as e:
        logging.getLogger("uvicorn.error").warning("TMDb request failed: %s", type(e).__name__)
        raise TmdbError("TMDb unavailable") from e
    titles, people = {}, {}
    for answer in answers:
        for hit in answer.get("results", []):
            kind, key = hit.get("media_type"), hit.get("id")
            if kind == "person" and hit.get("name"):
                people.setdefault(key, {"id": key, "name": hit["name"], "department": hit.get("known_for_department"), "popularity": hit.get("popularity") or 0})
            elif kind in ("movie", "tv"):
                entry = titles.setdefault((kind, key), {"id": key, "year": _year(hit.get("release_date") or hit.get("first_air_date")), "names": []})
                for name in (hit.get("title") or hit.get("name"), hit.get("original_title") or hit.get("original_name")):
                    if name and name not in entry["names"]:
                        entry["names"].append(name)
    found = [t for t in titles.values() if t["names"]]  # the answers come in the order of relevance
    return {"titles": found[:TOP_TITLES], "people": list(people.values())[:TOP_PEOPLE]}


async def filmography(person_id):
    """The films a person directed and the films they acted in, the most voted first: {'director': [...], 'cast': [...]}."""
    try:
        async with _client() as client:
            credits = await _get(client, f"/person/{person_id}/combined_credits", language="en-US")
    except (httpx.HTTPError, KeyError, ValueError) as e:
        logging.getLogger("uvicorn.error").warning("TMDb request failed: %s", type(e).__name__)
        raise TmdbError("TMDb unavailable") from e

    def films(credit_list, keep):
        movies = [c for c in credit_list if c.get("media_type") == "movie" and c.get("title") and keep(c)]
        movies.sort(key=lambda c: c.get("vote_count") or 0, reverse=True)
        return [{"title": c["title"], "original_title": c.get("original_title") or c["title"], "year": _year(c.get("release_date"))} for c in movies[:TOP_FILMS]]

    return {"director": films(credits.get("crew", []), lambda c: c.get("job") == "Director"), "cast": films(credits.get("cast", []), lambda c: True)}
