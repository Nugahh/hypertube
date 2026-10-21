import { useEffect, useState } from "react";
import type { Movie } from "./api";
import { Card } from "./Card";
import { errorText, useI18n } from "./i18n";
import { useApi } from "./useApi";

// a page of films the server keeps for the member (my list, favorites, downloads); a download in progress is asked about again every 3 s
export default function Shelf({ title, empty, load, round, onSelect }: {
  title: string;
  empty: string;
  load: (signal: AbortSignal) => Promise<Movie[]>;
  round: number; // changes when a film window closes: a film may have been added or removed meanwhile
  onSelect: (m: Movie) => void;
}) {
  const { t } = useI18n();
  const [tick, setTick] = useState(0);
  const films = useApi<Movie[]>(load, [], [round, tick]);
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
        {!films.loading && !films.error && films.data.length === 0 && <p className="notice">{empty}</p>}
        <div className="grid">{films.data.map((m) => <Card key={m.id} movie={m} onSelect={onSelect} />)}</div>
      </section>
    </main>
  );
}
