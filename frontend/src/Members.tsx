import { listUsers } from "./api";
import { errorText, useI18n } from "./i18n";
import { Avatar } from "./ProfilePage";
import { useApi } from "./useApi";

// every member; a click opens their public profile (picture and name, never the email)
export default function Members({ onOpen }: { onOpen: (id: number) => void }) {
  const { t } = useI18n();
  const users = useApi(listUsers, [], []);
  return (
    <main>
      <section className="row">
        <h2>{t("members.title")}</h2>
        {users.error ? <p className="notice" role="alert">{errorText(t, users.error)}</p> : null}
        {users.loading && <p className="notice">{t("loading")}</p>}
        <ul className="members">
          {users.data.map((u) => (
            <li key={u.id}>
              <button className="member" onClick={() => onOpen(u.id)}>
                <Avatar user={{ id: u.id, username: u.username, avatar_url: null }} size={40} />
                <span>{u.username}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
