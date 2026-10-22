# Hypertube

Browse TMDb's catalogue of films and series and stream them from the torrents that Jackett's indexers have. React + TypeScript front, Python FastAPI back, PostgreSQL database.

## Run the project

```bash
make up        # builds and starts everything (Docker required)
```

On the first run, `make up` creates the `.env` file with random secrets (never committed).

| Service | URL |
|---|---|
| Site | http://localhost:3000 |
| Jackett | http://localhost:9117 |
| API | http://localhost:8000 |

Open the site, create an account, then browse the catalogue (it is only available to logged-in users; it needs `TMDB_API_KEY`, see below). Jackett starts with no indexer: add some in its interface (http://localhost:9117, "Add indexer"). `JACKETT_INDEXER` in `.env` is `all` by default (every indexer added in Jackett), or the id of a single one. To search more indexers next to the main one, list their ids in `JACKETT_EXTRA_INDEXERS` (see `.env.example`); one that fails never hides the others, and each result shows the indexer it came from. Every indexer you add must be a legal source; it may give `.torrent` files or magnet links. The back reads Jackett's API key by itself.

**Language:** the interface is in English by default. The round flag in the header switches between English and Français; the choice is saved. Summaries, titles and genres of films come from TMDb in that language (kept in memory after the first request); TMDb's French list of series genres keeps seven English names, which the back translates.

| Command | Effect |
|---|---|
| `make up` | builds and starts |
| `make logs` | follows the logs |
| `make test` | runs the back tests in Docker |
| `make down` | stops |
| `make re` | stops then restarts |
| `make fclean` | stops and deletes images, database and `data/` |

If Docker answers `permission denied`: `sudo usermod -aG docker $USER`, then log in again.

## One user, no login

This branch is for a program installed on one machine: nobody signs up or logs in, there are no passwords, emails, profiles or pictures. The back creates the only member the first time it is asked (named after the system's login name) and every route answers for them: favorites, my list, watched films, positions and comments are theirs. Because nothing protects the site, `docker-compose.yml` publishes it on `127.0.0.1` only (do not open the ports to a network). Still checked: the comment text (1 to 1000 characters), subtitle files (2 MB, `.srt`/`.vtt`), positions and every query parameter; SQL goes through SQLAlchemy.

## Sources and movie details

- **TMDb lists, Jackett finds:** TMDb gives the films and series (the catalogue); Jackett, with the indexers you added, gives the torrents of a film when a member opens it. Nothing is listed from Jackett on its own: the site only knows the films a member opened (they are kept in the database, with their providers).
- Sources that were checked and rejected: Legit Torrents (named in the subject) closed in 2023; Public Domain Torrents' tracker has no seeder, so nothing can stream; PeerTube's licence field is declared by the uploader and not verified (copyrighted films labelled "public domain" show up), so it is not a reliable legal source.
- **Details** (summary, casting, length, rating, poster) come from TMDb: put a free key in `.env` as `TMDB_API_KEY` (https://www.themoviedb.org/settings/api). Without it the thumbnails have no rating and the sheets show only what the torrent provides.
- **Search:** the box searches TMDb for films and series (best match first, by title; TMDb does not filter a search by genre). Opening a result asks the providers for the film, like anywhere in the catalogue. It needs `TMDB_API_KEY`.
- **Home:** **Continue watching** (the films you started, latest first, shown once you have watched one; a red bar at the bottom of the poster shows how far you are: the player reports your position every 10 s and when it closes, and a film watched to 95 % leaves the row), then the catalogue (films or series). **Resume:** the sheet of a film you stopped shows "Resume 12:34" and opens the copy you were watching at that minute (a file the browser plays as it is jumps there; a converted stream starts there); a film watched to 95 % starts again from the beginning. Limit: the position is the one saved every 10 s, so you can lose a few seconds.
- **Films and Series tabs:** every film or series TMDb lists, to look through (by genre, most popular first, 20 more as you scroll; TMDb stops at 500 pages per list; Series has TMDb's TV genres). It needs `TMDB_API_KEY`. A title opens an information sheet (summary, length, rating, director, cast). For a film, opening the sheet also asks the providers (the same Jackett indexers as the search) for it, by TMDb's English and original names (`GET /api/catalog/movie/{id}/copies`): only results with the same title and the same year give or take one are kept, cinema recordings (CAM, TS, telesync, screener…) are dropped, the same release from two providers counts once, each copy is scored (seeders, a swarm with leechers, a size between 1.5 and 5 GB, x265) and the three best of each resolution (4K, 1080p, then the rest) are offered as soon as a provider has the film: the sheet is replaced by the film's own window, with **one tab per quality** (4K, 1080p, 720p), each listing its copies with a Play and a download button. A film no provider has (the usual case with legal sources only) keeps a note instead; series are information only. What the page lists is kept in the `catalog` table (kind, TMDb id, title, year, summary, poster, rating, genres).
- **My list, Favorites, Downloads:** the round **star** and **+** on every thumbnail (and in the film's window, kept in step) add it to the matching tab; pressing again removes it. Catalogue titles are bookmarked by TMDb id (`/api/catalog`), even before any provider has them. Both are per member, and the same film from several providers is one entry. **Downloads** lists what the server is downloading (with its progress, refreshed every 3 s) or has downloaded (a film played or downloaded with ⬇); it is the same for every member, and a film leaves it when the server deletes it after 30 days unwatched.
- **Download button:** it fills as the server downloads, shows a tick when done, and turns into a cross to cancel or erase the copy (after a confirmation; `DELETE /api/movies/:id/download` and `/file`). Each provider's button shows its own state (`GET /api/movies/states`).
- **Typo-tolerant search:** a catalogue search TMDb finds nothing for (e.g. "spidermann") is retried with the closest title the catalogue knows.
- **Letterboxd:** every film window and catalogue sheet links to the film's Letterboxd page.
- **Language menu:** round flags next to the account switch the site, genres, titles and summaries between English and Français.
- **Thumbnails** (Continue watching, My list, Favorites, Downloads): a check on a thumbnail means you already watched it. The same film offered by several providers (same title, same year when both give one) is **one thumbnail**: its sheet lists each provider with its seeders, size and resolution, and each has its own Play and download buttons. The thumbnail stands for the downloaded copy if there is one, else the best seeded; it counts as watched if any copy was.
- **Audio & subtitles:** in the player, the **Audio & subtitles** button opens a panel with the audio tracks on the left and the subtitles on the right (like Netflix or Stremio).
  - *Subtitles:* the `.srt` / `.vtt` files that come with the torrent are downloaded with the video, converted to WebVTT and listed (they appear once the movie has started loading). The member's language is selected by default when the film was made in another language. **Import a file…** adds a subtitle file of your own (2 MB max, language read from the file name or chosen in the list, 10 per movie, visible to every member, removable by whoever imported it). **Search OpenSubtitles…** finds and adds subtitles from OpenSubtitles: put `OPENSUBTITLES_API_KEY` (and optionally `OPENSUBTITLES_USERNAME` / `OPENSUBTITLES_PASSWORD`) in `.env`. Subtitles from OpenSubtitles are only fetched **when a member asks** (a fallback for a film that brings none), never by themselves; OpenSubtitles' official help page gives 5 downloads per 24 h per IP without an account and 10 per day with a regular account (searching is unlimited). That integration follows OpenSubtitles' REST API documentation and has only been tested against a fake server.
  - *Subtitle style:* a second panel sets the look of the subtitles (size, font, colour, shadow, background); it is kept in the browser.
  - *Audio:* the tracks of the file are listed with their language and codec. The first one plays as it is; choosing another goes through the server's converter, which restarts the film at the current position and cannot be seeked ahead (the time bar then counts from the switch). Most films have a single track.
- **Comments** on every movie sheet; only the author edits or deletes a comment.

## Video playback

- Click a film then **▶ Play**: the server downloads the torrent in the background with `libtorrent` and the film starts as soon as the first pieces are there. A provider with only magnet links works too: the magnet link holds just the torrent's hash, so the server first asks the swarm (trackers, DHT) for the list of files, for up to 45 s (then the answer is 504 "Nobody is sharing this torrent right now"); only the video and its subtitles are downloaded, as with a `.torrent` file. The player can seek (HTTP `Range` requests, the requested pieces get priority).
- The player takes the whole window (like Netflix) and draws its **own controls** (the browser's built-in bar cannot be extended): play/pause, seek bar, ±10 s, volume, time, full screen and the **Audio & subtitles** button. They fade after 3 s of inactivity (not while paused). Keys: `Space`/`K` play-pause, `←` `→` ±10 s, `↑` `↓` volume, `M` mute, `F` full screen, `Esc` closes the panel, then goes back to the film sheet (**←** does too).
- The **Audio & subtitles** panel opens on hover and each click applies at once; `Esc` closes it. The seek bar and ±10 s are off while a converted stream plays (another audio track, or a file the browser cannot play as it is).
- **How the stream is made** (the subject forbids libraries that stream a torrent, such as `webtorrent`, `pulsar` or `peerflix`): `libtorrent` only does BitTorrent (peers, pieces, DHT). The streaming is our own code: `app/engine.py` picks the video file and gives the pieces the player asks for priority, `app/stream.py` answers HTTP `Range` requests from the bytes already on disk and waits for the pieces that are not there yet, and `app/transcode.py` runs `ffmpeg` for the formats the browser cannot play.
- Only the torrent's video file is downloaded (an mp4/webm is preferred, since it plays without conversion).
- Formats the browser cannot play (mkv, avi…) are converted on the fly to MP4 by `ffmpeg` (included in the Docker image). Limit: a converted stream cannot seek past what has already been produced.
- **Streaming and downloading are two things.** Playing a film downloads it into a cache (`data/downloads`) so that it can start early and seek; a film that was only streamed is erased from the cache after 3 days unwatched (`CACHE_DAYS`). The **download button** of a copy is for the films you want to keep: it fills while the torrent downloads, then the file moves to your library folder, `~/Desktop/hypertube` by default (`LIBRARY_DIR` in `.env`; with Docker the folder is mounted into the back), and a tick shows. Films in the library are never cleaned up: the cross on the tick deletes the file (after a confirmation), the cross while downloading cancels and deletes what arrived. The **Downloads** tab lists only the films you chose to download. The **gear** in the header sets how long the cache keeps a streamed film (1, 3, 7, 30 days or never; saved in the database) and shows the library folder. A download you asked for that was running when the app was closed starts again by itself: the back looks for them every minute.
- BitTorrent port 6881 (TCP and UDP) must be reachable from the Internet to find and serve peers.

## Legal sources only

The subject requires free or legally distributable sources. Only enable indexers of that kind in Jackett.

## Development without Docker

```bash
# back (Python 3.12); without DATABASE_URL, a local SQLite database is used
cd backend && pip install -r requirements.txt
pytest
JACKETT_URL=http://localhost:9117 JACKETT_API_KEY=<key> uvicorn app.main:app --reload

# front (proxies /api to localhost:8000)
cd frontend && npm install && npm run dev
```
