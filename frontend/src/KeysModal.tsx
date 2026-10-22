import { useEffect, useState } from "react";
import { getSettings, setKeys, type Keys } from "./api";
import { errorText, useI18n } from "./i18n";

const FIELDS: { name: keyof Keys; label: string; secret: boolean }[] = [
  { name: "tmdb_api_key", label: "keys.tmdb", secret: true },
  { name: "opensubtitles_api_key", label: "keys.opensubtitles", secret: true },
  { name: "opensubtitles_username", label: "keys.os_user", secret: false },
  { name: "opensubtitles_password", label: "keys.os_password", secret: true },
];

// the keys of the services the app asks (TMDb for the films, OpenSubtitles for the subtitles); saved on this machine
export default function KeysModal({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const [current, setCurrent] = useState<Keys | null>(null);
  const [typed, setTyped] = useState<Partial<Record<keyof Keys, string>>>({});
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    getSettings(ctrl.signal).then((s) => setCurrent(s.keys)).catch((e) => e.name !== "AbortError" && setMessage({ ok: false, text: errorText(t, e) }));
    return () => ctrl.abort();
  }, []);

  async function save() {
    try {
      const saved = await setKeys(Object.fromEntries(Object.entries(typed).filter(([, v]) => v !== undefined)));
      setCurrent(saved.keys);
      setTyped({});
      setMessage({ ok: true, text: t("keys.saved") });
    } catch (e) {
      setMessage({ ok: false, text: errorText(t, e) });
    }
  }

  return (
    <div className="overlay top" onClick={onClose}>
      <div className="modal sources" role="dialog" aria-modal="true" aria-label={t("keys.title")} onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose} aria-label={t("modal.close")}>✕</button>
        <h2>{t("keys.title")}</h2>
        <p className="src-note">{t("keys.note")}</p>
        <form className="src-form" onSubmit={(e) => { e.preventDefault(); void save(); }}>
          {FIELDS.map((f) => {
            const set = !!current?.[f.name];
            return (
              <label key={f.name} className="src-field">
                <span>{t(f.label)} {set && f.secret && <em className="key-set">✓ {t("keys.set")}</em>}</span>
                <input
                  type={f.secret ? "password" : "text"}
                  autoComplete="off"
                  maxLength={200}
                  placeholder={f.secret ? (set ? t("keys.keep") : "") : String(current?.[f.name] ?? "")}
                  value={typed[f.name] ?? (f.secret ? "" : String(current?.[f.name] ?? ""))}
                  onChange={(e) => setTyped({ ...typed, [f.name]: e.target.value })}
                />
              </label>
            );
          })}
          {message && <p className={message.ok ? "form-ok" : "form-error"} role={message.ok ? "status" : "alert"}>{message.text}</p>}
          <div className="src-actions">
            <button type="button" className="btn-link" onClick={onClose}>{t("keys.close")}</button>
            <button className="btn-post" disabled={Object.keys(typed).length === 0}>{t("keys.save")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
