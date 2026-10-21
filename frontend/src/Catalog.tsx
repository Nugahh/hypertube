import { useEffect, useRef, useState } from "react";
import { getCatalog, getCatalogCopies, getCatalogGenres, getCatalogSheet, type CatalogItem, type CatalogKind, type Movie } from "./api";
import { gradient } from "./format";
import { errorText, useI18n } from "./i18n";
import { useApi, useInfinite } from "./useApi";

const KINDS: [CatalogKind, string][] = [["movie", "catalog.movies"], ["tv", "catalog.series"]];

// a title of the catalogue: its poster, name, year and TMDb rating
function Poster({ item, onSelect }: { item: CatalogItem; onSelect: (i: CatalogItem) => void }) {
  const { t } = useI18n();
  const art = item.poster ? `url(${item.poster}), ${gradient(item.id)}` : gradient(item.id);
  return (
    <button className="card" style={{ backgroundImage: art }} onClick={() => onSelect(item)}>
      {item.rating !== null && <span className="rating" title={t("card.rating")}>★ {item.rating.toFixed(1)}</span>}
      <span className="ttl">
        {item.title}
        <span className="sub">{item.year ?? t("year.unknown")}</span>
      </span>
    </button>
  );
}

// what TMDb says of a title while the providers are asked for it; as soon as one has the film, the film's own window takes over
function Sheet({ item, onClose, onFound }: { item: CatalogItem; onClose: () => void; onFound: (m: Movie) => void }) {
  const { t } = useI18n();
  const sheet = useApi((signal) => getCatalogSheet(item.kind, item.id, signal), null, [item.kind, item.id]);
  // the providers' copies of a film (series have none yet)
  const copies = useApi<Movie | null>((signal) => (item.kind === "movie" ? getCatalogCopies(item.id, signal) : Promise.resolve(null)), null, [item.kind, item.id]);
  const copy = copies.data;
  useEffect(() => {
    if (copy) onFound(copy);
  }, [copy]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const d = sheet.data;
  const credit = (label: string, names: string[]) => names.length > 0 && <><dt>{label}</dt><dd>{names.join(", ")}</dd></>;
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={item.title} onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose} aria-label={t("modal.close")}>✕</button>
        <div className="m-top">
          <div className="m-poster" style={{ backgroundImage: item.poster ? `url(${item.poster}), ${gradient(item.id)}` : gradient(item.id) }} />
          <div className="m-info">
            <h2>{item.title}</h2>
            <div className="meta">
              {[item.year, d?.runtime ? t("modal.runtime", { n: d.runtime }) : null, item.rating !== null ? `★ ${item.rating.toFixed(1)}` : null].filter(Boolean).join(" · ")}
            </div>
            {item.genres.length > 0 && <div className="genres">{item.genres.map((g) => <span key={g} className="chip static">{g}</span>)}</div>}
            {item.overview && <p className="overview">{item.overview}</p>}
            {sheet.error ? <p className="form-error" role="alert">{errorText(t, sheet.error)}</p> : null}
            {d && (
              <dl className="credits">
                {credit(t("modal.director"), d.directors)}
                {credit(t("modal.producer"), d.producers)}
                {credit(t("modal.cast"), d.cast)}
              </dl>
            )}
          </div>
        </div>
        <div className="m-body">
          {!copy && <p className="notice">{copies.loading && item.kind === "movie" ? t("catalog.looking") : copies.error ? errorText(t, copies.error) : t("catalog.note")}</p>}
        </div>
      </div>
    </div>
  );
}

// every film or series TMDb lists, by popularity and by genre, or finds for the typed words (`q`): it keeps loading as the
// member scrolls. A fixed `kind` (the Films and Series tabs) hides the choice between the two.
export default function Catalog({ onSelect, kind: fixed, q = "" }: { onSelect: (m: Movie) => void; kind?: CatalogKind; q?: string }) {
  const { t } = useI18n();
  const [picked, setKind] = useState<CatalogKind>("movie");
  const kind = fixed ?? picked;
  const [genre, setGenre] = useState<number>();
  const [open, setOpen] = useState<CatalogItem | null>(null);
  const genres = useApi((signal) => getCatalogGenres(kind, signal), [], [kind]);
  const pages = useInfinite<CatalogItem>((page, signal) => getCatalog(kind, q ? undefined : genre, q, page, signal), [kind, genre, q], q ? 350 : 0);

  // while the end marker is on screen, load the next page (same as the library grid)
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
    <>
      {!fixed && (
        <div className="chips" role="group" aria-label={t("catalog.kind")}>
          {KINDS.map(([k, key]) => (
            <button key={k} className={`chip ${k === kind ? "on" : ""}`} aria-pressed={k === kind} onClick={() => { setKind(k); setGenre(undefined); }}>
              {t(key)}
            </button>
          ))}
        </div>
      )}
      {!q && (
        <div className="chips" role="group" aria-label={t("genres.aria")}>
          <button className={`chip ${genre === undefined ? "on" : ""}`} aria-pressed={genre === undefined} onClick={() => setGenre(undefined)}>{t("catalog.all")}</button>
          {genres.data.map((g) => (
            <button key={g.id} className={`chip ${g.id === genre ? "on" : ""}`} aria-pressed={g.id === genre} onClick={() => setGenre(g.id)}>{g.name}</button>
          ))}
        </div>
      )}
      <section className="row">
        {q && <h2>{t("results.for", { q })}</h2>}
        {pages.error ? <p className="notice" role="alert">{errorText(t, pages.error)}</p> : null}
        {q && !pages.loading && !pages.error && pages.items.length === 0 && <p className="notice">{t("empty")}</p>}
        <div className="grid">{pages.items.map((i) => <Poster key={`${i.kind}-${i.id}`} item={i} onSelect={setOpen} />)}</div>
        <div ref={end} className="end">{pages.loading && <span className="notice">{t("loading")}</span>}</div>
      </section>
      {open && <Sheet item={open} onClose={() => setOpen(null)} onFound={(m) => { setOpen(null); onSelect(m); }} />}
    </>
  );
}
