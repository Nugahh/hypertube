"""Second search source: the Blender Foundation's open movies, all released under Creative Commons licences.

Four are seeded with a web seed by webtorrent.io (they play without any peer and bring subtitles), the others are
the Foundation's own uploads on the Internet Archive.
"""
from urllib.parse import quote

from app.jackett import words

PROVIDER = "Blender Open Movies"
GENRE = "blender"  # the row that shows only this source
WEBTORRENT = "https://webtorrent.io/torrents"


def _webtorrent(slug, folder, year, size):
    return dict(slug=slug, title=f"{folder} {year}", year=year, size=size,
                link=f"{WEBTORRENT}/{slug}.torrent", cover=f"{WEBTORRENT}/{quote(folder)}/poster.jpg")


def _archive(slug, item, title, year, size):
    return dict(slug=slug, title=f"{title} {year}", year=year, size=size,
                link=f"https://archive.org/download/{item}/{item}_archive.torrent", cover=f"https://archive.org/services/img/{item}")


# size: bytes of the video file the player gets
FILMS = [
    _webtorrent("big-buck-bunny", "Big Buck Bunny", 2008, 276134947),
    _webtorrent("sintel", "Sintel", 2010, 129241752),
    _webtorrent("tears-of-steel", "Tears of Steel", 2012, 571346576),
    _webtorrent("cosmos-laundromat", "Cosmos Laundromat", 2015, 220087570),
    _archive("elephants-dream", "elephants-dream-2006", "Elephants Dream", 2006, 298488038),
    _archive("spring", "spring_blenderopenmovie", "Spring", 2019, 48274047),
    _archive("caminandes-llama-drama", "caminandes-1-llama-drama", "Caminandes: Llama Drama", 2013, 16731934),
    _archive("caminandes-llamigos", "caminandes-3-llamigos", "Caminandes: Llamigos", 2016, 42736609),
    _archive("glass-half", "Glass_201703", "Glass Half", 2015, 65761189),
]


def search(q, genre=None):
    if genre not in (None, "populaires", GENRE):
        return []  # the other rows are archive.org's or come from TMDb's genres
    wanted = [w.lower() for w in words(q)]
    found = []
    for film in FILMS:
        if all(w in film["title"].lower() for w in wanted):
            found.append(
                {
                    "id": f"blender:{film['slug']}",
                    "title": film["title"],
                    "year": film["year"],
                    "resolution": None,
                    "size": film["size"],
                    # the web seed is always available and counts as one seeder
                    "seeders": 1,
                    "peers": 1,
                    "provider": PROVIDER,
                    "cover": film["cover"],
                    "link": film["link"],
                }
            )
    return found
