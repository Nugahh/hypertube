import { useState, type ChangeEvent, type FormEvent } from "react";
import { createClient, deleteClient, getUser, listClients, updateProfile, uploadAvatar, type NewApiClient, type PublicUser, type User } from "./api";
import { avatarPath, useDefaultAvatars } from "./avatars";
import { Field, validUsername } from "./AuthPage";
import { errorText, LANGS, useI18n } from "./i18n";
import { useApi } from "./useApi";

export function Avatar({ user, size = 36 }: { user: Pick<PublicUser, "id" | "avatar_url" | "username">; size?: number }) {
  const defaults = useDefaultAvatars();
  const src = user.avatar_url ?? (defaults.length ? avatarPath(defaults[user.id % defaults.length]) : null);
  // a class emblem is a transparent cut-out: it is drawn on a dark disc (an uploaded photo fills the circle)
  if (src?.startsWith("/avatars/"))
    return <span className="avatar emblem" style={{ width: size, height: size, backgroundImage: `url(${src})` }} aria-hidden />;
  return src ? (
    <img className="avatar" src={src} alt="" width={size} height={size} />
  ) : (
    <span className="avatar" style={{ width: size, height: size, fontSize: size * 0.42 }} aria-hidden>
      {user.username[0]?.toUpperCase()}
    </span>
  );
}

const MAX_AVATAR = 2 * 1024 * 1024; // same limit as the backend

function OwnProfile({ me, onUpdate }: { me: User; onUpdate: (u: User) => void }) {
  const { t } = useI18n();
  const [form, setForm] = useState({ username: me.username, email: me.email, first_name: me.first_name, last_name: me.last_name, language: me.language });
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const defaults = useDefaultAvatars();
  const set = (key: keyof typeof form) => (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm({ ...form, [key]: e.target.value });

  async function run(action: () => Promise<User>) {
    setBusy(true);
    setMessage(null);
    try {
      onUpdate(await action());
      setMessage({ ok: true, text: t("profile.saved") });
    } catch (err) {
      setMessage({ ok: false, text: errorText(t, err) });
    }
    setBusy(false);
  }

  const save = (e: FormEvent) => {
    e.preventDefault();
    if (!validUsername(form.username)) return setMessage({ ok: false, text: t("v.username") });
    return run(() => updateProfile(me.id, form));
  };

  const pick = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // lets the same file be picked again
    if (!file) return;
    if (file.size > MAX_AVATAR) return setMessage({ ok: false, text: errorText(t, { status: 413 }) });
    return run(() => uploadAvatar(file));
  };

  return (
    <form className="profile-card" onSubmit={save}>
      <div className="profile-head">
        <Avatar user={me} size={96} />
        <div>
          <h1>{me.username}</h1>
          <label className="btn-link file">
            {t("profile.picture.change")}
            <input type="file" accept="image/jpeg,image/png,image/webp" onChange={pick} hidden />
          </label>
        </div>
      </div>
      {defaults.length > 0 && (
        <div className="avatar-picker" role="group" aria-label={t("profile.avatars")}>
          <span className="picker-title">{t("profile.avatars")}</span>
          {defaults.map((a) => (
            <button
              type="button"
              key={a.file}
              className={me.avatar_url === avatarPath(a) ? "on" : ""}
              aria-pressed={me.avatar_url === avatarPath(a)}
              title={a.name}
              aria-label={a.name}
              disabled={busy}
              onClick={() => run(() => updateProfile(me.id, { avatar_url: avatarPath(a) }))}
            >
              <Avatar user={{ id: 0, username: a.name, avatar_url: avatarPath(a) }} size={44} />
            </button>
          ))}
        </div>
      )}
      <Field label={t("auth.username")} autoComplete="username" value={form.username} onChange={set("username")} />
      <Field label={t("auth.email")} type="email" autoComplete="email" value={form.email} onChange={set("email")} />
      <div className="field-row">
        <Field label={t("auth.first")} autoComplete="given-name" value={form.first_name} onChange={set("first_name")} />
        <Field label={t("auth.last")} autoComplete="family-name" value={form.last_name} onChange={set("last_name")} />
      </div>
      <label className="field">
        <span>{t("profile.language")}</span>
        <select value={form.language} onChange={set("language")}>
          {LANGS.map((l) => <option key={l} value={l}>{t(`lang.${l}`)}</option>)}
        </select>
      </label>
      {message && <p className={message.ok ? "form-ok" : "form-error"} role={message.ok ? "status" : "alert"}>{message.text}</p>}
      <button className="btn red" disabled={busy}>{t("profile.save")}</button>
    </form>
  );
}

// credentials for programs: POST /api/oauth/token with the client id and secret returns a Bearer token for the API
function ApiAccess() {
  const { t } = useI18n();
  const [round, setRound] = useState(0);
  const [name, setName] = useState("");
  const [created, setCreated] = useState<NewApiClient | null>(null);
  const [error, setError] = useState<string | null>(null);
  const clients = useApi(listClients, [], [round]);

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      setRound((n) => n + 1);
    } catch (err) {
      setError(errorText(t, err));
    }
  }

  return (
    <section className="profile-card api-card" aria-label={t("api.title")}>
      <h2>{t("api.title")}</h2>
      <p className="auth-help">{t("api.help")}</p>
      <ul className="clients">
        {clients.data.map((c) => (
          <li key={c.id}>
            <span><b>{c.name}</b> <code>{c.client_id}</code></span>
            <button className="link-small" onClick={() => run(() => deleteClient(c.id))}>{t("api.delete")}</button>
          </li>
        ))}
      </ul>
      {!clients.loading && clients.data.length === 0 && <p className="notice">{t("api.none")}</p>}
      {created && (
        <div className="secret" role="status">
          <p>{t("api.secret")}</p>
          <code>{created.client_id}</code>
          <code>{created.client_secret}</code>
        </div>
      )}
      <form
        className="field-row"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) run(async () => { setCreated(await createClient(name)); setName(""); });
        }}
      >
        <label className="field">
          <span>{t("api.name")}</span>
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={50} />
        </label>
        <button className="btn-link" disabled={!name.trim()}>{t("api.create")}</button>
      </form>
      {error && <p className="form-error" role="alert">{error}</p>}
    </section>
  );
}

// own profile: editable. Someone else's: name and picture only (the email stays private, server side).
// It is shown in a window over the page (ProfileModal), not as a page of its own.
export default function ProfilePage({ id, me, onUpdate }: { id: number; me: User; onUpdate: (u: User) => void }) {
  const { t } = useI18n();
  const own = id === me.id;
  const other = useApi<PublicUser | null>((signal) => (own ? Promise.resolve(null) : getUser(id, signal)), null, [id, own]);

  return (
    <section className="profile">
        {own ? (
          <>
            <OwnProfile me={me} onUpdate={onUpdate} />
            <ApiAccess />
          </>
        ) : other.error ? (
          <p className="notice" role="alert">{t("profile.notfound")}</p>
        ) : other.data ? (
          <div className="profile-card">
            <div className="profile-head">
              <Avatar user={other.data} size={96} />
              <div>
                <h1>{other.data.username}</h1>
                <p className="notice">{other.data.first_name} {other.data.last_name}</p>
              </div>
            </div>
          </div>
        ) : (
          <p className="notice">{t("loading")}</p>
        )}
    </section>
  );
}
