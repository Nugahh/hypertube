import { useEffect, useRef, useState, type ReactNode } from "react";
import { getContinue, getDownloads, getShelf, me, setLanguage, type Movie, type User } from "./api";
import { Card } from "./Card";
import Catalog from "./Catalog";
import LangMenu from "./LangMenu";
import { errorText, useI18n } from "./i18n";
import MovieModal from "./MovieModal";
import Shelf from "./Shelf";
import { useApi, type State } from "./useApi";

type View = "home" | "films" | "series" | "list" | "favorites" | "downloads";
const TABS: [View, string][] = [
  ["home", "nav.home"],
  ["films", "nav.films"],
  ["series", "nav.series"],
  ["list", "nav.list"],
  ["favorites", "nav.favorites"],
  ["downloads", "nav.downloads"],
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
      <Catalog kind="movie" onSelect={onSelect} />
    </main>
  );
}

function Library({ user, onUserChange }: { user: User; onUserChange: (u: User) => void }) {
  const { t, setLang } = useI18n();
  const pickLang = (language: User["language"]) => {
    // the server answers in the language it has on record: it is saved first, then the site (and what it shows) changes
    setLanguage(language).then(onUserChange).catch(() => setLang(language));
  };
  const [q, setQ] = useState("");
  const [view, setView] = useState<View>("home");
  const [selected, setSelected] = useState<Movie | null>(null);
  const [round, setRound] = useState(0); // counts the film windows closed: "continue watching" is asked again
  const closeMovie = () => {
    setSelected(null);
    setRound((n) => n + 1);
  };
  const searching = q.trim() !== "";

  // Escape closes the movie sheet
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && closeMovie();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const shelf = (title: string, empty: string, load: (signal: AbortSignal) => Promise<Movie[]>, catalog?: "list" | "favorite") => (
    <Shelf key={view} title={title} empty={empty} load={load} catalog={catalog} round={round} onSelect={setSelected} />
  );

  const page = () => {
    if (searching) return <main><Catalog q={q.trim()} onSelect={setSelected} /></main>;
    if (view === "list") return shelf(t("nav.list"), t("shelf.list.empty"), (s) => getShelf("list", s), "list");
    if (view === "favorites") return shelf(t("nav.favorites"), t("shelf.favorites.empty"), (s) => getShelf("favorite", s), "favorite");
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
          <LangMenu onPick={pickLang} />
        </div>
      </header>

      {page()}

      <footer>
        <span>© Hypertube</span>
        <span>{t("footer.legal")} · {t("footer.credit")}</span>
      </footer>

      {selected && <MovieModal key={selected.id} movie={selected} me={user} onClose={closeMovie} />}
    </>
  );
}

export default function App() {
  const { t, setLang } = useI18n();
  const [user, setUser] = useState<User>();

  // the app's server may still be starting: ask again until it answers
  useEffect(() => {
    let timer = 0;
    const ask = () => me().then(setUser).catch(() => (timer = window.setTimeout(ask, 1000)));
    ask();
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (user) setLang(user.language);
  }, [user?.language]);

  if (!user) return <p className="notice" role="status">{t("loading")}</p>;
  return <Library user={user} onUserChange={setUser} />;
}
