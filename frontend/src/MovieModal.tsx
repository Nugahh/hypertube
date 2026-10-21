import { useCallback, useEffect, useState } from "react";
import { getMovie, setBookmark, startDownload, type Movie, type MovieDetails, type Shelf, type User } from "./api";
import Comments from "./Comments";
import { formatSize, initials, meta, poster } from "./format";
import { errorText, useI18n } from "./i18n";
import Player from "./Player";

// the server's view of one copy of the movie (nothing / downloading / downloaded), refreshed while the window is open
function useDetails(id: number) {
  const [details, setDetails] = useState<MovieDetails | null>(null);
  const [round, setRound] = useState(0);
  useEffect(() => setDetails(null), [id]); // another provider's copy: do not show the previous one meanwhile
  useEffect(() => {
    const ctrl = new AbortController();
    const load = () => getMovie(id, ctrl.signal).then(setDetails).catch(() => {});
    load();
    const timer = setInterval(load, 2000);
    return () => {
      clearInterval(timer);
      ctrl.abort();
    };
  }, [id, round]);
  return [details, () => setRound((n) => n + 1)] as const;
}

export default function MovieModal({ movie, me, onClose, onProfile }: { movie: Movie; me: User; onClose: () => void; onProfile: (id: number) => void }) {
  const { t } = useI18n();
  const [playing, setPlaying] = useState(false);
  const [copy, setCopy] = useState(movie.id); // the provider's copy that is played or downloaded
  const [details, refresh] = useDetails(copy);
  const [error, setError] = useState<string | null>(null);
  const [marks, setMarks] = useState({ favorite: !!movie.favorite, list: !!movie.listed }); // the star and the +
  const state = details?.state ?? "idle";
  const stopPlaying = useCallback(() => setPlaying(false), []); // stable: the player's idle timer restarts whenever it changes

  async function toggle(kind: Shelf) {
    const on = !marks[kind];
    setError(null);
    setMarks({ ...marks, [kind]: on });
    try {
      await setBookmark(movie.id, kind, on);
    } catch (e) {
      setMarks((m) => ({ ...m, [kind]: !on }));
      setError(errorText(t, e));
    }
  }

  async function download(id: number) {
    setError(null);
    setCopy(id);
    try {
      await startDownload(id);
      refresh();
    } catch (e) {
      setError(errorText(t, e));
    }
  }

  const sources = movie.sources?.length ? movie.sources : [movie];
  if (playing) return <Player movie={{ ...movie, id: copy }} details={details} onBack={stopPlaying} onChanged={refresh} />;
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={movie.title} onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose} aria-label={t("modal.close")}>✕</button>
        <div className="m-hero" style={poster(movie)}>
          <h2>{movie.title}</h2>
        </div>
        <div className="m-body">
          <div className="meta">
            {[movie.year, details?.runtime ? t("modal.runtime", { n: details.runtime }) : null, movie.rating !== null ? `★ ${movie.rating.toFixed(1)}` : null, movie.resolution, formatSize(movie.size)]
              .filter(Boolean)
              .join(" · ") || meta(movie)}
          </div>
          <div className="m-actions">
            <button className={`mark${marks.favorite ? " on" : ""}`} aria-pressed={marks.favorite} onClick={() => toggle("favorite")}>
              {marks.favorite ? "★" : "☆"} {t("modal.favorite")}
            </button>
            <button className={`mark${marks.list ? " on" : ""}`} aria-pressed={marks.list} onClick={() => toggle("list")}>
              {marks.list ? "✓" : "+"} {t("modal.list")}
            </button>
          </div>
          {details && details.genres.length > 0 && <div className="genres">{details.genres.map((g) => <span key={g} className="chip static">{g}</span>)}</div>}
          {details?.overview && <p className="overview">{details.overview}</p>}
          {details && (details.directors.length > 0 || details.producers.length > 0 || details.cast.length > 0) && (
            <dl className="credits">
              {details.directors.length > 0 && <><dt>{t("modal.director")}</dt><dd>{details.directors.join(", ")}</dd></>}
              {details.producers.length > 0 && <><dt>{t("modal.producer")}</dt><dd>{details.producers.join(", ")}</dd></>}
              {details.cast.length > 0 && <><dt>{t("modal.cast")}</dt><dd>{details.cast.join(", ")}</dd></>}
            </dl>
          )}
          <h3>{t("modal.providers")}</h3>
          {sources.map((s) => (
            <div className={`prov${s.id === copy ? " on" : ""}`} key={s.id}>
              <div className="logo-sq">{initials(s.provider)}</div>
              <div className="info">
                <b>{s.provider}</b>
                <span>{[t("modal.seeders", { n: s.seeders }), s.resolution, formatSize(s.size)].filter(Boolean).join(" · ")}</span>
              </div>
              <button className="play" onClick={() => { setCopy(s.id); setPlaying(true); }}>{t("modal.play")}</button>
              <button className="dl" onClick={() => download(s.id)} disabled={s.id === copy && state !== "idle"} title={t("modal.download")} aria-label={t("modal.download")}>⬇</button>
            </div>
          ))}
          {state === "downloading" && details && <p className="dl-state">{t("dl.downloading", { pct: Math.round(details.progress * 100) })}</p>}
          {state === "ready" && <p className="dl-state">{t("dl.done")}</p>}
          {error && <p className="form-error" role="alert">{error}</p>}
          <Comments movieId={movie.id} me={me} onProfile={onProfile} />
        </div>
      </div>
    </div>
  );
}
