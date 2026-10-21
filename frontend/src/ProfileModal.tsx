import type { User } from "./api";
import { useI18n } from "./i18n";
import ProfilePage from "./ProfilePage";

// a member's profile in a window over the current page (like the movie sheet): no new page, nothing to navigate back from
export default function ProfileModal({ id, me, onUpdate, onClose }: { id: number; me: User; onUpdate: (u: User) => void; onClose: () => void }) {
  const { t } = useI18n();
  return (
    <div className="overlay top" onClick={onClose}>
      <div className="modal narrow" role="dialog" aria-modal="true" aria-label={t("profile.title")} onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose} aria-label={t("modal.close")}>✕</button>
        <ProfilePage id={id} me={me} onUpdate={onUpdate} />
      </div>
    </div>
  );
}
