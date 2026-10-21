"""The search box: it looks everywhere (titles, other names of a film, directors and actors, summaries) and ranks the
films by how the query matches, the title first. Typos, accents and capitals do not matter."""
import asyncio
import logging
import re
import time
from dataclasses import dataclass

from sqlalchemy import select

from app import blender, jackett, movies, sources
from app import textmatch as tm
from app import tmdb
from app.models import Movie

# what a result is found by, best first; inside a level the films are in name order
LEVELS = {"exact": 100, "words": 90, "prefix": 80, "typo": 70, "alias": 60, "director": 50, "creator": 45, "cast": 40, "overview": 30, "other": 20}
TITLE_LEVELS = {tm.EXACT: LEVELS["words"], tm.PREFIX: LEVELS["prefix"], tm.TYPO: LEVELS["typo"]}
TTL = 300
EXPANSION_TIMEOUT = 30
MAX_TITLES = 40  # in one archive.org query
MAX_PEOPLE = 3  # people of that name whose films are looked up
DIRECTED, ACTED = 25, 15  # films taken from each list of a person

_cache = {}  # (folded query, genre, language) -> (time, [(movie id, level, kind, label)]). shortcut: per process


@dataclass
class Hit:
    movie: Movie
    level: int
    kind: str  # title | alias | director | creator | cast | overview | other
    label: str | None  # the name that matched (the director, the other title…)


def _term(token):
    typos = tm.allowed_typos(len(token))
    return f"{token}~{typos}" if typos else token  # archive.org (Lucene): word~1 also finds the words one slip away


def _all_of(raw):
    return "(" + " AND ".join(_term(t) for t in raw) + ")"


def _with(base, query):
    return f"{query} AND ({base})" if base else query


def _titles_query(titles, base):
    clean = [re.sub(r"\s+", " ", re.sub(r"[^\w\s'-]", " ", t)).strip() for t in titles]
    return _with(base, "(" + " OR ".join(f'title:"{t}"' for t in dict.fromkeys(c for c in clean if c)) + ")")


def _credited(result, films):
    """Is this archive.org result one of the person's films (same title, same year give or take one)?"""
    title = tm.fold(tmdb.clean_title(result["title"]))
    for film in films:
        if title in (tm.fold(film["title"]), tm.fold(film["original_title"])):
            if not (result["year"] and film["year"]) or abs(result["year"] - film["year"]) <= 1:
                return True
    return False


def _judge(movie, qt, qfold, reasons):
    """(level, kind, label) of the best way the query matches this movie, from its title, what the search found it by,
    and what TMDb told us about it earlier."""
    best = (0, "other", None)

    def consider(level, kind, label=None):
        nonlocal best
        if level > best[0]:
            best = (level, kind, label)

    title = tmdb.clean_title(movie.title)
    if tm.fold(title) == qfold:
        consider(LEVELS["exact"], "title")
    else:
        consider(TITLE_LEVELS.get(tm.match_quality(qt, tm.tokens(title)), 0), "title")
    for kind, label in reasons:
        consider(LEVELS[kind], kind, label)
    info = movie.info
    if info:
        for name in (info.directors or []) + (info.producers or []):
            if tm.match_quality(qt, tm.tokens(name)):
                consider(LEVELS["director"], "director", name)
        for name in info.cast or []:
            if tm.match_quality(qt, tm.tokens(name)):
                consider(LEVELS["cast"], "cast", name)
        if info.overview and tm.match_quality(qt, tm.tokens(info.overview)) == tm.EXACT:  # whole words only: a summary is long
            consider(LEVELS["overview"], "overview")
    return best


