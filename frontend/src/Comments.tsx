import { useState, type FormEvent } from "react";
import { deleteComment, editComment, getComments, postComment, type MovieComment, type User } from "./api";
import { errorText, useI18n } from "./i18n";
import { Avatar } from "./ProfilePage";
import { useApi } from "./useApi";

const MAX = 1000; // same limit as the backend

function CommentForm({ initial = "", submit, cancel, label }: { initial?: string; submit: (text: string) => Promise<void>; cancel?: () => void; label: string }) {
  const { t } = useI18n();
  const [text, setText] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await submit(text);
      if (!initial) setText("");
    } catch (err) {
      setError(errorText(t, err));
    }
    setBusy(false);
  }

  return (
    <form className="comment-form" onSubmit={onSubmit}>
      <textarea value={text} onChange={(e) => setText(e.target.value)} maxLength={MAX} rows={initial ? 3 : 2} placeholder={t("comments.placeholder")} aria-label={t("comments.placeholder")} />
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="comment-actions">
        <button className="btn-link" disabled={busy || !text.trim()}>{label}</button>
        {cancel && <button type="button" className="btn-link" onClick={cancel}>{t("comments.cancel")}</button>}
      </div>
    </form>
  );
}

// the comments of a movie: anyone logged in reads and posts, the author edits and deletes (the server checks it too)
export default function Comments({ movieId, me, onProfile }: { movieId: number; me: User; onProfile: (id: number) => void }) {
  const { t, lang } = useI18n();
  const [round, setRound] = useState(0);
  const [editing, setEditing] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const list = useApi<MovieComment[]>((signal) => getComments(movieId, signal), [], [movieId, round]);
  const reload = () => setRound((n) => n + 1);

  async function remove(c: MovieComment) {
    setError(null);
    try {
      await deleteComment(c.id);
      reload();
    } catch (err) {
      setError(errorText(t, err));
    }
  }

  return (
    <section className="comments" aria-label={t("comments.title", { n: list.data.length })}>
      <h3>{t("comments.title", { n: list.data.length })}</h3>
      <CommentForm
        label={t("comments.post")}
        submit={async (text) => {
          await postComment(movieId, text);
          reload();
        }}
      />
      {error && <p className="form-error" role="alert">{error}</p>}
      {list.error ? <p className="form-error" role="alert">{errorText(t, list.error)}</p> : null}
      {!list.loading && !list.error && list.data.length === 0 && <p className="notice">{t("comments.empty")}</p>}
      <ul>
        {list.data.map((c) => (
          <li key={c.id} className="comment">
            <Avatar user={{ id: c.user_id, username: c.username, avatar_url: c.avatar_url }} size={32} />
            <div className="comment-main">
              <div className="comment-head">
                <button className="comment-author" onClick={() => onProfile(c.user_id)}>{c.username}</button>
                <time dateTime={c.date}>{new Date(c.date).toLocaleDateString(lang)}</time>
                {c.edited && <span className="notice">({t("comments.edited")})</span>}
              </div>
              {editing === c.id ? (
                <CommentForm
                  initial={c.content}
                  label={t("comments.save")}
                  cancel={() => setEditing(null)}
                  submit={async (text) => {
                    await editComment(c.id, text);
                    setEditing(null);
                    reload();
                  }}
                />
              ) : (
                <p className="comment-text">{c.content}</p>
              )}
              {c.user_id === me.id && editing !== c.id && (
                <div className="comment-actions">
                  <button className="link-small" onClick={() => setEditing(c.id)}>{t("comments.edit")}</button>
                  <button className="link-small" onClick={() => remove(c)}>{t("comments.delete")}</button>
                </div>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
