"""OpenSubtitles (https://www.opensubtitles.com): search and download subtitles for a movie.

Needs OPENSUBTITLES_API_KEY; with OPENSUBTITLES_USERNAME and OPENSUBTITLES_PASSWORD too, the calls are made as that account
(higher download quota). Nothing here has been run against the live service: the calls follow its REST API v1 documentation.
"""
import logging
import os
import re
import time
from urllib.parse import urlparse

import httpx

API = "https://api.opensubtitles.com/api/v1"
USER_AGENT = "Hypertube v1.0"
MAX_BYTES = 2 * 1024 * 1024
TOKEN_SECONDS = 20 * 3600  # a token lasts 24 h

_token = None  # (jwt, monotonic time it expires). shortcut: per process, a restart logs in again


class OpenSubtitlesError(Exception):
    pass


class OpenSubtitlesQuota(OpenSubtitlesError):
    """The account's downloads for the day are used up (shared by every member of the site)."""


def configured():
    return bool(os.getenv("OPENSUBTITLES_API_KEY"))


def _client():
    # the API redirects a request whose parameters are not in its canonical form (see search): follow it
    return httpx.AsyncClient(timeout=15, follow_redirects=True)


async def _headers(client):
    global _token
    headers = {"Api-Key": os.environ["OPENSUBTITLES_API_KEY"], "User-Agent": USER_AGENT, "Accept": "application/json"}
    user, password = os.getenv("OPENSUBTITLES_USERNAME"), os.getenv("OPENSUBTITLES_PASSWORD")
    if user and password:
        if _token is None or _token[1] < time.monotonic():
            res = await client.post(f"{API}/login", headers=headers, json={"username": user, "password": password})
            res.raise_for_status()
            _token = (res.json()["token"], time.monotonic() + TOKEN_SECONDS)
        headers["Authorization"] = f"Bearer {_token[0]}"
    return headers


def _fail(e):
    # never forward or log str(e): it can hold the URL and headers
    logging.getLogger("uvicorn.error").warning("OpenSubtitles request failed: %s", type(e).__name__)
    return OpenSubtitlesError("OpenSubtitles unavailable")


async def search(query, lang, tmdb_id=None, year=None):
    """[{file_id, lang, release, downloads, title, year}]: the film asked for first (the search is fuzzy), the most downloaded first."""
    params = {"query": query, "languages": lang}
    if tmdb_id:
        params["tmdb_id"] = tmdb_id
    if year:
        params["year"] = year
    params = dict(sorted(params.items()))  # the docs: parameters in alphabetical order (httpx writes spaces as +, as they want)
    try:
        async with _client() as client:
            res = await client.get(f"{API}/subtitles", params=params, headers=await _headers(client))
            res.raise_for_status()
            data = res.json()["data"]
    except (httpx.HTTPError, KeyError, ValueError) as e:
        raise _fail(e) from e
    wanted = set(re.findall(r"[a-z0-9]+", query.lower()))
    found = []
    for item in data:
        attrs = item.get("attributes") or {}
        files = attrs.get("files") or []
        if not files or "file_id" not in files[0]:
            continue
        feature = attrs.get("feature_details") or {}
        title = feature.get("title") or ""
        names = set(re.findall(r"[a-z0-9]+", f"{title} {feature.get('parent_title') or ''}".lower()))
        found.append(
            {
                "file_id": files[0]["file_id"],
                "lang": attrs.get("language") or lang,
                "release": (attrs.get("release") or files[0].get("file_name") or "")[:120],
                "downloads": attrs.get("download_count") or 0,
                "title": title,
                "year": feature.get("year"),
                # kept apart for the ranking: is it the film that was asked for, in the right year, human made?
                "_rank": (not (names and (wanted <= names or names <= wanted)), bool(year and feature.get("year") and feature["year"] != year), bool(attrs.get("machine_translated") or attrs.get("ai_translated"))),
            }
        )
    # the search is fuzzy ("Big Buck Bunny" also finds "The House Bunny"): only the film asked for is offered, a wrong
    # subtitle added by mistake is worse than none (the member can still import a file)
    best = [f for f in found if not f["_rank"][0]]
    ranked = sorted(best, key=lambda f: (*f["_rank"], -f["downloads"]))[:20]
    for f in ranked:
        del f["_rank"]
    return ranked


def _trusted(link):
    url = urlparse(link)
    return url.scheme == "https" and (url.hostname or "").endswith(".opensubtitles.com")


async def _fetch_file(client, link):
    """The subtitle file at a link; a redirect is followed by hand, and only inside OpenSubtitles."""
    for _ in range(3):
        # no API headers: the key is for the API, not for the file server
        async with client.stream("GET", link, follow_redirects=False) as file:
            if file.is_redirect:
                link = str(file.url.join(file.headers["location"]))
                if not _trusted(link):
                    raise ValueError("untrusted redirect")
                continue
            file.raise_for_status()
            data = b""
            async for chunk in file.aiter_bytes():
                data += chunk
                if len(data) > MAX_BYTES:
                    raise ValueError("too big")
            return data
    raise ValueError("too many redirects")


async def download(file_id):
    """The bytes of a subtitle file: OpenSubtitles gives a temporary link, then serves the file from it."""
    try:
        async with _client() as client:
            res = await client.post(f"{API}/download", headers={**await _headers(client), "Content-Type": "application/json"}, json={"file_id": file_id})
            res.raise_for_status()
            link = res.json()["link"]
            if not _trusted(link):  # the answer comes from the network: never fetch an arbitrary address
                raise ValueError("untrusted link")
            return await _fetch_file(client, link)
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (406, 429):  # shortcut: the status OpenSubtitles uses for a spent quota is from its docs, not verified
            logging.getLogger("uvicorn.error").warning("OpenSubtitles download refused: %s", e.response.status_code)
            raise OpenSubtitlesQuota("OpenSubtitles download quota reached") from e
        raise _fail(e) from e
    except (httpx.HTTPError, KeyError, ValueError) as e:
        raise _fail(e) from e
