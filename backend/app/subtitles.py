"""Subtitles that come with a torrent (.srt / .vtt files next to the video), offered to the player as WebVTT."""
import re
from pathlib import Path

from app import library

EXTENSIONS = (".srt", ".vtt")
MAX_BYTES = 2 * 1024 * 1024  # a subtitle file is a few dozen kB: anything bigger is not one

LABELS = {"en": "English", "fr": "Français", "es": "Español", "de": "Deutsch", "it": "Italiano", "pt": "Português", "nl": "Nederlands", "ru": "Русский", "pl": "Polski", "no": "Norsk"}
_NAMES = {
    "en": ("en", "eng", "english"),
    "fr": ("fr", "fre", "fra", "french", "francais"),
    "es": ("es", "spa", "spanish", "espanol"),
    "de": ("de", "ger", "deu", "german", "deutsch"),
    "it": ("it", "ita", "italian", "italiano"),
    "pt": ("pt", "por", "portuguese"),
    "nl": ("nl", "dut", "nld", "dutch"),
    "ru": ("ru", "rus", "russian"),
    "pl": ("pl", "pol", "polish"),
    "no": ("no", "nor", "norwegian"),
}
CODES = {name: code for code, names in _NAMES.items() for name in names}


def is_subtitle(path):
    return Path(path).suffix.lower() in EXTENSIONS


def language_of(path):
    """'Movie.fr.srt' -> 'fr'; the file name says it ('name.fr.srt', 'English.srt'), else the nearest folder ('Subs/French/2.srt')."""
    p = Path(path)
    for part in (p.stem, *reversed(p.parts[:-1])):
        tokens = [t for t in re.split(r"[^a-z]+", part.lower()) if t]
        for token in reversed(tokens):
            if token in CODES:
                return CODES[token]
            if part == p.stem:
                break  # in a file name only the last word can be the language: "It.2017.srt" is not Italian
    return None


def to_vtt(raw):
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("latin-1")  # never fails
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if text.startswith("WEBVTT"):
        return text + "\n"
    # srt writes 00:00:01,000 where WebVTT wants 00:00:01.000, in the timing lines only
    lines = [re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", line) if "-->" in line else line for line in text.split("\n")]
    return "WEBVTT\n\n" + "\n".join(lines) + "\n"


def found(engine, movie):
    """{language: path relative to the download directory} of the complete subtitle files of a movie, one per language."""
    torrent = engine.get(movie.infohash) if movie.status == "downloading" else None
    if torrent is not None:
        candidates = [path for path, complete in torrent.subtitle_files() if complete]
    elif movie.status == "ready" and movie.file_path and "/" in movie.file_path:
        base = library.root_of(engine, movie.file_path)
        root = base / movie.file_path.split("/")[0]
        candidates = [str(p.relative_to(base)) for p in root.rglob("*") if p.is_file() and is_subtitle(p)]
    else:
        candidates = []
    result = {}
    for path in sorted(candidates):
        lang = language_of(path)
        if lang and lang not in result:
            result[lang] = path
    return result


def available(engine, movie):
    langs = found(engine, movie)
    return [{"lang": lang, "label": LABELS[lang]} for lang in sorted(langs, key=lambda code: (code != "en", code))]


def read_vtt(engine, path):
    file = library.locate(engine, path)
    return to_vtt(file.read_bytes()[:MAX_BYTES]) if file.is_file() else None
