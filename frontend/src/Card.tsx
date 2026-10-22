import { useEffect, useState, type ReactNode } from "react";
import { setBookmark, type Movie, type Shelf } from "./api";
import { useI18n } from "./i18n";
import { poster } from "./format";

// thin line icons, drawn so that they sit in the middle of the round button
const Svg = ({ children, fill }: { children: ReactNode; fill?: boolean }) => (
  <svg viewBox="0 0 24 24" width="12" height="12" fill={fill ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
);
const Star = ({ on }: { on: boolean }) => <Svg fill={on}><path d="M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.9L12 16.9l-5.2 2.8 1-5.9-4.3-4.1 5.9-.8z" /></Svg>;
const Plus = () => <Svg><path d="M12 5v14M5 12h14" /></Svg>;
const Tick = () => <Svg><path d="M5 12.5l4.5 4.5L19 7.5" /></Svg>;

// the star (favorites) and the + (my list), always shown on a thumbnail: full or checked when it is in; `children` sit next to them (the rating)
export function Marks({ favorite, listed, save, children }: { favorite?: boolean; listed?: boolean; save: (kind: Shelf, on: boolean) => Promise<void>; children?: ReactNode }) {
  const { t } = useI18n();
  const [marks, setMarks] = useState({ favorite: !!favorite, list: !!listed });
  useEffect(() => setMarks({ favorite: !!favorite, list: !!listed }), [favorite, listed]);

  async function toggle(kind: Shelf) {
    const on = !marks[kind];
    setMarks((m) => ({ ...m, [kind]: on }));
    try {
      await save(kind, on);
    } catch {
      setMarks((m) => ({ ...m, [kind]: !on })); // the server refused: put the icon back
    }
  }

  return (
    <span className="marks">
      <button className={`pin star${marks.favorite ? " on" : ""}`} aria-pressed={marks.favorite} aria-label={t("modal.favorite")} title={t("modal.favorite")} onClick={() => void toggle("favorite")}>
        <Star on={marks.favorite} />
      </button>
      <button className={`pin${marks.list ? " on" : ""}`} aria-pressed={marks.list} aria-label={t("modal.list")} title={t("modal.list")} onClick={() => void toggle("list")}>
        {marks.list ? <Tick /> : <Plus />}
      </button>
      {children}
    </span>
  );
}

// a thumbnail: name, year, TMDb rating, cover; a check and a dimmed cover tell which ones the member already watched;
// the + and the star (always shown) add it to the favorites and to my list without opening it
export function Card({ movie, onSelect }: { movie: Movie; onSelect: (m: Movie) => void }) {
  const { t } = useI18n();
  return (
    <div className={`card${movie.watched ? " watched" : ""}`} style={poster(movie)}>
      <button className="open" aria-label={movie.title} onClick={() => onSelect(movie)} />
      {movie.resolution && <span className="badge">{movie.resolution}</span>}
      {"state" in movie && movie.state === "downloading" && <span className="dlbadge">⬇ {Math.round(Number("progress" in movie ? movie.progress : 0) * 100)}%</span>}
      {typeof movie.played === "number" && movie.played > 0 && (
        <span className="played" role="progressbar" aria-label={t("card.progress")} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(movie.played * 100)}>
          <i style={{ width: `${Math.round(movie.played * 100)}%` }} />
        </span>
      )}
      {movie.watched && <span className="seen" title={t("card.watched")} role="img" aria-label={t("card.watched")}>✓</span>}
      <span className="ttl">
        {movie.title}
        <span className="sub">{movie.year ?? t("year.unknown")}</span>
        {movie.match && movie.match.kind !== "title" && (
          <span className="why">{t(`why.${movie.match.kind}`, { name: movie.match.label ?? "" })}</span>
        )}
      </span>
      <Marks favorite={movie.favorite} listed={movie.listed} save={(kind, on) => setBookmark(movie.id, kind, on)}>
        {movie.rating !== null && <span className="rating" title={t("card.rating")}>★ {movie.rating.toFixed(1)}</span>}
      </Marks>
    </div>
  );
}
