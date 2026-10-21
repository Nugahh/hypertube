import { useEffect, useRef, useState } from "react";
import type { User } from "./api";
import { useI18n } from "./i18n";
import { Avatar } from "./ProfilePage";

// the member's picture in the header; its menu (Account, Sign out) opens on hover, like Netflix, so signing out stays
// a single click, and on click or tap for a keyboard or a touch screen
export default function AccountMenu({ user, onAccount, onLogout }: { user: User; onAccount: () => void; onLogout: () => void }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const closing = useRef(0);
  // leaving the picture or the menu closes it after a short moment, so a slip of the pointer between them does not
  const enter = () => {
    clearTimeout(closing.current);
    setOpen(true);
  };
  const leave = () => {
    clearTimeout(closing.current);
    closing.current = window.setTimeout(() => setOpen(false), 160);
  };

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

  useEffect(() => () => clearTimeout(closing.current), []);

  const choose = (action: () => void) => () => {
    clearTimeout(closing.current);
    setOpen(false);
    action();
  };

  return (
    <div className="account" ref={box} onMouseEnter={enter} onMouseLeave={leave}>
      <button className="account-btn" aria-haspopup="menu" aria-expanded={open} aria-label={t("menu.aria", { name: user.username })} onClick={() => setOpen(true)}>
        <Avatar user={user} size={32} />
        <span className={`caret${open ? " up" : ""}`} aria-hidden>▾</span>
      </button>
      {open && (
        <div className="account-menu" role="menu">
          <div className="account-who"><Avatar user={user} size={28} /><span>{user.username}</span></div>
          <button role="menuitem" onClick={choose(onAccount)}>{t("menu.account")}</button>
          <button role="menuitem" className="signout" onClick={choose(onLogout)}>{t("menu.signout")}</button>
        </div>
      )}
    </div>
  );
}
