import { useEffect, useRef, useState } from "react";
import { getLibrary, type Genre, type Movie, type Sort } from "./api";
import { Card } from "./Card";
import { errorText, useI18n } from "./i18n";
import { useInfinite } from "./useApi";

const SORTS: Sort[] = ["relevance", "popularity", "name", "year", "rating"];
const RATINGS = [0, 5, 6, 7, 8];

// genre names come translated by id; the backend's English label is the fallback for a genre added later
export function useGenreLabel() {
  const { t } = useI18n();
  return (g: Genre) => {
    const key = `genre.${g.id}`;
    const label = t(key);
    return label === key ? g.label : label;
  };
}

const year = (v: string) => (/^\d{4}$/.test(v) ? Number(v) : undefined);

// the library as a grid that keeps loading the next page while the member scrolls (no "next page" link), with sort and filters
export default function LibraryGrid({ title, q = "", genre, genres, filters = true, onSelect }: {
  title: string;
  q?: string;
  genre?: string; // fixed by the parent (genre chips, series)
  genres?: Genre[]; // when given, a genre filter is offered
  filters?: boolean; // the sort and filter bar (the genre rows of Films and Series go without)
  onSelect: (m: Movie) => void;
}) {
  const { t } = useI18n();
  const label = useGenreLabel();
  const [sort, setSort] = useState<Sort | null>(null); // null: the server's default (relevance for a search, else popularity)
  const [minRating, setMinRating] = useState(0);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [picked, setPicked] = useState("");
  const wanted = genre ?? (picked || undefined);
  const searching = q.trim() !== "";

  const pages = useInfinite<Movie>(
    (page, signal) =>
      getLibrary({ q, genre: wanted, sort: sort ?? undefined, min_rating: minRating || undefined, year_from: year(from), year_to: year(to), page }, signal),
    [q, wanted, sort, minRating, year(from), year(to)],
    searching ? 350 : 200,
  );

  // while the end marker is on screen, load the next page; observing again after each page covers a tall screen
  const end = useRef<HTMLDivElement>(null);
  const more = useRef(pages.more);
  more.current = pages.more;
  useEffect(() => {
    if (!end.current || !pages.hasMore || pages.loading || pages.error) return;
    const watcher = new IntersectionObserver((entries) => entries[0].isIntersecting && more.current(), { rootMargin: "400px" });
    watcher.observe(end.current);
    return () => watcher.disconnect();
  }, [pages.items.length, pages.hasMore, pages.loading, pages.error]);

  return (
    <section className="row">
      <h2>{title}</h2>
      {filters && <div className="filters">
        <label>
          {t("lib.sort")}
          <select value={sort ?? (searching ? "relevance" : "popularity")} onChange={(e) => setSort(e.target.value as Sort)}>
            {SORTS.filter((s) => s !== "relevance" || searching).map((s) => <option key={s} value={s}>{t(`sort.${s}`)}</option>)}
          </select>
        </label>
        <label>
          {t("lib.rating")}
          <select value={minRating} onChange={(e) => setMinRating(Number(e.target.value))}>
            {RATINGS.map((r) => <option key={r} value={r}>{r ? t("lib.rating.n", { n: r }) : t("lib.rating.any")}</option>)}
          </select>
        </label>
        <label>
          {t("lib.year.from")}
          <input value={from} onChange={(e) => setFrom(e.target.value)} inputMode="numeric" maxLength={4} placeholder="1950" />
        </label>
        <label>
          {t("lib.year.to")}
          <input value={to} onChange={(e) => setTo(e.target.value)} inputMode="numeric" maxLength={4} placeholder="2020" />
        </label>
        {genres && !genre && (
          <label>
            {t("lib.genre")}
            <select value={picked} onChange={(e) => setPicked(e.target.value)}>
              <option value="">{t("lib.genre.all")}</option>
              {genres.map((g) => <option key={g.id} value={g.id}>{label(g)}</option>)}
            </select>
          </label>
        )}
        {!pages.error && <span className="count">{t("lib.total", { n: pages.total })}</span>}
      </div>}
      {pages.error ? <p className="notice" role="alert">{errorText(t, pages.error)}</p> : null}
      {!pages.loading && !pages.error && pages.items.length === 0 && <p className="notice">{t("empty")}</p>}
      <div className="grid">{pages.items.map((m) => <Card key={m.id} movie={m} onSelect={onSelect} />)}</div>
      <div ref={end} className="end">{pages.loading && <span className="notice">{t("loading")}</span>}</div>
    </section>
  );
}
