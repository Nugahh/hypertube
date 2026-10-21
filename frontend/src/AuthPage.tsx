import { useState, type ChangeEvent, type FormEvent } from "react";
import { forgotPassword, login, register, type User } from "./api";
import { errorText, LANGS, useI18n } from "./i18n";
import { Logo42, LogoGoogle } from "./logos";

type Mode = "login" | "register" | "forgot";
type Form = { email: string; username: string; first_name: string; last_name: string; password: string; confirm: string };

const EMPTY: Form = { email: "", username: "", first_name: "", last_name: "", password: "", confirm: "" };

export const validPassword = (p: string) => p.length >= 8 && /[a-zA-Z]/.test(p) && /\d/.test(p);

export function Field(p: { label: string; value: string; onChange: (e: ChangeEvent<HTMLInputElement>) => void; type?: string; autoComplete?: string }) {
  return (
    <label className="field">
      <span>{p.label}</span>
      <input type={p.type ?? "text"} value={p.value} onChange={p.onChange} autoComplete={p.autoComplete} required maxLength={128} />
    </label>
  );
}

// English / French switch for visitors (members choose in their profile)
export function LangSwitch() {
  const { lang, setLang, t } = useI18n();
  return (
    <div className="auth-lang" role="group">
      {LANGS.map((l) => (
        <button key={l} className={l === lang ? "on" : ""} aria-pressed={l === lang} onClick={() => setLang(l)}>
          {t(`lang.${l}`)}
        </button>
      ))}
    </div>
  );
}

const OAUTH = [["42", "42", Logo42], ["google", "Google", LogoGoogle]] as const;

export default function AuthPage({ onAuth, notice, error: initialError }: { onAuth: (u: User) => void; notice?: string; error?: string }) {
  const { t } = useI18n();
  const [mode, setMode] = useState<Mode>("login");
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState<string | null>(initialError ?? null);
  const [info, setInfo] = useState<string | null>(notice ?? null);
  const [busy, setBusy] = useState(false);
  const set = (key: keyof Form) => (e: ChangeEvent<HTMLInputElement>) => setForm({ ...form, [key]: e.target.value });
  const go = (m: Mode) => { setMode(m); setError(null); setInfo(null); };

  // same rules as the backend, so most mistakes are caught before the request
  function validate(): string | null {
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(form.email)) return t("v.email");
    if (mode === "forgot") return null;
    if (!/^[a-zA-Z0-9_]{3,30}$/.test(form.username)) return t("v.username");
    if (!form.first_name.trim() || !form.last_name.trim()) return t("v.names");
    if (!validPassword(form.password)) return t("v.password");
    if (form.password !== form.confirm) return t("v.mismatch");
    return null;
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const problem = mode === "login" ? null : validate();
    if (problem) return setError(problem);
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      if (mode === "forgot") {
        await forgotPassword(form.email);
        setInfo(t("auth.forgot.sent"));
      } else {
        const { confirm: _confirm, ...data } = form;
        onAuth(mode === "login" ? await login(form.username, form.password) : await register(data));
        return;
      }
    } catch (err) {
      setError(errorText(t, err));
    }
    setBusy(false);
  }

  return (
    <div className="auth">
      <LangSwitch />
      <div className="logo">HYPERTUBE</div>
      <form className="auth-card" onSubmit={submit} noValidate>
        {mode === "forgot" ? (
          <>
            <h1 className="auth-title">{t("auth.forgot")}</h1>
            <p className="auth-help">{t("auth.forgot.help")}</p>
            <Field label={t("auth.email")} type="email" autoComplete="email" value={form.email} onChange={set("email")} />
          </>
        ) : (
          <>
            <div className="auth-tabs" role="tablist">
              {(["login", "register"] as const).map((m) => (
                <button type="button" key={m} role="tab" aria-selected={mode === m} className={mode === m ? "on" : ""} onClick={() => go(m)}>
                  {t(`auth.${m}`)}
                </button>
              ))}
            </div>
            {mode === "register" && <Field label={t("auth.email")} type="email" autoComplete="email" value={form.email} onChange={set("email")} />}
            <Field label={t("auth.username")} autoComplete="username" value={form.username} onChange={set("username")} />
            {mode === "register" && (
              <div className="field-row">
                <Field label={t("auth.first")} autoComplete="given-name" value={form.first_name} onChange={set("first_name")} />
                <Field label={t("auth.last")} autoComplete="family-name" value={form.last_name} onChange={set("last_name")} />
              </div>
            )}
            <Field label={t("auth.password")} type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} value={form.password} onChange={set("password")} />
            {mode === "register" && <Field label={t("auth.confirm")} type="password" autoComplete="new-password" value={form.confirm} onChange={set("confirm")} />}
          </>
        )}
        {error && <p className="form-error" role="alert">{error}</p>}
        {info && <p className="form-ok" role="status">{info}</p>}
        <button className="btn red" disabled={busy}>
          {t(mode === "forgot" ? "auth.forgot.send" : `auth.submit.${mode}`)}
        </button>
        {mode === "login" && <button type="button" className="link" onClick={() => go("forgot")}>{t("auth.forgot")}</button>}
        {mode === "forgot" && <button type="button" className="link" onClick={() => go("login")}>{t("auth.back")}</button>}
        {mode !== "forgot" && (
          <>
            <div className="auth-or">{t("auth.or")}</div>
            {/* plain links: the whole page goes to the provider and comes back signed in */}
            <div className="oauth">
              {OAUTH.map(([id, label, Logo]) => (
                <a key={id} className="btn-link" href={`/api/auth/${id}/login`}>
                  <Logo />
                  {t("auth.with", { provider: label })}
                </a>
              ))}
            </div>
          </>
        )}
      </form>
    </div>
  );
}
