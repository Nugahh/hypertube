import { useState, type FormEvent } from "react";
import { resetPassword } from "./api";
import { Field, LangSwitch, validPassword } from "./AuthPage";
import { errorText, useI18n } from "./i18n";

// opened from the link in the password-reset email: /reset-password?token=…
export default function ResetPage({ token, onDone }: { token: string; onDone: () => void }) {
  const { t } = useI18n();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(token ? null : t("reset.missing"));
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!validPassword(password)) return setError(t("v.password"));
    if (password !== confirm) return setError(t("v.mismatch"));
    setBusy(true);
    setError(null);
    try {
      await resetPassword(token, password);
      onDone();
    } catch (err) {
      setError(errorText(t, err));
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <LangSwitch />
      <div className="logo">HYPERTUBE</div>
      <form className="auth-card" onSubmit={submit} noValidate>
        <h1 className="auth-title">{t("reset.title")}</h1>
        <Field label={t("auth.password")} type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        <Field label={t("auth.confirm")} type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="btn red" disabled={busy || !token}>{t("reset.submit")}</button>
        <button type="button" className="link" onClick={onDone}>{t("auth.back")}</button>
      </form>
    </div>
  );
}
