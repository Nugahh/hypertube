import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

JACKETT_URL = os.getenv("JACKETT_URL", "http://localhost:9117")
INDEXER = os.getenv("JACKETT_INDEXER", "internetarchive")
CONFIG_FILE = os.getenv("JACKETT_CONFIG", "/jackett-config/Jackett/ServerConfig.json")

TORZNAB = "{http://torznab.com/schemas/2015/feed}"
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
RESOLUTION = re.compile(r"\b(?:480|576|720|1080|2160)p\b", re.I)
ARCHIVE_ID = re.compile(r"https://archive\.org/details/([^/?#]+)")


FILMS = "collection:feature_films"


def _genre(label, query, section="films"):
    return {"label": label, "query": query, "section": section}


# archive.org queries (Lucene syntax) behind each row of the site; the first one is also the home page
GENRES = {
    # labels are English (the default language); the front translates them by id
    "populaires": _genre("Popular", FILMS),
    # not an archive.org query: this row comes from the second source (blender.py)
    "blender": _genre("Open movies", ""),
    "comedie": _genre("Comedy", f'{FILMS} AND subject:"comedy"'),
    "drame": _genre("Drama", f'{FILMS} AND subject:"drama"'),
    "policier": _genre("Crime", f'{FILMS} AND subject:"crime"'),
    "noir": _genre("Film noir", f'{FILMS} AND subject:"film noir"'),
    "western": _genre("Western", f'{FILMS} AND subject:"western"'),
    "horreur": _genre("Sci-fi & horror", "collection:SciFi_Horror"),
    "documentaire": _genre("Documentaries", f'{FILMS} AND subject:"documentary"'),
    "muets": _genre("Silent films", "collection:silent_films"),
    "animation": _genre("Animation", "collection:animationandcartoons"),
    "series": _genre("Classic TV series", "collection:classic_tv", "series"),
}


class JackettError(Exception):
    pass


def words(q):
    # archive.org parses the query as Lucene: strip the syntax characters, an unbalanced "(" makes it fail
    return re.sub(r"[^\w\s']", " ", q).split()


def build_query(q, genre=None):
    joined = " ".join(words(q))
    base = GENRES[genre or "populaires"]["query"]
    if not joined:
        return base
    return f"({joined}) AND ({base})" if genre else joined


def parse_title(title):
    years = YEAR.findall(title)
    resolution = RESOLUTION.search(title)
    # the last year wins: "2001 A Space Odyssey 1968" is a 1968 film
    return (
        int(years[-1]) if years else None,
        resolution.group().lower() if resolution else None,
    )


def parse_results(xml):
    root = ET.fromstring(xml)
    if root.tag == "error":
        # error 900 puts a whole .NET stack trace in the description: keep the first line
        raise JackettError((root.get("description") or "Jackett error").splitlines()[0])
    results = []
    for item in root.iter("item"):
        attrs = {a.get("name"): a.get("value") for a in item.findall(f"{TORZNAB}attr")}
        title = item.findtext("title", "")
        year, resolution = parse_title(title)
        archive = ARCHIVE_ID.match(item.findtext("comments", ""))
        results.append(
            {
                "id": item.findtext("guid", ""),
                "title": title,
                "year": year,
                "resolution": resolution,
                "size": int(item.findtext("size") or 0),
                "seeders": int(attrs.get("seeders", 0)),
                "peers": int(attrs.get("peers", 0)),
                "provider": item.findtext("jackettindexer", ""),
                "cover": f"https://archive.org/services/img/{archive[1]}" if archive else None,
                # Jackett proxy URL carrying the API key: server side only, never sent to the browser
                "link": item.findtext("link", ""),
            }
        )
    return sorted(results, key=lambda r: r["seeders"], reverse=True)


def _api_key():
    return os.getenv("JACKETT_API_KEY") or json.loads(Path(CONFIG_FILE).read_text())["APIKey"]


async def fetch_xml(q):
    # as long as Jackett's own HTTP timeout: giving up earlier makes Jackett flag its indexer as failing
    async with httpx.AsyncClient(timeout=100) as client:
        res = await client.get(
            f"{JACKETT_URL}/api/v2.0/indexers/{INDEXER}/results/torznab/api",
            # cat=2000 is Torznab "Movies": without it an empty query returns every kind of upload
            params={"apikey": _api_key(), "t": "search", "cat": 2000, "q": q},
        )
        res.raise_for_status()
        return res.text


async def fetch_torrent(link):
    """The .torrent file behind a result's link (Jackett fetches it from the provider)."""
    try:
        async with httpx.AsyncClient(timeout=100) as client:
            res = await client.get(link)
            res.raise_for_status()
            return res.content
    except httpx.HTTPError as e:
        logging.getLogger("uvicorn.error").warning("Torrent download failed: %s", type(e).__name__)
        raise JackettError("Jackett unavailable") from e  # never forward str(e): it holds the URL and its API key


async def _run(query):
    try:
        return parse_results(await fetch_xml(query))
    except (httpx.HTTPError, OSError, KeyError, ET.ParseError) as e:
        # never forward or log str(e): httpx errors embed the URL, API key included
        logging.getLogger("uvicorn.error").warning("Jackett request failed: %s", type(e).__name__)
        raise JackettError("Jackett unavailable") from e


async def lucene(query):
    """A raw archive.org (Lucene) query through Jackett: every result, most seeded first, unfiltered."""
    return await _run(query)


async def search(q, genre=None):
    results = await _run(build_query(q, genre))
    wanted = [w.lower() for w in words(q)]
    if not wanted:
        return results  # home page: archive.org's most downloaded films
    # archive.org also matches descriptions, keep only titles with every word; the subject wants name order
    matching = [r for r in results if all(w in r["title"].lower() for w in wanted)]
    return sorted(matching, key=lambda r: r["title"].lower())
