import { useEffect, useRef, useState, type ChangeEvent } from "react";
import {
  ApiError, deleteSubtitle, importFromOpenSubtitles, importSubtitleFile, searchSubtitles,
  type AudioTrack, type FoundSubtitle, type Movie, type Subtitle,
} from "./api";
import { useI18n } from "./i18n";

// the languages a subtitle can be in (the server's list), by their own name
const LANGUAGES: Record<string, string> = {
  en: "English", fr: "Français", es: "Español", de: "Deutsch", it: "Italiano", pt: "Português", nl: "Nederlands", ru: "Русский", pl: "Polski", no: "Norsk",
};
const CHANNELS: Record<number, string> = { 1: "1.0", 2: "2.0", 6: "5.1", 8: "7.1" };

const audioLabel = (a: AudioTrack) =>
  [a.label, [a.codec?.toUpperCase(), a.channels ? CHANNELS[a.channels] ?? `${a.channels}ch` : null].filter(Boolean).join(" ")].filter(Boolean).join(" · ");

function Choice({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button className={`track${on ? " on" : ""}`} aria-pressed={on} onClick={onClick}>
      <span className="tick" aria-hidden>{on ? "✓" : ""}</span>
      <span className="track-name">{children}</span>
    </button>
  );
}

// search the movie's subtitles on OpenSubtitles (the server does the call, with its own key) and add one to the player
function OpenSubtitles({ movie, onAdded, onBack }: { movie: Movie; onAdded: (s: Subtitle) => void; onBack: () => void }) {
  const { t, lang } = useI18n();
  const [wanted, setWanted] = useState<string>(lang);
  const [found, setFound] = useState<FoundSubtitle[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const problem = (e: unknown) =>
    e instanceof ApiError && e.status === 501 ? t("tracks.opensub.off") : e instanceof ApiError && e.status === 429 ? t("tracks.opensub.quota") : t("tracks.opensub.down");

  // searches by itself when the view opens and whenever the language changes
  useEffect(() => {
    const ctrl = new AbortController();
    setBusy(true);
    setError(null);
    setFound(null);
    searchSubtitles(movie.id, wanted, ctrl.signal)
      .then(setFound)
      .catch((e) => e.name !== "AbortError" && setError(problem(e)))
      .finally(() => !ctrl.signal.aborted && setBusy(false));
    return () => ctrl.abort();
  }, [wanted]);

  async function add(f: FoundSubtitle) {
    setBusy(true);
    setError(null);
    try {
      onAdded(await importFromOpenSubtitles(movie.id, f));
    } catch (e) {
      setError(problem(e));
      setBusy(false);
    }
  }

  return (
    <>
      <button className="link-small" onClick={onBack}>← {t("tracks.back")}</button>
      <div className="tracks-search">
        <select value={wanted} onChange={(e) => setWanted(e.target.value)} aria-label={t("tracks.language")}>
          {Object.entries(LANGUAGES).map(([code, name]) => <option key={code} value={code}>{name}</option>)}
        </select>
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}
      {busy && !found && !error && <p className="tracks-note">{t("tracks.opensub.loading")}</p>}
      {found?.length === 0 && <p className="tracks-note">{t("tracks.opensub.none")}</p>}
      <ul className="tracks-results">
        {found?.map((f) => (
          <li key={f.file_id}>
            <span className="track-name">
              {f.title ? `${f.title}${f.year ? ` (${f.year})` : ""}` : f.release || LANGUAGES[f.lang]}
              <small>{[f.title && f.release, t("tracks.opensub.downloads", { n: f.downloads })].filter(Boolean).join(" · ")}</small>
            </span>
            <button className="btn-link" onClick={() => add(f)} disabled={busy}>{t("tracks.opensub.add")}</button>
          </li>
        ))}
      </ul>
    </>
  );
}

