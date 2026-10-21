import asyncio
import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

JACKETT_URL = os.getenv("JACKETT_URL", "http://localhost:9117")
INDEXER = os.getenv("JACKETT_INDEXER", "all")  # "all" asks every indexer configured in Jackett
# other Jackett indexers (comma separated ids) searched next to it; legal sources only
EXTRA = [i.strip() for i in os.getenv("JACKETT_EXTRA_INDEXERS", "").split(",") if i.strip()]
CONFIG_FILE = os.getenv("JACKETT_CONFIG", "/jackett-config/Jackett/ServerConfig.json")

TORZNAB = "{http://torznab.com/schemas/2015/feed}"
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
RESOLUTION = re.compile(r"\b(?:480|576|720|1080|2160)p\b", re.I)


class JackettError(Exception):
    pass


def words(q):
    # some indexers parse the query as a syntax (Lucene…): strip its characters, an unbalanced "(" makes them fail
    return re.sub(r"[^\w\s']", " ", q).split()


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
                "cover": None,  # the indexers' own image URL carries Jackett's API key: TMDb gives the poster
                # Jackett proxy URL carrying the API key: server side only, never sent to the browser
                "link": item.findtext("link", ""),
            }
        )
    return sorted(results, key=lambda r: r["seeders"], reverse=True)


def _api_key():
    return os.getenv("JACKETT_API_KEY") or json.loads(Path(CONFIG_FILE).read_text())["APIKey"]


async def fetch_xml(q, indexer=None):
    # as long as Jackett's own HTTP timeout: giving up earlier makes Jackett flag its indexer as failing
    async with httpx.AsyncClient(timeout=100) as client:
        res = await client.get(
            f"{JACKETT_URL}/api/v2.0/indexers/{indexer or INDEXER}/results/torznab/api",
            # cat=2000 is Torznab "Movies": without it an empty query returns every kind of upload
            params={"apikey": _api_key(), "t": "search", "cat": 2000, "q": q},
        )
        res.raise_for_status()
        return res.text


async def fetch_torrent(link):
    """The torrent behind a result's link: the bytes of a .torrent file (Jackett fetches it from the provider), or a magnet
    link (str) for a provider that only has those: its link is one, or Jackett's download URL redirects to one."""
    if link.startswith("magnet:"):
        return link
    try:
        async with httpx.AsyncClient(timeout=100) as client:
            res = await client.get(link)  # a redirect is not followed: its address is the answer
            if res.is_redirect and res.headers.get("location", "").startswith("magnet:"):
                return res.headers["location"]
            res.raise_for_status()
            return res.text if res.content.startswith(b"magnet:") else res.content
    except httpx.HTTPError as e:
        logging.getLogger("uvicorn.error").warning("Torrent download failed: %s", type(e).__name__)
        raise JackettError("Jackett unavailable") from e  # never forward str(e): it holds the URL and its API key


async def _run(query, indexer=None):
    try:
        return parse_results(await (fetch_xml(query) if indexer is None else fetch_xml(query, indexer)))
    except (httpx.HTTPError, OSError, KeyError, ET.ParseError) as e:
        # never forward or log str(e): httpx errors embed the URL, API key included
        logging.getLogger("uvicorn.error").warning("Jackett request failed: %s", type(e).__name__)
        raise JackettError("Jackett unavailable") from e


async def _all_of(jobs):
    """Every indexer at once: what those that answered found (most seeded first), an error only when none answered."""
    answers = await asyncio.gather(*jobs, return_exceptions=True)
    answered = [a for a in answers if not isinstance(a, Exception)]
    if not answered:
        raise answers[0]
    return sorted((r for a in answered for r in a), key=lambda r: r["seeders"], reverse=True)


async def search(q):
    """What the indexers have for these words (with none: what they list by default): most seeded first, or by name when
    words were given."""
    query = " ".join(words(q))
    results = await _all_of([_run(query)] + [_run(query, i) for i in EXTRA])
    wanted = [w.lower() for w in words(q)]
    # an indexer also matches descriptions: keep only titles with every word; the subject wants name order
    matching = [r for r in results if all(w in r["title"].lower() for w in wanted)]
    return sorted(matching, key=lambda r: r["title"].lower()) if wanted else matching
