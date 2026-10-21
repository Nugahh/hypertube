import time

from app import blender, jackett

TTL = 300  # seconds a search is remembered: scrolling through pages must not ask Jackett again for every page
_cache = {}  # shortcut: in memory and per process; use a shared cache (Redis) if the backend ever runs several workers


async def search(q, genre=None):
    key = (q.strip().lower(), genre)
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < TTL:
        return cached[1]
    found = await _search(q, genre)
    _cache[key] = (time.monotonic(), found)
    return found


async def _search(q, genre):
    """Every source at once. A source that fails only matters when the other has nothing to show."""
    own = blender.search(q, genre)
    if genre == blender.GENRE:
        return own
    try:
        found = await jackett.search(q, genre)
    except jackett.JackettError:
        if own:
            return own
        raise
    merged = found + own
    # the subject wants search results in name order; the home page keeps popularity order
    return sorted(merged, key=lambda r: r["title"].lower()) if jackett.words(q) else merged
