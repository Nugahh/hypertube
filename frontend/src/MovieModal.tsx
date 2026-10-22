import { useCallback, useEffect, useState } from "react";
import { cancelDownload, deleteFile, getMovie, getStates, type CopyState, setBookmark, startDownload, type Movie, type MovieDetails, type Shelf, type Tier, type User } from "./api";
import Comments from "./Comments";
import { clock, formatSize, initials, meta, poster } from "./format";
import { errorText, useI18n } from "./i18n";
import { CancelIcon, DownloadIcon, TickIcon } from "./icons";
import { LetterboxdLink } from "./logos";
import Player from "./Player";

const TIERS: Tier[] = ["4K", "1080p", "720p"]; // the order of the quality tabs

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

// one button for the life of a copy on the server: download, then it fills as the file arrives (click to cancel), then a tick
// (the cross shows on hover, to erase it)
function DownloadButton({ state, progress, onDownload, onCancel, onErase }: {
  state: "idle" | "downloading" | "ready";
  progress: number;
  onDownload: () => void;
  onCancel: () => void;
  onErase: () => void;
}) {
  const { t } = useI18n();
  if (state === "ready") {
    return (
      <button className="dl done" onClick={onErase} title={t("modal.erase")} aria-label={t("modal.erase")}>
        <span className="when-idle"><TickIcon /></span>
        <span className="when-hover"><CancelIcon /></span>
      </button>
    );
  }
  if (state === "downloading") {
    const pct = Math.round(progress * 100);
    return (
      <button className="dl busy" style={{ "--p": `${pct}%` } as React.CSSProperties} onClick={onCancel} title={`${t("modal.cancelDownload")} (${pct}%)`} aria-label={t("modal.cancelDownload")}>
        <span className="fill" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} />
        <span className="when-idle">{pct}%</span>
        <span className="when-hover"><CancelIcon /></span>
      </button>
    );
  }
  return <button className="dl" onClick={onDownload} title={t("modal.download")} aria-label={t("modal.download")}><DownloadIcon /></button>;
}

// the download of every copy of the film, so each provider's button tells the truth (a copy may be downloading from another window)
function useStates(ids: number[]) {
  const [states, setStates] = useState<Record<number, CopyState>>({});
  const [round, setRound] = useState(0);
  const key = ids.join(",");
  useEffect(() => {
    const ctrl = new AbortController();
    const load = () => getStates(ids, ctrl.signal).then(setStates).catch(() => {});
    load();
    const timer = setInterval(load, 2000);
    return () => {
      clearInterval(timer);
      ctrl.abort();
    };
  }, [key, round]);
  return [states, () => setRound((n) => n + 1)] as const;
}

export default function MovieModal({ movie, me, onClose, onProfile }: { movie: Movie; me: User; onClose: () => void; onProfile: (id: number) => void }) {
  const { t } = useI18n();
  const [playing, setPlaying] = useState(false);
  const [copy, setCopy] = useState(movie.resume?.id ?? movie.id); // the provider's copy that is played or downloaded: the one the member was watching
  const [details, refresh] = useDetails(copy);
  const [error, setError] = useState<string | null>(null);
  const [erasing, setErasing] = useState<number | null>(null); // the confirmation window of the delete
  const [marks, setMarks] = useState({ favorite: !!movie.favorite, list: !!movie.listed }); // the star and the +
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

  async function erase(id: number) {
    setErasing(null);
    setError(null);
    try {
      await deleteFile(id);
      refreshAll();
    } catch (e) {
      setError(errorText(t, e));
    }
  }

  async function cancel(id: number) {
    setError(null);
    try {
      await cancelDownload(id);
      refreshAll();
    } catch (e) {
      setError(errorText(t, e));
    }
  }

  async function download(id: number) {
    setError(null);
    setCopy(id);
    try {
      await startDownload(id);
      refreshAll();
    } catch (e) {
      setError(errorText(t, e));
    }
  }

  const sources = movie.sources?.length ? movie.sources : [movie];
  const [states, refreshStates] = useStates(sources.map((s) => s.id));
  const refreshAll = () => { refresh(); refreshStates(); };
  const tiers = TIERS.filter((x) => sources.some((s) => s.tier === x)); // a tab per quality the providers have
  const [tier, setTier] = useState<Tier>(() => sources.find((s) => s.id === copy)?.tier ?? tiers[0]); // opens on the quality of the copy in use
  if (playing) return <Player movie={{ ...movie, id: copy }} details={details} resumeAt={movie.resume?.position} onBack={stopPlaying} onChanged={refresh} />;
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={movie.title} onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose} aria-label={t("modal.close")}>✕</button>
        <div className="m-top">
          <div className="m-poster" style={poster(movie)} />
          <div className="m-info">
            <h2>{movie.title}</h2>
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
              {details?.tmdb_id && <LetterboxdLink tmdbId={details.tmdb_id} />}
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
          </div>
        </div>
        <div className="m-body">
          <h3>{t("modal.providers")}</h3>
          <div className="chips" role="tablist" aria-label={t("modal.quality")}>
            {tiers.map((x) => (
              <button key={x} role="tab" aria-selected={x === tier} className={`chip ${x === tier ? "on" : ""}`} onClick={() => setTier(x)}>{x}</button>
            ))}
          </div>
          {sources.filter((s) => s.tier === tier).map((s) => (
            <div className={`prov${s.id === copy ? " on" : ""}`} key={s.id}>
              <div className="logo-sq">{initials(s.provider)}</div>
              <div className="info">
                <b>{s.provider}</b>
                <span>{[t("modal.seeders", { n: s.seeders }), s.resolution, formatSize(s.size)].filter(Boolean).join(" · ")}</span>
              </div>
              <button className="play" onClick={() => { setCopy(s.id); setPlaying(true); }}>{movie.resume ? t("modal.resume", { time: clock(movie.resume.position) }) : t("modal.play")}</button>
              <DownloadButton
                state={states[s.id]?.state ?? "idle"}
                progress={states[s.id]?.progress ?? 0}
                onDownload={() => download(s.id)}
                onCancel={() => void cancel(s.id)}
                onErase={() => setErasing(s.id)}
              />
            </div>
          ))}
          {error && <p className="form-error" role="alert">{error}</p>}
          {erasing !== null && (
            <div className="overlay top" onClick={() => setErasing(null)}>
              <div className="modal confirm" role="alertdialog" aria-modal="true" aria-label={t("erase.title")} onClick={(e) => e.stopPropagation()}>
                <h3>{t("erase.title")}</h3>
                <p>{t("erase.text")}</p>
                <div className="confirm-actions">
                  <button className="btn-link" autoFocus onClick={() => setErasing(null)}>{t("erase.cancel")}</button>
                  <button className="btn-post" onClick={() => void erase(erasing)}>{t("erase.confirm")}</button>
                </div>
              </div>
            </div>
          )}
          <Comments movieId={movie.id} me={me} onProfile={onProfile} />
        </div>
      </div>
    </div>
  );
}
