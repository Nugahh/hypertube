# Hypertube

Search and stream free-to-distribute films from two sources: the Internet Archive (through Jackett) and the Blender Foundation's open movies (Creative Commons). React + TypeScript front, Python FastAPI back, PostgreSQL database.

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

Open the site, create an account, then browse the library (it is only available to logged-in users). Jackett configures itself (Internet Archive indexer enabled, API key read by the back).

**Forgotten password:** the reset link arrives in Mailpit (http://localhost:8025). For a real SMTP server, fill in the `SMTP_*` and `APP_URL` variables in `.env` (see `.env.example`).

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

- Passwords are hashed with Argon2id and never stored or logged in clear text.
- Session through an `httpOnly` + `SameSite=Lax` cookie (signed with `SECRET_KEY`). Set `COOKIE_SECURE=true` once the site is served over HTTPS.
- Log in with username + password; an unknown user and a wrong password get the same answer.
- Forgotten password: a signed link valid for 1 hour and single use (it stops working as soon as the password changes). The answer is the same whether the account exists or not.
- Profile: everyone edits their own email, name, language and picture; other members' emails are never returned. Pictures are decoded then re-encoded as 256×256 JPEG (2 MB max), never served as uploaded.
- **Default pictures:** a member without a picture gets one of the images listed in `frontend/public/avatars/index.json` (the same one every time), and can pick another in the profile or upload their own. They are the 19 Dofus class symbols (from DofusDB, cropped to a square), © Ankama, used as fan content in a school project and credited in the footer: check Ankama's terms before publishing the project publicly. To add images, copy them into that folder and add a line to `index.json` (see `frontend/public/avatars/README.txt`; lowercase file names with hyphens).
- Parameterized SQL queries (SQLAlchemy), forms validated on both the front and the back.
- No migrations for now: the tables are created at startup.

## Log in with 42 and Google

- Create the applications at https://profile.intra.42.fr/oauth/applications/new (scope `public`) and https://console.cloud.google.com (OAuth client ID, "Web application"), then fill in `FORTYTWO_CLIENT_ID/SECRET` and `GOOGLE_CLIENT_ID/SECRET` in `.env`.
- Redirect URIs to register: `APP_URL` + `/api/auth/42/callback` and `APP_URL` + `/api/auth/google/callback` (`http://localhost:3000/...` with `make up`). With `npm run dev`, set `APP_URL=http://localhost:5173` and register that address too.
- An account is identified by the provider's own id. A **verified** email that already has an account joins that account; an unverified email is refused. A random `state` token (`httpOnly` cookie) protects the return trip against CSRF.
- OAuth accounts have no password: they always sign in through the provider.

## Sources and movie details

- **Internet Archive** (`collection:feature_films` and others) through Jackett, searched live, and **Blender Open Movies**: the Blender Foundation's nine open movies, all Creative Commons (Big Buck Bunny, Sintel, Tears of Steel, Cosmos Laundromat, Elephants Dream, Spring, Caminandes 1 and 3, Glass Half), with their own row "Open movies". A search queries both and merges the results, sorted by name; a source that fails does not hide the other. The first four are seeded with a web seed by webtorrent.io and come with subtitles; the others use the Foundation's uploads on the Internet Archive.
- Sources that were checked and rejected: Legit Torrents (named in the subject) closed in 2023; Public Domain Torrents' tracker has no seeder, so nothing can stream; PeerTube's licence field is declared by the uploader and not verified (copyrighted films labelled "public domain" show up), so it is not a reliable legal source.
- **Details** (summary, casting, length, rating, poster) come from TMDb: put a free key in `.env` as `TMDB_API_KEY` (https://www.themoviedb.org/settings/api). Without it the thumbnails have no rating and the sheets show only what the torrent provides.
- **Search:** the box looks everywhere and ranks by how a film matched (best first; by name inside each level): the exact title, the title with all your words, the title being typed, the title with a **typo** ("chapliin", "drakula"), then another name of the film (a title typed in another language), its **director** or **actor**, a **creator** credited on archive.org, the **summary**, and finally what archive.org found some other way. Accents and capitals do not matter, words can come in any order. A thumbnail that is not a title match says why ("Director: Charles Chaplin"). Typos are forgiven by edit distance (one slip from 4 letters, two from 8; short words must be exact), not by a regex, and archive.org is asked with its fuzzy operator (`word~1`). Directors, actors and other-language titles need `TMDB_API_KEY`; without it the search still covers titles, archive.org's own credits and descriptions, and what TMDb already told us about films seen before. The default sort is **Relevance**; **Name** gives the plain alphabetical order. Limits: archive.org answers at most about 100 results per query, and a search that goes through several queries can take a few seconds the first time (it is remembered for 5 minutes).
- **Library:** the grid loads the next page while you scroll (no "next page" link), sortable by popularity, name, year or rating, filterable by genre, year range and minimum rating. A check on a thumbnail means you already watched it.
- **Audio & subtitles:** in the player, the **Audio & subtitles** button opens a panel with the audio tracks on the left and the subtitles on the right (like Netflix or Stremio).
  - *Subtitles:* the `.srt` / `.vtt` files that come with the torrent are downloaded with the video, converted to WebVTT and listed (they appear once the movie has started loading). The member's language is selected by default when the film was made in another language. **Import a file…** adds a subtitle file of your own (2 MB max, language read from the file name or chosen in the list, 10 per movie, visible to every member, removable by whoever imported it). **Search OpenSubtitles…** finds and adds subtitles from OpenSubtitles: put `OPENSUBTITLES_API_KEY` (and optionally `OPENSUBTITLES_USERNAME` / `OPENSUBTITLES_PASSWORD`) in `.env`. Subtitles from OpenSubtitles are only fetched **when a member asks** (a fallback for a film that brings none), never by themselves; OpenSubtitles' official help page gives 5 downloads per 24 h per IP without an account and 10 per day with a regular account (searching is unlimited). That integration follows OpenSubtitles' REST API documentation and has only been tested against a fake server.
  - *Audio:* the tracks of the file are listed with their language and codec. The first one plays as it is; choosing another goes through the server's converter, which restarts the film at the current position and cannot be seeked ahead (the time bar then counts from the switch). Most films have a single track.
- **Comments** on every movie sheet; only the author edits or deletes a comment.
- **Members** tab and clickable authors open any member's profile (the email stays private).

## REST API

Base URL `http://localhost:8000/api` (also `http://localhost:3000/api` through the site). JSON, standard status codes, `Location` header on creation.

1. In your profile, **API access** → create a client: you get a client id and a secret (shown once, max 5 per member, deleting a client revokes its tokens).
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

- Click a film then **▶ Play**: the server downloads the torrent in the background with `libtorrent` and the film starts as soon as the first pieces are there. The player can seek (HTTP `Range` requests, the requested pieces get priority).
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
