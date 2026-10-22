import { useMemo, useState } from "react";
import { addSource, getSourceConfig, listSources, removeSource, testSource, type SearchSource, type SourceField } from "./api";
import { errorText, useI18n } from "./i18n";
import { useApi } from "./useApi";

const SHOWN = 40; // of the hundreds Jackett knows: the search narrows them

function Field({ field, value, onChange }: { field: SourceField; value: unknown; onChange: (v: unknown) => void }) {
  if (field.type === "inputbool") {
    return <label className="src-field check"><input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} /> {field.name}</label>;
  }
  if (field.type === "inputselect" && field.options) {
    return (
      <label className="src-field">
        <span>{field.name}</span>
        <select value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
          {Object.entries(field.options).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
        </select>
      </label>
    );
  }
  return (
    <label className="src-field">
      <span>{field.name}</span>
      <input type={field.type === "inputpassword" ? "password" : "text"} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

// the sources the search asks (Jackett's indexers): the member's own, and a catalogue to add from. Which sources to use, and whether
// their content may be downloaded where the member lives, is the member's call.
export default function SourcesModal({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const [round, setRound] = useState(0);
  const sources = useApi<SearchSource[]>(listSources, [], [round]);
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<"public" | "all">("public");
  const [editing, setEditing] = useState<{ source: SearchSource; fields: SourceField[]; values: Record<string, unknown> } | null>(null);
  const [tests, setTests] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const mine = sources.data.filter((s) => s.configured);
  const found = useMemo(() => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    return sources.data
      .filter((s) => !s.configured && (kind === "all" || s.type === "public") && words.every((w) => `${s.name} ${s.description ?? ""} ${s.language ?? ""}`.toLowerCase().includes(w)))
      .slice(0, SHOWN);
  }, [sources.data, query, kind]);

  async function run(id: string, action: () => Promise<unknown>) {
    setBusy(id);
    setError(null);
    let done = false;
    try {
      await action();
      setRound((n) => n + 1);
      done = true;
    } catch (e) {
      setError(errorText(t, e));
    }
    setBusy(null);
    return done;
  }

  async function add(source: SearchSource) {
    // a public source needs nothing more; the others ask for an account or a setting first
    if (source.type === "public") return run(source.id, () => addSource(source.id, {}));
    setBusy(source.id);
    setError(null);
    try {
      const fields = await getSourceConfig(source.id);
      setEditing({ source, fields, values: Object.fromEntries(fields.map((f) => [f.id, f.value])) });
    } catch (e) {
      setError(errorText(t, e));
    }
    setBusy(null);
  }

  async function test(source: SearchSource) {
    setTests((x) => ({ ...x, [source.id]: "…" }));
    try {
      const res = await testSource(source.id);
      setTests((x) => ({ ...x, [source.id]: res.ok ? `✓ ${t("sources.works")}` : `✕ ${res.error ?? t("sources.fails")}` }));
    } catch (e) {
      setTests((x) => ({ ...x, [source.id]: `✕ ${errorText(t, e)}` }));
    }
  }

  return (
    <div className="overlay top" onClick={onClose}>
      <div className="modal sources" role="dialog" aria-modal="true" aria-label={t("sources.title")} onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose} aria-label={t("modal.close")}>✕</button>
        <h2>{t("sources.title")}</h2>
        <p className="src-note">{t("sources.note")}</p>
        {error && <p className="form-error" role="alert">{error}</p>}
        {sources.error ? <p className="form-error" role="alert">{errorText(t, sources.error)}</p> : null}

        <h3>{t("sources.mine")}</h3>
        {!sources.loading && mine.length === 0 && <p className="notice">{t("sources.none")}</p>}
        <ul className="src-list">
          {mine.map((s) => (
            <li key={s.id}>
              <div className="src-name"><b>{s.name}</b>{tests[s.id] && <small>{tests[s.id]}</small>}</div>
              <button className="btn-link" onClick={() => void test(s)}>{t("sources.test")}</button>
              <button className="btn-link" disabled={busy === s.id} onClick={() => void run(s.id, () => removeSource(s.id))}>{t("sources.remove")}</button>
            </li>
          ))}
        </ul>

        <h3>{t("sources.add")}</h3>
        {editing ? (
          <form className="src-form" onSubmit={(e) => { e.preventDefault(); void run(editing.source.id, () => addSource(editing.source.id, editing.values)).then((done) => done && setEditing(null)); }}>
            <b>{editing.source.name}</b>
            {editing.fields.length === 0 && <p className="notice">{t("sources.nothing")}</p>}
            {editing.fields.map((f) => <Field key={f.id} field={f} value={editing.values[f.id]} onChange={(v) => setEditing({ ...editing, values: { ...editing.values, [f.id]: v } })} />)}
            <div className="src-actions">
              <button type="button" className="btn-link" onClick={() => setEditing(null)}>{t("sources.cancel")}</button>
              <button className="btn-post" disabled={busy === editing.source.id}>{t("sources.save")}</button>
            </div>
          </form>
        ) : (
          <>
            <div className="src-search">
              <input type="search" placeholder={t("sources.search")} aria-label={t("sources.search")} value={query} maxLength={60} onChange={(e) => setQuery(e.target.value)} />
              <select value={kind} aria-label={t("sources.kind")} onChange={(e) => setKind(e.target.value as "public" | "all")}>
                <option value="public">{t("sources.kind.public")}</option>
                <option value="all">{t("sources.kind.all")}</option>
              </select>
            </div>
            <ul className="src-list">
              {found.map((s) => (
                <li key={s.id}>
                  <div className="src-name"><b>{s.name}</b><small>{[s.type, s.language].filter(Boolean).join(" · ")}</small>{s.description && <small className="src-desc">{s.description}</small>}</div>
                  <button className="btn-link" disabled={busy === s.id} onClick={() => void add(s)}>{t("sources.addone")}</button>
                </li>
              ))}
              {!sources.loading && found.length === 0 && <li className="notice">{t("sources.nomatch")}</li>}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
