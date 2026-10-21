import type { Movie } from "./api";
import { useI18n } from "./i18n";
import { poster } from "./format";

// a thumbnail: name, year, TMDb rating, cover; a check and a dimmed cover tell which ones the member already watched
export function Card({ movie, onSelect }: { movie: Movie; onSelect: (m: Movie) => void }) {
  const { t } = useI18n();
  return (
    <button className={`card${movie.watched ? " watched" : ""}`} style={poster(movie)} onClick={() => onSelect(movie)}>
      {movie.resolution && <span className="badge">{movie.resolution}</span>}
      {movie.rating !== null && <span className="rating" title={t("card.rating")}>★ {movie.rating.toFixed(1)}</span>}
      {movie.watched && <span className="seen" title={t("card.watched")} role="img" aria-label={t("card.watched")}>✓</span>}
      <span className="ttl">
        {movie.title}
        <span className="sub">{movie.year ?? t("year.unknown")}</span>
        {movie.match && movie.match.kind !== "title" && (
          <span className="why">{t(`why.${movie.match.kind}`, { name: movie.match.label ?? "" })}</span>
        )}
      </span>
    </button>
  );
}