// Netflix / Stremio style: audio on the left, subtitles on the right, with import and OpenSubtitles under the subtitles.
// Choices are only kept (and applied to the player) with Apply; Cancel throws them away.
export default function TracksPanel({ movie, subs, selected, audio, audioIndex, onApply, onCancel, onChanged }: {
  movie: Movie;
  subs: Subtitle[];
  selected: string | null; // the subtitle in use now: ref, or null for none
  audio: AudioTrack[] | null; // null while the server looks at the file
  audioIndex: number; // the audio track in use now
  onApply: (sub: string | null, audio: number) => void;
  onCancel: () => void;
  onChanged: () => void; // the list of subtitles changed: reload it now
}) {
  const { t } = useI18n();
  const [pickedSub, setPickedSub] = useState(selected);
  const [pickedAudio, setPickedAudio] = useState(audioIndex);
  const [view, setView] = useState<"list" | "opensub">("list");
  const [importLang, setImportLang] = useState(""); // "": the server reads it from the file name
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const picker = useRef<HTMLInputElement>(null);

  const added = (s: Subtitle) => {
    onChanged();
    setPickedSub(s.ref); // chosen, but still to apply
    setView("list");
  };

  const importError = (e: unknown) => {
    const status = e instanceof ApiError ? e.status : 0;
    return t(({ 413: "tracks.err.big", 415: "tracks.err.format", 422: "tracks.err.language", 409: "tracks.err.many" } as const)[status as 413] ?? "tracks.err.generic");
  };

  async function pick(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // lets the same file be picked again
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      added(await importSubtitleFile(movie.id, file, importLang));
    } catch (err) {
      setError(importError(err));
    }
    setBusy(false);
  }

  async function remove(s: Subtitle) {
    setError(null);
    try {
      await deleteSubtitle(movie.id, s.ref); // removing is immediate: it is the file that goes, not a choice
      if (pickedSub === s.ref) setPickedSub(null);
      onChanged();
    } catch (err) {
      setError(importError(err));
    }
  }

  return (
    <div className="tracks" role="dialog" aria-label={t("player.tracks")}>
      <section className="tracks-col" aria-label={t("tracks.audio")}>
        <h3>{t("tracks.audio")}</h3>
        {audio === null ? (
          <p className="tracks-note">{t("tracks.audio.loading")}</p>
        ) : audio.length === 0 ? (
          <Choice on onClick={() => setPickedAudio(0)}>{t("tracks.audio.default")}</Choice>
        ) : (
          audio.map((a) => <Choice key={a.index} on={a.index === pickedAudio} onClick={() => setPickedAudio(a.index)}>{audioLabel(a)}</Choice>)
        )}
        {audio !== null && audio.length > 1 && <p className="tracks-note">{t("tracks.audio.note")}</p>}
      </section>
      <section className="tracks-col" aria-label={t("tracks.subtitles")}>
        <h3>{t("tracks.subtitles")}</h3>
        {view === "opensub" ? (
          <OpenSubtitles movie={movie} onAdded={added} onBack={() => setView("list")} />
        ) : (
          <>
            <Choice on={pickedSub === null} onClick={() => setPickedSub(null)}>{t("tracks.off")}</Choice>
            {subs.length === 0 && <p className="tracks-note">{t("tracks.none")}</p>}
            {subs.map((s) => (
              <div key={s.ref} className="track-row">
                <Choice on={pickedSub === s.ref} onClick={() => setPickedSub(s.ref)}>
                  {LANGUAGES[s.lang] ?? s.lang}
                  {s.source !== "torrent" && <small>{s.source === "opensubtitles" ? "OpenSubtitles" : t("tracks.imported")} · {s.label}</small>}
                </Choice>
                {s.mine && <button className="link-small" onClick={() => remove(s)} aria-label={t("tracks.remove")}>✕</button>}
              </div>
            ))}
            <div className="tracks-actions">
              <div className="tracks-import">
                <select value={importLang} onChange={(e) => setImportLang(e.target.value)} aria-label={t("tracks.language")}>
                  <option value="">{t("tracks.import.auto")}</option>
                  {Object.entries(LANGUAGES).map(([code, name]) => <option key={code} value={code}>{name}</option>)}
                </select>
                <button className="btn-link" onClick={() => picker.current?.click()} disabled={busy}>{t("tracks.import")}</button>
                <input ref={picker} type="file" accept=".srt,.vtt,text/vtt,application/x-subrip" onChange={pick} hidden />
              </div>
              <button className={`btn-link${subs.length === 0 ? " hint" : ""}`} onClick={() => setView("opensub")}>{t("tracks.opensub")}</button>
            </div>
            {error && <p className="form-error" role="alert">{error}</p>}
          </>
        )}
      </section>
      <div className="tracks-footer">
        <button className="btn-link" onClick={onCancel}>{t("tracks.cancel")}</button>
        <button className="btn red" onClick={() => onApply(pickedSub, pickedAudio)}>{t("tracks.apply")}</button>
      </div>
    </div>
  );
}
