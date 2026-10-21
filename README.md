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
| Mailpit (emails sent by the app) | http://localhost:8025 |

Open the site, create an account, then browse the catalogue (it is only available to logged-in users; it needs `TMDB_API_KEY`, see below). Jackett starts with no indexer: add some in its interface (http://localhost:9117, "Add indexer"). `JACKETT_INDEXER` in `.env` is `all` by default (every indexer added in Jackett), or the id of a single one. To search more indexers next to the main one, list their ids in `JACKETT_EXTRA_INDEXERS` (see `.env.example`); one that fails never hides the others, and each result shows the indexer it came from. Every indexer you add must be a legal source; it may give `.torrent` files or magnet links. The back reads Jackett's API key by itself.

**Forgotten password:** click "Forgot password?" on the login page and type the account's email. The mail does not go to a real mailbox: it is caught by Mailpit, open http://localhost:8025 to read it and click the link (valid 1 hour, single use). For a real SMTP server, fill in the `SMTP_*` and `APP_URL` variables in `.env` (see `.env.example`).

**Account menu:** the header shows only your profile picture; hovering or clicking it opens a menu with **Account** (a window over the page, not a page of its own: username, picture, email, language, API access) and **Sign out** (one click, from any page).

**Language:** the interface is in English by default. Each member picks a language (English / Français) in their profile, visitors on the login page.

| Command | Effect |
|---|---|
| `make up` | builds and starts |
| `make logs` | follows the logs |
| `make test` | runs the back tests in Docker |
| `make down` | stops |
| `make re` | stops then restarts |
| `make fclean` | stops and deletes images, database and `data/` |

If Docker answers `permission denied`: `sudo usermod -aG docker $USER`, then log in again.

## Accounts and security

- Passwords are hashed with Argon2id and never stored or logged in clear text. A new password (sign-up, reset, profile) needs 8 to 128 characters with a **capital letter, a digit and a special character** (not a letter, digit or space); the sign-up form shows the rule, the back enforces it. Accounts made earlier with a weaker password can still log in.
- Session through an `httpOnly` + `SameSite=Lax` cookie (signed with `SECRET_KEY`). Set `COOKIE_SECURE=true` once the site is served over HTTPS.
- Log in with username + password; an unknown user and a wrong password get the same answer.
- Forgotten password: a signed link valid for 1 hour and single use (it stops working as soon as the password changes). The answer is the same whether the account exists or not.
- **First login:** a new account (sign-up, or first 42 / Google login) lands on a page of its own to pick its picture and type its username (the 42 / Google name is only a suggestion). It is shown once per account; accounts that existed before this page was added see it once too.
- Profile (the **Account** window): everyone edits their own username, email, name, language and picture; other members' emails are never returned. Pictures are decoded then re-encoded as 256×256 JPEG (2 MB max), never served as uploaded.
- **Default pictures:** a member without a picture gets one of the images listed in `frontend/public/avatars/index.json` (the same one every time), and can pick another in the profile or upload their own. They are the 19 Dofus class symbols (from DofusDB, cropped to a square), © Ankama, used as fan content in a school project and credited in the footer: check Ankama's terms before publishing the project publicly. To add images, copy them into that folder and add a line to `index.json` (see `frontend/public/avatars/README.txt`; lowercase file names with hyphens).
- Parameterized SQL queries (SQLAlchemy), forms validated on both the front and the back.
- No migrations for now: the tables are created at startup.

## Log in with 42 and Google

- Create the applications at https://profile.intra.42.fr/oauth/applications/new (scope `public`) and https://console.cloud.google.com (OAuth client ID, "Web application"), then fill in `FORTYTWO_CLIENT_ID/SECRET` and `GOOGLE_CLIENT_ID/SECRET` in `.env`.
- Redirect URIs to register: `APP_URL` + `/api/auth/42/callback` and `APP_URL` + `/api/auth/google/callback` (`http://localhost:3000/...` with `make up`). With `npm run dev`, set `APP_URL=http://localhost:5173` and register that address too.
- An account is identified by the provider's own id. A **verified** email that already has an account joins that account; an unverified email is refused. A random `state` token (`httpOnly` cookie) protects the return trip against CSRF.
- OAuth accounts have no password: they always sign in through the provider.

## Sources and movie details

- **TMDb lists, Jackett finds:** TMDb gives the films and series (the catalogue); Jackett, with the indexers you added, gives the torrents of a film when a member opens it. Nothing is listed from Jackett on its own: the site only knows the films a member opened (they are kept in the database, with their providers).
- Sources that were checked and rejected: Legit Torrents (named in the subject) closed in 2023; Public Domain Torrents' tracker has no seeder, so nothing can stream; PeerTube's licence field is declared by the uploader and not verified (copyrighted films labelled "public domain" show up), so it is not a reliable legal source.
- **Details** (summary, casting, length, rating, poster) come from TMDb: put a free key in `.env` as `TMDB_API_KEY` (https://www.themoviedb.org/settings/api). Without it the thumbnails have no rating and the sheets show only what the torrent provides.
- **Search:** the box searches TMDb for films and series (best match first, by title; TMDb does not filter a search by genre). Opening a result asks the providers for the film, like anywhere in the catalogue. It needs `TMDB_API_KEY`.
- **Home:** **Continue watching** (the films you started, latest first, shown once you have watched one; a red bar at the bottom of the poster shows how far you are: the player reports your position every 10 s and when it closes, and a film watched to 95 % leaves the row), then the catalogue (films or series). **Resume:** the sheet of a film you stopped shows "Resume 12:34" and opens the copy you were watching at that minute (a file the browser plays as it is jumps there; a converted stream starts there); a film watched to 95 % starts again from the beginning. Limit: the position is the one saved every 10 s, so you can lose a few seconds.
- **Films and Series tabs:** every film or series TMDb lists, to look through (by genre, most popular first, 20 more as you scroll; TMDb stops at 500 pages per list; Series has TMDb's TV genres). It needs `TMDB_API_KEY`. A title opens an information sheet (summary, length, rating, director, cast). For a film, opening the sheet also asks the providers (the same Jackett indexers as the search) for it, by TMDb's English and original names (`GET /api/catalog/movie/{id}/copies`): only results with the same title and the same year give or take one are kept, cinema recordings (CAM, TS, telesync, screener…) are dropped, the same release from two providers counts once, each copy is scored (seeders, a swarm with leechers, a size between 1.5 and 5 GB, x265) and the three best of each resolution (4K, 1080p, then the rest) are offered as soon as a provider has the film: the sheet is replaced by the film's own window, with **one tab per quality** (4K, 1080p, 720p), each listing its copies with a Play and a download button. A film no provider has (the usual case with legal sources only) keeps a note instead; series are information only. What the page lists is kept in the `catalog` table (kind, TMDb id, title, year, summary, poster, rating, genres).
- **My list, Favorites, Downloads:** in a film's sheet, **+ My list** and **☆ Favorite** (the star) add it to the matching tab; pressing again removes it. Both are per member, and the same film from several providers is one entry. **Downloads** lists what the server is downloading (with its progress, refreshed every 3 s) or has downloaded (a film played or downloaded with ⬇); it is the same for every member, and a film leaves it when the server deletes it after 30 days unwatched.
- **Thumbnails** (Continue watching, My list, Favorites, Downloads): a check on a thumbnail means you already watched it. The same film offered by several providers (same title, same year when both give one) is **one thumbnail**: its sheet lists each provider with its seeders, size and resolution, and each has its own Play and download buttons. The thumbnail stands for the downloaded copy if there is one, else the best seeded; it counts as watched if any copy was.
- **Audio & subtitles:** in the player, the **Audio & subtitles** button opens a panel with the audio tracks on the left and the subtitles on the right (like Netflix or Stremio).
  - *Subtitles:* the `.srt` / `.vtt` files that come with the torrent are downloaded with the video, converted to WebVTT and listed (they appear once the movie has started loading). The member's language is selected by default when the film was made in another language. **Import a file…** adds a subtitle file of your own (2 MB max, language read from the file name or chosen in the list, 10 per movie, visible to every member, removable by whoever imported it). **Search OpenSubtitles…** finds and adds subtitles from OpenSubtitles: put `OPENSUBTITLES_API_KEY` (and optionally `OPENSUBTITLES_USERNAME` / `OPENSUBTITLES_PASSWORD`) in `.env`. Subtitles from OpenSubtitles are only fetched **when a member asks** (a fallback for a film that brings none), never by themselves; OpenSubtitles' official help page gives 5 downloads per 24 h per IP without an account and 10 per day with a regular account (searching is unlimited). That integration follows OpenSubtitles' REST API documentation and has only been tested against a fake server.
  - *Audio:* the tracks of the file are listed with their language and codec. The first one plays as it is; choosing another goes through the server's converter, which restarts the film at the current position and cannot be seeked ahead (the time bar then counts from the switch). Most films have a single track.
- **Comments** on every movie sheet; only the author edits or deletes a comment.
- **Members** tab and clickable authors open any member's profile (the email stays private).

## REST API

Base URL `http://localhost:8000/api` (also `http://localhost:3000/api` through the site). JSON, standard status codes, `Location` header on creation.

1. In the **Account** window (profile picture menu), **API access** → create a client: you get a client id and a secret (shown once, max 5 per member, deleting a client revokes its tokens).
2. `POST /api/oauth/token` with `grant_type=client_credentials&client_id=…&client_secret=…` (form, or HTTP Basic) returns `{"access_token", "token_type": "Bearer", "expires_in": 3600}`.
3. Send `Authorization: Bearer <access_token>` on the other calls.

| Route | Auth | Answer |
|---|---|---|
| `POST /api/oauth/token` | client + secret | token (401 `invalid_client`, 400 otherwise) |
| `GET /api/movies` | none | the front page: top movies with `id`, `name` |
| `GET /api/movies/:id` | token | name, id, rating, year, length, summary, cast, subtitles, comments count… |
| `GET /api/users` | token | `id`, `username` of every member |
| `GET /api/users/:id` | token | username, picture URL (+ email only for your own profile) |
| `PATCH /api/users/:id` | token | username, email, password, picture URL, names, language; **403** for someone else's profile |
| `GET /api/comments` | token | latest comments (author, date, content, id) |
| `GET /api/comments/:id` | token | one comment |
| `POST /api/comments` or `POST /api/movies/:id/comments` | token | creates a comment (201) |
| `PATCH /api/comments/:id`, `DELETE /api/comments/:id` | token | author only (403 otherwise) |
| `GET /api/movies/:id/comments` | token | comments of a movie |

Anything else answers 404 (unknown route) or 405 (wrong method); no token answers 401.

## Video playback

- Click a film then **▶ Play**: the server downloads the torrent in the background with `libtorrent` and the film starts as soon as the first pieces are there. A provider with only magnet links works too: the magnet link holds just the torrent's hash, so the server first asks the swarm (trackers, DHT) for the list of files, for up to 45 s (then the answer is 504 "Nobody is sharing this torrent right now"); only the video and its subtitles are downloaded, as with a `.torrent` file. The player can seek (HTTP `Range` requests, the requested pieces get priority).
- The player takes the whole window (like Netflix) and draws its **own controls** (the browser's built-in bar cannot be extended): play/pause, seek bar, ±10 s, volume, time, full screen and the **Audio & subtitles** button. They fade after 3 s of inactivity (not while paused). Keys: `Space`/`K` play-pause, `←` `→` ±10 s, `↑` `↓` volume, `M` mute, `F` full screen, `Esc` closes the panel, then goes back to the film sheet (**←** does too).
- In the **Audio & subtitles** panel, choices are only kept with **Apply**; **Cancel** (or `Esc`) throws them away. The seek bar and ±10 s are off while a converted stream plays (another audio track, or a file the browser cannot play as it is).
- Only the torrent's video file is downloaded (an mp4/webm is preferred, since it plays without conversion).
- Formats the browser cannot play (mkv, avi…) are converted on the fly to MP4 by `ffmpeg` (included in the Docker image). Limit: a converted stream cannot seek past what has already been produced.
- **⬇** downloads the film to the server without playing it: it is then played from disk, without downloading again.
- A film not watched for 30 days is deleted from the disk automatically.
- BitTorrent port 6881 (TCP and UDP) must be reachable from the Internet to find and serve peers.

## Legal sources only

The subject requires free or legally distributable sources. Only enable indexers of that kind in Jackett.

## Development without Docker

```bash
# back (Python 3.12); without DATABASE_URL, a local SQLite database is used
cd backend && pip install -r requirements.txt
pytest
SECRET_KEY=dev JACKETT_URL=http://localhost:9117 JACKETT_API_KEY=<key> uvicorn app.main:app --reload

# front (proxies /api to localhost:8000)
cd frontend && npm install && npm run dev
```
