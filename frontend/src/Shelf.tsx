import { useEffect, useState } from "react";
import { getCatalogShelf, type CatalogItem, type Movie, type Shelf as Kind } from "./api";
import { Card } from "./Card";
import { Poster, Sheet } from "./Catalog";
import { errorText, useI18n } from "./i18n";
import { useApi } from "./useApi";

// a page of films the server keeps for the member (my list, favorites, downloads); a download in progress is asked about again every 3 s
export default function Shelf({ title, empty, load, catalog, round, onSelect }: {
  title: string;
  empty: string;
  load: (signal: AbortSignal) => Promise<Movie[]>;
  catalog?: Kind; // the titles put there from the catalogue come after the films
  round: number; // changes when a film window closes: a film may have been added or removed meanwhile
  onSelect: (m: Movie) => void;
}) {
  const { t, lang } = useI18n();
  const [tick, setTick] = useState(0);
  const films = useApi<Movie[]>(load, [], [round, tick]);
  const titles = useApi<CatalogItem[]>((signal) => (catalog ? getCatalogShelf(catalog, signal) : Promise.resolve([])), [], [catalog, round, tick, lang]);
  const [open, setOpen] = useState<CatalogItem | null>(null);
  const running = films.data.some((m) => "state" in m && m.state === "downloading");
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => setTick((n) => n + 1), 3000);
    return () => clearInterval(timer);
  }, [running]);
  return (
    <main>
      <section className="row">
        <h2>{title}</h2>
        {films.error ? <p className="notice" role="alert">{errorText(t, films.error)}</p> : null}
        {films.loading && films.data.length === 0 && <p className="notice">{t("loading")}</p>}
        {!films.loading && !films.error && films.data.length === 0 && titles.data.length === 0 && <p className="notice">{empty}</p>}
        <div className="grid">{films.data.map((m) => <Card key={m.id} movie={m} onSelect={onSelect} />)}{titles.data.map((i) => <Poster key={`${i.kind}-${i.id}`} item={i} onSelect={setOpen} />)}</div>
      </section>
      {open && <Sheet item={open} onClose={() => setOpen(null)} onFound={(m) => { setOpen(null); onSelect(m); }} />}
    </main>
  );
}