async def _expand(qt, qfold, raw, base, genre, language, reasons_for):
    """What TMDb adds: the other names of a film typed in another language, and the films of a person typed."""
    found = await tmdb.discover(" ".join(raw), language)
    jobs = []

    for entry in found["titles"]:
        scored = [(tm.match_quality(qt, tm.tokens(n)), n) for n in entry["names"]]
        quality, typed = max(scored, key=lambda s: s[0])
        if quality == 0:
            continue  # TMDb matched something loosely that does not look like what was typed
        for name in entry["names"]:
            if name != typed and tm.fold(name) != qfold:
                jobs.append(("alias", typed, jackett.search(name, genre), None))

    # people whose name looks like what was typed, the best known first ("chaplin" is also Oona and Geraldine Chaplin).
    # TMDb files Charlie Chaplin under "Acting" although he directed his films: both lists are always looked at.
    people = [p for p in found["people"] if tm.match_quality(qt, tm.tokens(p["name"]))]
    people = sorted(people, key=lambda p: -(p.get("popularity") or 0))[:MAX_PEOPLE]
    filmographies = await asyncio.gather(*(tmdb.filmography(p["id"]) for p in people), return_exceptions=True)
    for person, films in zip(people, filmographies):
        if isinstance(films, Exception):
            continue
        directed, acted = films["director"][:DIRECTED], films["cast"][:ACTED]
        names = [t for f in directed + acted for t in (f["title"], f["original_title"])][:MAX_TITLES]
        if names:
            jobs.append(("person", person["name"], jackett.lucene(_titles_query(names, base)), (directed, acted)))

    answers = await asyncio.gather(*(job[2] for job in jobs), return_exceptions=True)
    for (kind, label, _, credits), answer in zip(jobs, answers):
        if isinstance(answer, Exception):
            continue  # one expansion failing leaves the others
        for r in answer:
            if kind == "person":
                directed, acted = credits
                role = "director" if _credited(r, directed) else "cast" if _credited(r, acted) else None
                if role:
                    reasons_for(r, role, label)
            else:
                reasons_for(r, kind, label)


async def find(db, q, genre=None, language="en"):
    """The films that answer the query, as Hits, best first (level, then name). Raises JackettError when archive.org
    could not be asked and there is nothing else to show."""
    qt = tm.tokens(q)
    if not qt:
        return []
    qfold = " ".join(qt)
    key = (qfold, genre, language)
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < TTL:
        rows = {m.id: m for m in db.scalars(select(Movie).where(Movie.id.in_([c[0] for c in cached[1]])))}
        return [Hit(rows[i], level, kind, label) for i, level, kind, label in cached[1] if i in rows]

    raw = [t for t in re.findall(r"\w+", q.lower()) if len(t) > 1] or [q.strip().lower()]
    base = jackett.GENRES[genre]["query"] if genre and genre != blender.GENRE else None
    candidates = {}  # archive/open-movie id -> [result, [(kind, label)]]

    def add(result, kind=None, label=None):
        entry = candidates.setdefault(result["id"], [result, []])
        if kind:
            entry[1].append((kind, label))

    failure = None
    if genre != blender.GENRE:
        queries = (_with(base, _all_of(raw)), _with(base, "creator:" + _all_of(raw)))
        tasks = [] if sources.is_down() else [asyncio.ensure_future(jackett.lucene(query)) for query in queries]
        if not tasks:
            failure = jackett.JackettError("The Internet Archive does not answer")
        else:
            await asyncio.wait(tasks, timeout=sources.SLOW)
        for task, kind in zip(tasks, ("other", "creator")):
            if not task.done():  # not dropped: Jackett flags its indexer as failing when the client gives up
                task.add_done_callback(lambda t: t.cancelled() or t.exception())
                sources.mark_down()
                failure = failure or jackett.JackettError("The Internet Archive is slow to answer")
            elif task.exception():
                failure = failure or task.exception()
            else:
                for r in task.result():
                    add(r, kind)
        if tasks and all(task.done() for task in tasks):  # else archive.org does not answer: the expansions would only wait again
            try:
                await asyncio.wait_for(_expand(qt, qfold, raw, base, genre, language, lambda r, kind, label: add(r, kind, label)), EXPANSION_TIMEOUT)
            except Exception as e:  # TMDb is a bonus: a problem there never breaks the search
                logging.getLogger("uvicorn.error").warning("Search expansion failed: %s", type(e).__name__)
    for r in blender.search("", genre):  # nine films: compared locally, so typos and accents work on them too
        add(r)

    rows = movies.upsert_results(db, [r for r, _ in candidates.values()])
    known = {m.source_id for m in rows}
    local = [] if genre else [m for m in db.scalars(select(Movie)) if m.source_id not in known]  # what was seen before, with its details
    hits = []
    for movie, (_, reasons) in zip(rows, candidates.values()):
        level, kind, label = _judge(movie, qt, qfold, reasons)
        if level:
            hits.append(Hit(movie, level, kind, label))
    for movie in local:
        level, kind, label = _judge(movie, qt, qfold, [])
        if level >= LEVELS["overview"]:
            hits.append(Hit(movie, level, kind, label))
    if not hits and failure:
        raise failure
    hits.sort(key=lambda h: (-h.level, h.movie.title.lower()))
    if not failure:  # an answer made while archive.org was down must not stay for five minutes
        _cache[key] = (time.monotonic(), [(h.movie.id, h.level, h.kind, h.label) for h in hits])
    return hits
