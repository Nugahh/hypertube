import asyncio
import time

from app import blender, jackett

TTL = 300  # seconds a search is remembered: scrolling through pages must not ask Jackett again for every page
RETRY = 60  # seconds a search made without the Internet Archive is remembered, so it is tried again soon
SLOW = 10  # seconds the Internet Archive gets before the open movies are shown without it
_down_until = 0  # until then the Internet Archive is not waited for: it did not answer in time a moment ago
_cache = {}  # key -> (expires at, results). shortcut: in memory and per process; use a shared cache (Redis) if the backend ever runs several workers


def _keep(key, found, ttl):
    _cache[key] = (time.monotonic() + ttl, found)
    return found


def is_down():
    return time.monotonic() < _down_until


def mark_down():
    global _down_until
    _down_until = time.monotonic() + RETRY


def _merge(q, found, own):
    merged = found + own
    # the subject wants search results in name order; the home page keeps popularity order
    return sorted(merged, key=lambda r: r["title"].lower()) if jackett.words(q) else merged


def _arrived(key, q, own, task):
    """The Internet Archive finally answered, after the open movies were shown alone: its answer takes their place."""
    global _down_until
    if not task.cancelled() and task.exception() is None:
        _down_until = 0  # it answers again
        _keep(key, _merge(q, task.result(), own), TTL)


async def search(q, genre=None):
    """Every source at once. A source that fails only matters when the other has nothing to show."""
    key = (q.strip().lower(), genre)
    cached = _cache.get(key)
    if cached and time.monotonic() < cached[0]:
        return cached[1]
    own = blender.search(q, genre)
    if genre == blender.GENRE:
        return _keep(key, own, TTL)
    if is_down():  # every row of a page asks at once: only the first one waits, the others do not pile requests up on it
        if own:
            return own
        raise jackett.JackettError("The Internet Archive does not answer")
    task = asyncio.ensure_future(jackett.search(q, genre))
    await asyncio.wait({task}, timeout=SLOW)
    if not task.done():
        mark_down()
        # the request is not dropped: Jackett flags its indexer as failing when the client gives up
        task.add_done_callback(lambda t: _arrived(key, q, own, t))
        if own:
            return _keep(key, own, RETRY)
        raise jackett.JackettError("The Internet Archive is slow to answer")
    try:
        found = task.result()
    except jackett.JackettError:
        if own:
            return _keep(key, own, RETRY)
        raise
    return _keep(key, _merge(q, found, own), TTL)
