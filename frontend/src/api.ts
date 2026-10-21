// the quality tabs of a film's copies: the server files a release by what its name says (anything else is a 720p)
export type Tier = "4K" | "1080p" | "720p";

// one provider's copy of a film
export type Source = { id: number; provider: string; resolution: string | null; size: number; seeders: number; tier: Tier };

export type Movie = {
  id: number;
  tier: Tier;
  title: string;
  year: number | null;
  resolution: string | null;
  size: number;
  seeders: number;
  peers: number;
  provider: string;
  cover: string | null;
  rating: number | null; // TMDb, out of 10
  watched: boolean;
  favorite?: boolean; // the star
  listed?: boolean; // in my list
  resume?: { id: number; position: number; duration: number } | null; // where the member stopped: the copy they watched and the seconds
  finished?: boolean; // watched to the end
  played?: number | null; // how far the member is in the film, 0 to 1 (the "continue watching" row)
  sources?: Source[]; // every provider offering this film, best first (the film's own id is the first one's)
  // for a search: why this film is in the results (a title is the plain case, the others are explained on the thumbnail)
  match?: { kind: "title" | "alias" | "director" | "creator" | "cast" | "overview" | "other"; label: string | null } | null;
};

// a film of the downloads page: what the server has of it
export type DownloadItem = Movie & { state: "downloading" | "ready"; progress: number };
export type Shelf = "favorite" | "list";

// where the server is with the movie: nothing yet, downloading (progress 0..1), or fully on its disk
// ref: what the subtitle URL takes (a language code for the torrent's file, an id for an imported one)
export type Subtitle = { ref: string; lang: string; label: string; source: "torrent" | "upload" | "opensubtitles"; mine: boolean };
export type AudioTrack = { index: number; lang: string | null; label: string; codec: string | null; channels: number | null };
export type FoundSubtitle = { file_id: number; lang: string; release: string; downloads: number; title: string; year: number | null };
export type MovieDetails = Movie & {
  state: "idle" | "downloading" | "ready";
  progress: number;
  rate: number;
  native: boolean | null; // the browser plays the file as it is (else it is converted); null until the torrent was opened
  overview: string | null;
  runtime: number | null; // minutes
  language: string | null; // original language of the video
  genres: string[];
  directors: string[];
  producers: string[];
  cast: string[];
  comments?: number; // only on GET /api/movies/:id
  subtitles?: Subtitle[];
};

export type MovieComment = {
  id: number;
  movie_id: number;
  user_id: number;
  username: string;
  avatar_url: string | null;
  date: string;
  content: string;
  edited: boolean;
};

export type ApiClient = { id: number; name: string; client_id: string; created_at: string };
export type NewApiClient = ApiClient & { client_secret: string }; // the secret is only returned at creation

// what anyone can see of a member; `email` is only present on the own profile
export type PublicUser = {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  avatar_url: string | null;
};

export type User = PublicUser & { email: string; language: "en" | "fr"; welcomed: boolean };

export type RegisterData = Pick<User, "email" | "username" | "first_name" | "last_name"> & { password: string };
export type ProfileChanges = Partial<Pick<User, "username" | "email" | "first_name" | "last_name" | "language" | "avatar_url" | "welcomed">>;

// the UI translates by `status` (see errorText in i18n.tsx)
export class ApiError extends Error {
  constructor(public status: number) {
    super(`HTTP ${status}`);
  }
}

async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  const isJson = typeof init.body === "string";
  const res = await fetch(url, { ...init, headers: isJson ? { "Content-Type": "application/json" } : undefined });
  // a closed session on any call outside the auth routes sends the user back to the login page
  if (res.status === 401 && !url.startsWith("/api/auth/")) window.dispatchEvent(new Event("unauthorized"));
  if (!res.ok) throw new ApiError(res.status);
  return res.status === 204 ? (undefined as T) : res.json();
}

const send = <T>(method: string, url: string, body?: unknown) =>
  request<T>(url, { method, body: body === undefined ? undefined : JSON.stringify(body) });

