import { useEffect, useRef, useState, type ReactNode } from "react";
import { getContinue, getDownloads, getShelf, logout, me, type Movie, type User } from "./api";
import AccountMenu from "./AccountMenu";
import { Card } from "./Card";
import Catalog from "./Catalog";
import AuthPage from "./AuthPage";
import { errorText, useI18n } from "./i18n";
import Members from "./Members";
import MovieModal from "./MovieModal";
import ProfileModal from "./ProfileModal";
import { Avatar } from "./ProfilePage";
import ResetPage from "./ResetPage";
import Shelf from "./Shelf";
import Welcome from "./Welcome";
import { useApi, type State } from "./useApi";

type View = "home" | "films" | "series" | "list" | "favorites" | "downloads" | "members";
const TABS: [View, string][] = [
  ["home", "nav.home"],
  ["films", "nav.films"],
  ["series", "nav.series"],
  ["list", "nav.list"],
  ["favorites", "nav.favorites"],
  ["downloads", "nav.downloads"],
  ["members", "nav.members"],
];

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

// the films the member started, then what TMDb lists (a film opens on the copies the providers have of it)
function Home({ round, onSelect }: { round: number; onSelect: (m: Movie) => void }) {
  const { t } = useI18n();
  const resume = useApi<Movie[]>(getContinue, [], [round]); // what the member watched: it changes when a film window closes
  return (
    <main>
      {resume.data.length > 0 && <Row title={t("home.continue")} state={resume} onSelect={onSelect} />}
      <Catalog onSelect={onSelect} />
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
  const [profileId, setProfileId] = useState<number | null>(null); // the member whose profile window is open
  const [selected, setSelected] = useState<Movie | null>(null);
  const [round, setRound] = useState(0); // counts the film windows closed: "continue watching" is asked again
  const closeMovie = () => {
    setSelected(null);
    setRound((n) => n + 1);
  };
  const searching = q.trim() !== "";

  // Escape closes the window on top: the profile, else the movie sheet
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (profileId !== null) setProfileId(null);
      else closeMovie();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [profileId]);

  const shelf = (title: string, empty: string, load: (signal: AbortSignal) => Promise<Movie[]>) => (
    <Shelf key={view} title={title} empty={empty} load={load} round={round} onSelect={setSelected} />
  );

  const page = () => {
    if (searching) return <main><Catalog q={q.trim()} onSelect={setSelected} /></main>;
    if (view === "members") return <Members onOpen={setProfileId} />;
    if (view === "list") return shelf(t("nav.list"), t("shelf.list.empty"), (s) => getShelf("list", s));
    if (view === "favorites") return shelf(t("nav.favorites"), t("shelf.favorites.empty"), (s) => getShelf("favorite", s));
    if (view === "downloads") return shelf(t("nav.downloads"), t("shelf.downloads.empty"), getDownloads);
    switch (view) {
      case "home": return <Home round={round} onSelect={setSelected} />;
      case "films": return <main><Catalog key="films" kind="movie" onSelect={setSelected} /></main>;
      default: return <main><Catalog key="series" kind="tv" onSelect={setSelected} /></main>;
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
          <AccountMenu user={user} onAccount={() => setProfileId(user.id)} onLogout={onLogout} />
        </div>
      </header>

      {page()}

      <footer>
        <span>© Hypertube</span>
        <span>{t("footer.legal")} · {t("footer.credit")}</span>
      </footer>

      {selected && <MovieModal key={selected.id} movie={selected} me={user} onClose={closeMovie} onProfile={setProfileId} />}
      {profileId !== null && <ProfileModal id={profileId} me={user} onUpdate={onUserChange} onClose={() => setProfileId(null)} />}
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
  const signOut = () => logout().finally(() => setUser(null));
  if (!user.welcomed) return <Welcome me={user} onDone={setUser} onLogout={signOut} />;
  return <Library user={user} onUserChange={setUser} onLogout={signOut} />;
}
