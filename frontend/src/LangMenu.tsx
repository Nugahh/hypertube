import { useEffect, useRef, useState } from "react";
import { LANGS, useI18n, type Lang } from "./i18n";
import { FlagEN, FlagFR } from "./logos";

const FLAGS: Record<Lang, () => JSX.Element> = { en: FlagEN, fr: FlagFR };

// the language of the site, next to the account: the current flag, and a menu with the others
export default function LangMenu({ onPick }: { onPick: (l: Lang) => void }) {
  const { lang, t } = useI18n();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    const escape = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);
  const Flag = FLAGS[lang];
  return (
    <div className="account lang" ref={box}>
      <button className="account-btn" aria-haspopup="menu" aria-expanded={open} aria-label={t("lang.change")} title={t("lang.change")} onClick={() => setOpen(!open)}>
        <Flag />
        <span className={`caret${open ? " up" : ""}`} aria-hidden>▾</span>
      </button>
      {open && (
        <div className="account-menu" role="menu">
          {LANGS.map((l) => {
            const F = FLAGS[l];
            return (
              <button key={l} role="menuitemradio" aria-checked={l === lang} aria-label={t(`lang.${l}`)} title={t(`lang.${l}`)} className="lang-item" onClick={() => { setOpen(false); onPick(l); }}>
                <F />
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
