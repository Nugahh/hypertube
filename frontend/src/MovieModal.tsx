import { useCallback, useEffect, useState } from "react";
import { getMovie, startDownload, type Movie, type MovieDetails, type User } from "./api";
import Comments from "./Comments";
import { formatSize, initials, meta, poster } from "./format";
import { errorText, useI18n } from "./i18n";
import Player from "./Player";

// the server's view of the movie (nothing / downloading / downloaded), refreshed while the window is open
function useDetails(movie: Movie) {
  const [details, setDetails] = useState<MovieDetails | null>(null);
  const [round, setRound] = useState(0);
  useEffect(() => {
    const ctrl = new AbortController();
    const load = () => getMovie(movie.id, ctrl.signal).then(setDetails).catch(() => {});
    load();
    const timer = setInterval(load, 2000);
    return () => {
      clearInterval(timer);
      ctrl.abort();
    };
  }, [movie.id, round]);
  return [details, () => setRound((n) => n + 1)] as const;
}

export default function MovieModal({ movie, me, onClose, onProfile }: { movie: Movie; me: User; onClose: () => void; onProfile: (id: number) => void }) {
  const { t } = useI18n();
  const [playing, setPlaying] = useState(false);
  const [details, refresh] = useDetails(movie);
  const [error, setError] = useState<string | null>(null);
  const state = details?.state ?? "idle";
  const stopPlaying = useCallback(() => setPlaying(false), []); // stable: the player's idle timer restarts whenever it changes

  async function download() {
    setError(null);
    try {
      await startDownload(movie.id);
      refresh();
    } catch (e) {
      setError(errorText(t, e));
    }
  }

  if (playing) return <Player movie={movie} details={details} onBack={stopPlaying} onChanged={refresh} />;
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
          <div className="prov">
            <div className="logo-sq">{initials(movie.provider)}</div>
            <div className="info">
              <b>{movie.provider}</b>
              <span>{t("modal.seeders", { n: movie.seeders })} · {formatSize(movie.size)}</span>
            </div>
            <button className="play" onClick={() => setPlaying(true)}>{t("modal.play")}</button>
            <button className="dl" onClick={download} disabled={state !== "idle"} title={t("modal.download")} aria-label={t("modal.download")}>⬇</button>
          </div>
          {state === "downloading" && details && <p className="dl-state">{t("dl.downloading", { pct: Math.round(details.progress * 100) })}</p>}
          {state === "ready" && <p className="dl-state">{t("dl.done")}</p>}
          {error && <p className="form-error" role="alert">{error}</p>}
          <Comments movieId={movie.id} me={me} onProfile={onProfile} />
        </div>
      </div>
    </div>
  );
}
