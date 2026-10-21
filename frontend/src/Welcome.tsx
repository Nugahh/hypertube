import { useState, type FormEvent } from "react";
import { updateProfile, type User } from "./api";
import { avatarPath, useDefaultAvatars } from "./avatars";
import { Field, validUsername } from "./AuthPage";
import { errorText, useI18n } from "./i18n";
import { Avatar } from "./ProfilePage";

// shown once per account, right after it is created (sign-up or first 42 / Google login): the picture, then the username
export default function Welcome({ me, onDone, onLogout }: { me: User; onDone: (u: User) => void; onLogout: () => void }) {
  const { t } = useI18n();
  const defaults = useDefaultAvatars();
  const [picked, setPicked] = useState<string | null>(null);
  const [username, setUsername] = useState(me.username);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // the picture the provider gave (42, Google) stays on offer next to the site's own
  const given = me.avatar_url && !me.avatar_url.startsWith("/avatars/") ? me.avatar_url : null;
  const choices = [...(given ? [{ src: given, name: t("welcome.yours") }] : []), ...defaults.map((a) => ({ src: avatarPath(a), name: a.name }))];
  const shown = picked ?? me.avatar_url ?? (defaults.length ? avatarPath(defaults[me.id % defaults.length]) : null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!validUsername(username)) return setError(t("v.username"));
    setBusy(true);
    setError(null);
    try {
      // an uploaded picture is not a URL the backend accepts back: only a changed picture is sent
      onDone(await updateProfile(me.id, { username, avatar_url: shown && shown !== me.avatar_url ? shown : undefined, welcomed: true }));
    } catch (err) {
      setError(errorText(t, err));
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <div className="logo">HYPERTUBE</div>
      <form className="auth-card welcome" onSubmit={submit} noValidate>
        <h1 className="auth-title">{t("welcome.title")}</h1>
        <p className="auth-help">{t("welcome.help")}</p>
        <div className="welcome-pic"><Avatar user={{ id: me.id, username, avatar_url: shown }} size={120} /></div>
        <div className="avatar-picker" role="group" aria-label={t("profile.avatars")}>
          {choices.map((c) => (
            <button type="button" key={c.src} className={shown === c.src ? "on" : ""} aria-pressed={shown === c.src} title={c.name} aria-label={c.name} onClick={() => setPicked(c.src)}>
              <Avatar user={{ id: 0, username: c.name, avatar_url: c.src }} size={44} />
            </button>
          ))}
        </div>
        <Field label={t("auth.username")} autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="btn red" disabled={busy}>{t("welcome.go")}</button>
        <button type="button" className="link" onClick={onLogout}>{t("menu.signout")}</button>
      </form>
    </div>
  );
}
