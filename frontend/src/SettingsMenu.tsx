import { useEffect, useRef, useState } from "react";
import { getSettings, setCacheDays, type Settings } from "./api";
import { errorText, useI18n } from "./i18n";
import { GearIcon } from "./icons";

const DAYS = [1, 3, 7, 30, 0]; // 0: never

// the settings, next to the language: where the films are kept, and how long a film that was only streamed stays in the cache
export default function SettingsMenu() {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const ctrl = new AbortController();
    getSettings(ctrl.signal).then(setSettings).catch((e) => e.name !== "AbortError" && setError(errorText(t, e)));
    const away = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    const escape = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", escape);
    return () => {
      ctrl.abort();
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  async function change(days: number) {
    setError(null);
    try {
      setSettings(await setCacheDays(days));
    } catch (e) {
      setError(errorText(t, e));
    }
  }

  return (
    <div className="account settings" ref={box}>
      <button className="account-btn" aria-haspopup="dialog" aria-expanded={open} aria-label={t("settings.title")} title={t("settings.title")} onClick={() => setOpen(!open)}>
        <GearIcon />
      </button>
      {open && (
        <div className="account-menu settings-panel" role="dialog" aria-label={t("settings.title")}>
          <h3>{t("settings.title")}</h3>
          <label className="setting">
            <span>{t("settings.cache")}</span>
            <select value={settings?.cache_days ?? ""} disabled={!settings} onChange={(e) => void change(Number(e.target.value))}>
              {settings && !DAYS.includes(settings.cache_days) && <option value={settings.cache_days}>{t("settings.days", { n: settings.cache_days })}</option>}
              {DAYS.map((d) => <option key={d} value={d}>{d === 0 ? t("settings.never") : t("settings.days", { n: d })}</option>)}
            </select>
            <small>{t("settings.cache.help")}</small>
          </label>
          <div className="setting">
            <span>{t("settings.library")}</span>
            <code>{settings?.library_dir ?? "…"}</code>
            <small>{t("settings.library.help")}</small>
          </div>
          {error && <p className="form-error" role="alert">{error}</p>}
        </div>
      )}
    </div>
  );
}
