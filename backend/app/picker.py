"""Which torrents to offer for a film: no cinema recordings, one per release, the best three of each resolution."""
import re

CAM = re.compile(r"\b(CAM|TS|TELESYNC|TC|SCREENER|SCR|HDCAM)\b", re.I)  # a cinema recording: nobody wants to watch it
TIERS = ("4K", "1080p", "720p")  # a release that is neither of the first two is listed as 720p
PER_TIER = 3
GB = 1024**3


def score(result):
    """How good a copy looks: well seeded, a swarm with leechers, the size of a film (not a remux), a modern codec."""
    seeders, peers = result["seeders"], result["peers"]
    points = min(seeders, 500)
    if seeders < 3:
        points -= 1000
    if seeders > 10:
        points += 500
    if seeders > 0 and peers > 0:
        if 0.5 < seeders / peers < 5:
            points += 400
    elif seeders > 0:  # nobody else is downloading
        points -= 200
    gigabytes = result["size"] / GB
    if 1.5 < gigabytes < 5:
        points += 300
    elif gigabytes > 10:
        points -= 150
    title = result["title"].upper()
    if "X265" in title or "HEVC" in title:
        points += 150
    return points


def tier(title):
    """The tab a release is listed in: 4K, 1080p, or 720p for everything else."""
    title = title.upper()
    return "4K" if "2160P" in title or "4K" in title else "1080p" if "1080P" in title else "720p"


def pick(results):
    """The copies worth offering: 4K first, then 1080p, then the rest; the best scored first inside each."""
    releases = {}
    for r in results:
        if CAM.search(r["title"]):
            continue
        key = (re.sub(r"[^A-Z0-9]", "", r["title"].upper()), r["size"])  # the same release from two providers
        if key not in releases or r["seeders"] > releases[key]["seeders"]:
            releases[key] = r
    tiers = {name: [] for name in TIERS}
    for r in releases.values():
        tiers[tier(r["title"])].append(r)
    return [r for name in TIERS for r in sorted(tiers[name], key=score, reverse=True)[:PER_TIER]]
