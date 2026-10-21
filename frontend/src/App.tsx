import { useEffect, useRef, useState, type ReactNode } from "react";
import { getGenres, logout, me, search, type Genre, type Movie, type User } from "./api";
import { Card } from "./Card";
import AuthPage from "./AuthPage";
import { errorText, useI18n } from "./i18n";
import { gradient, meta } from "./format";
import LibraryGrid, { useGenreLabel } from "./LibraryGrid";
import Members from "./Members";
import MovieModal from "./MovieModal";
import ProfilePage, { Avatar } from "./ProfilePage";
import ResetPage from "./ResetPage";
import { useApi, type State } from "./useApi";

type View = "home" | "films" | "series" | "list" | "favorites" | "downloads" | "members" | "profile";
const TABS: [Exclude<View, "profile">, string][] = [
  ["home", "nav.home"],
  ["films", "nav.films"],
  ["series", "nav.series"],
  ["list", "nav.list"],
  ["favorites", "nav.favorites"],
  ["downloads", "nav.downloads"],
  ["members", "nav.members"],
];

// typing is debounced; rows and genre filters load right away
const useMovies = (q: string, genre?: string, limit?: number) =>
  useApi<Movie[]>((signal) => search({ q, genre, limit }, signal), [], [q, genre, limit], q ? 350 : 0);

function Status({ state, children }: { state: State<Movie[]>; children: ReactNode }) {
  const { t } = useI18n();
  if (state.error) return <p className="notice" role="alert">{errorText(t, state.error)}</p>;
  if (state.loading) return <p className="notice">{t("loading")}</p>;
  if (state.data.length === 0) return <p className="notice">{t("empty")}</p>;
  return <>{children}</>;
}

function Row({ title, state, onSelect }: { title: string; state: State<Movie[]>; onSelect: (m: Movie) => void }) {
  const { t } = useI18n();
  const rail = useRef<HTMLDivElement>(null);
  const scroll = (dir: number) =>
    rail.current?.scrollBy({ left: dir * rail.current.clientWidth * 0.8, behavior: "smooth" });
  return (
    <section className="row">
      <h2>{title}</h2>
      <Status state={state}>
        <div className="rail-wrap">
          <button className="arrow left" aria-label={t("row.prev")} onClick={() => scroll(-1)}>‹</button>
          <div className="rail" ref={rail}>
            {state.data.map((m) => <Card key={m.id} movie={m} onSelect={onSelect} />)}
          </div>
          <button className="arrow right" aria-label={t("row.next")} onClick={() => scroll(1)}>›</button>
        </div>
      </Status>
    </section>
  );
}

function GenreRow({ genre, onSelect }: { genre: Genre; onSelect: (m: Movie) => void }) {
  const label = useGenreLabel();
  return <Row title={label(genre)} state={useMovies("", genre.id, 20)} onSelect={onSelect} />;
}

function Home({ genres, onSelect }: { genres: Genre[]; onSelect: (m: Movie) => void }) {
  const { t } = useI18n();
  const label = useGenreLabel();
  const popular = useMovies("", "populaires", 20);
  const hero = popular.data[0];
  const first = genres.find((g) => g.id === "populaires");
  return (
    <>
      {hero && (
        <section className="hero" style={{ backgroundImage: gradient(hero.id) }}>
          <div className="hero-in">
            <span className="tag">{t("hero.tag", { provider: hero.provider })}</span>
            <h1>{hero.title}</h1>
            <div className="meta">{meta(hero)}</div>
            <button className="btn primary" onClick={() => onSelect(hero)}>ⓘ {t("hero.details")}</button>
          </div>
        </section>
      )}
      <main className={hero ? "after-hero" : ""}>
        <Row title={first ? label(first) : t("genre.populaires")} state={popular} onSelect={onSelect} />
        {genres.filter((g) => g.section === "films" && g.id !== "populaires").map((g) => (
          <GenreRow key={g.id} genre={g} onSelect={onSelect} />
        ))}
      </main>
    </>
  );
}

function Films({ genres, onSelect }: { genres: Genre[]; onSelect: (m: Movie) => void }) {
  const { t } = useI18n();
  const label = useGenreLabel();
  const [genre, setGenre] = useState("populaires");
  const films = genres.filter((g) => g.section === "films");
  const current = films.find((g) => g.id === genre);
  return (
    <main>
      <div className="chips" role="group" aria-label={t("genres.aria")}>
        {films.map((g) => (
          <button key={g.id} className={`chip ${g.id === genre ? "on" : ""}`} aria-pressed={g.id === genre} onClick={() => setGenre(g.id)}>
            {label(g)}
          </button>
        ))}
      </div>
      <LibraryGrid title={current ? label(current) : t("nav.films")} genre={genre} onSelect={onSelect} />
    </main>
  );
}

function Series({ genres, onSelect }: { genres: Genre[]; onSelect: (m: Movie) => void }) {
  const label = useGenreLabel();
  const series = genres.find((g) => g.id === "series");
  return <main><LibraryGrid title={series ? label(series) : ""} genre="series" onSelect={onSelect} /></main>;
}