// the TMDb catalogue: titles to look through; a film opens on the copies the providers have of it
export type CatalogKind = "movie" | "tv";
export type CatalogItem = { kind: CatalogKind; id: number; title: string; year: number | null; rating: number | null; poster: string | null; overview: string | null; genres: string[] };
export type CatalogSheet = { runtime: number | null; directors: string[]; producers: string[]; cast: string[] };
export const getCatalogGenres = (kind: CatalogKind, signal: AbortSignal) => request<{ id: number; name: string }[]>(`/api/catalog/genres?kind=${kind}`, { signal });
export const getCatalogSheet = (kind: CatalogKind, id: number, signal: AbortSignal) => request<CatalogSheet>(`/api/catalog/${kind}/${id}`, { signal });
// the film to open (every copy is a provider's source of it), null when no provider has it
export const getCatalogCopies = (id: number, signal: AbortSignal) => request<Movie | null>(`/api/catalog/movie/${id}/copies`, { signal });
// by popularity (of a genre, or all), or, with `q`, what TMDb finds for the words (best match first, no genre)
export function getCatalog(kind: CatalogKind, genre: number | undefined, q: string, page: number, signal: AbortSignal) {
  const params = new URLSearchParams({ kind, page: String(page) });
  if (genre !== undefined) params.set("genre", String(genre));
  if (q) params.set("q", q);
  return request<{ items: CatalogItem[]; page: number; total: number; has_more: boolean }>(`/api/catalog?${params}`, { signal });
}
export const getShelf = (kind: Shelf, signal: AbortSignal) => request<Movie[]>(`/api/bookmarks/${kind}`, { signal });
// the player says where the member is, so the film can show a bar in "continue watching"
export const saveProgress = (id: number, position: number, duration: number) => send<void>("PUT", `/api/movies/${id}/progress`, { position, duration });
export const getDownloads = (signal: AbortSignal) => request<DownloadItem[]>("/api/downloads", { signal });
export const setBookmark = (id: number, kind: Shelf, on: boolean) => send<void>(on ? "PUT" : "DELETE", `/api/movies/${id}/bookmarks/${kind}`);
// the films the member started, the latest first (the row "continue watching")
export const getContinue = (signal: AbortSignal) => request<Movie[]>("/api/continue", { signal });

// null when nobody is logged in (not an error, so the console stays clean)
export const me = () => request<User | null>("/api/auth/me");
export const login = (username: string, password: string) => send<User>("POST", "/api/auth/login", { username, password });
export const register = (data: RegisterData) => send<User>("POST", "/api/auth/register", data);
export const logout = () => send<void>("POST", "/api/auth/logout");
export const forgotPassword = (email: string) => send<void>("POST", "/api/auth/forgot", { email });
export const resetPassword = (token: string, password: string) => send<void>("POST", "/api/auth/reset", { token, password });

export const getMovie = (id: number, signal: AbortSignal) => request<MovieDetails>(`/api/movies/${id}`, { signal });
export const startDownload = (id: number) => send<MovieDetails>("POST", `/api/movies/${id}/download`);
// another audio track, or a restart from `start` seconds, goes through the server's converter
export const streamUrl = (id: number, audio = 0, start = 0) => `/api/movies/${id}/stream${audio || start ? `?audio=${audio}&start=${start}` : ""}`;
export const subtitleUrl = (id: number, ref: string) => `/api/movies/${id}/subtitles/${ref}`;

export const getAudio = (id: number, signal: AbortSignal) => request<AudioTrack[]>(`/api/movies/${id}/audio`, { signal });
export const searchSubtitles = (id: number, lang: string, signal: AbortSignal) =>
  request<FoundSubtitle[]>(`/api/movies/${id}/subtitles/search?lang=${lang}`, { signal });
export function importSubtitleFile(id: number, file: File, lang: string) {
  const body = new FormData();
  body.append("file", file);
  if (lang) body.append("lang", lang);
  return request<Subtitle>(`/api/movies/${id}/subtitles`, { method: "POST", body });
}
export const importFromOpenSubtitles = (id: number, f: FoundSubtitle) =>
  send<Subtitle>("POST", `/api/movies/${id}/subtitles/opensubtitles`, { file_id: f.file_id, lang: f.lang, release: f.release });
export const deleteSubtitle = (id: number, ref: string) => send<void>("DELETE", `/api/movies/${id}/subtitles/${ref}`);

export const getComments = (movieId: number, signal: AbortSignal) => request<MovieComment[]>(`/api/movies/${movieId}/comments`, { signal });
export const postComment = (movieId: number, comment: string) => send<MovieComment>("POST", `/api/movies/${movieId}/comments`, { comment });
export const editComment = (id: number, comment: string) => send<MovieComment>("PATCH", `/api/comments/${id}`, { comment });
export const deleteComment = (id: number) => send<void>("DELETE", `/api/comments/${id}`);

export const listUsers = (signal: AbortSignal) => request<{ id: number; username: string }[]>("/api/users", { signal });

export const listClients = (signal: AbortSignal) => request<ApiClient[]>("/api/clients", { signal });
export const createClient = (name: string) => send<NewApiClient>("POST", "/api/clients", { name });
export const deleteClient = (id: number) => send<void>("DELETE", `/api/clients/${id}`);

export const getUser = (id: number, signal: AbortSignal) => request<PublicUser | User>(`/api/users/${id}`, { signal });
export const updateProfile = (id: number, changes: ProfileChanges) => send<User>("PATCH", `/api/users/${id}`, changes);
export function uploadAvatar(file: File) {
  const body = new FormData();
  body.append("file", file);
  return request<User>("/api/users/me/avatar", { method: "POST", body });
}