function Results({ q, genres, onSelect }: { q: string; genres: Genre[]; onSelect: (m: Movie) => void }) {
  const { t } = useI18n();
  return <main><LibraryGrid title={t("results.for", { q })} q={q} genres={genres} onSelect={onSelect} /></main>;
}

function Soon({ title }: { title: string }) {
  const { t } = useI18n();
  return (
    <main>
      <section className="row">
        <h2>{title}</h2>
        <p className="notice">{t("soon")}</p>
      </section>
    </main>
  );
}

function Library({ user, onUserChange, onLogout }: {
  user: User;
  onUserChange: (u: User) => void;
  onLogout: () => void;
}) {
  const { t } = useI18n();
  const [q, setQ] = useState("");
  const [view, setView] = useState<View>("home");
  const [profileId, setProfileId] = useState(user.id);
  const [selected, setSelected] = useState<Movie | null>(null);
  const genres = useApi<Genre[]>(getGenres, [], []);
  const searching = q.trim() !== "";

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setSelected(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const openProfile = (id: number) => {
    setSelected(null);
    setQ("");
    setProfileId(id);
    setView("profile");
  };

  const page = () => {
    if (searching) return <Results q={q.trim()} genres={genres.data} onSelect={setSelected} />;
    if (view === "profile") return <ProfilePage id={profileId} me={user} onUpdate={onUserChange} />;
    if (view === "members") return <Members onOpen={openProfile} />;
    if (genres.error) return <main><p className="notice" role="alert">{errorText(t, genres.error)}</p></main>;
    switch (view) {
      case "home": return <Home genres={genres.data} onSelect={setSelected} />;
      case "films": return <Films genres={genres.data} onSelect={setSelected} />;
      case "series": return <Series genres={genres.data} onSelect={setSelected} />;
      default: return <Soon title={t(TABS.find(([v]) => v === view)![1])} />;
    }
  };

  return (
    <>
      <header className="nav">
        <div className="logo">HYPERTUBE</div>
        <nav aria-label={t("nav.label")}>
          {TABS.map(([v, key]) => {
            const current = view === v && !searching;
            return (
              <button key={v} className={current ? "on" : ""} aria-current={current ? "page" : undefined} onClick={() => { setQ(""); setView(v); }}>
                {t(key)}
              </button>
            );
          })}
        </nav>
        <div className="nav-r">
          <label className="search">
            <input
              type="search"
              placeholder={t("search.placeholder")}
              aria-label={t("search.aria")}
              value={q}
              maxLength={100}
              onChange={(e) => setQ(e.target.value)}
            />
          </label>
          <button className="who" title={t("profile.open")} onClick={() => openProfile(user.id)}>
            <Avatar user={user} size={30} />
            <span>{user.username}</span>
          </button>
          <button className="btn-link" onClick={onLogout}>{t("logout")}</button>
        </div>
      </header>

      {page()}

      <footer>
        <span>© Hypertube</span>
        <span>{t("footer.legal")} · {t("footer.credit")}</span>
      </footer>

      {selected && <MovieModal key={selected.id} movie={selected} me={user} onClose={() => setSelected(null)} onProfile={openProfile} />}
    </>
  );
}

// the password-reset email links to /reset-password?token=…
const resetTokenFromUrl = () =>
  window.location.pathname === "/reset-password" ? new URLSearchParams(window.location.search).get("token") ?? "" : null;

// the OAuth callback sends the visitor back to /?oauth_error=<code>; only known codes are shown
const OAUTH_ERRORS = ["denied", "failed", "unavailable", "unverified"];
const oauthErrorFromUrl = () => {
  const code = new URLSearchParams(window.location.search).get("oauth_error");
  return code === null ? null : OAUTH_ERRORS.includes(code) ? code : "failed";
};

export default function App() {
  const { t, setLang } = useI18n();
  const [user, setUser] = useState<User | null | undefined>(undefined); // undefined: checking the session
  const [resetToken, setResetToken] = useState(resetTokenFromUrl);
  const [notice, setNotice] = useState<string>();
  const [oauthError] = useState(oauthErrorFromUrl);

  useEffect(() => {
    if (oauthError) window.history.replaceState(null, "", "/"); // a reload must not show it again
    me().then(setUser).catch(() => setUser(null));
    const onUnauthorized = () => setUser(null);
    window.addEventListener("unauthorized", onUnauthorized);
    return () => window.removeEventListener("unauthorized", onUnauthorized);
  }, []);

  // a member's saved language wins over the browser's last choice
  useEffect(() => {
    if (user) setLang(user.language);
  }, [user?.language]);

  if (resetToken !== null) {
    return (
      <ResetPage
        token={resetToken}
        onDone={() => {
          window.history.replaceState(null, "", "/");
          setNotice(resetToken ? t("reset.done") : undefined);
          setResetToken(null);
        }}
      />
    );
  }
  if (user === undefined) return null;
  if (user === null) return <AuthPage onAuth={setUser} notice={notice} error={oauthError ? t(`oauth.${oauthError}`) : undefined} />;
  return (
    <Library
      user={user}
      onUserChange={setUser}
      onLogout={() => logout().finally(() => setUser(null))}
    />
  );
}
