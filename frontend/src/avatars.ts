import { useEffect, useState } from "react";

// the site's own pictures, listed in /avatars/index.json (see public/avatars/README.txt): the picker offers them, and
// a member who has not uploaded a picture gets one of them, always the same
export type DefaultAvatar = { file: string; name: string };

let cache: DefaultAvatar[] | null = null;
let loading: Promise<DefaultAvatar[]> | null = null;

const load = () =>
  (loading ??= fetch("/avatars/index.json")
    .then((r) => (r.ok ? r.json() : []))
    .catch(() => [])
    .then((list: DefaultAvatar[]) => (cache = Array.isArray(list) ? list : [])));

export function useDefaultAvatars() {
  const [list, setList] = useState<DefaultAvatar[]>(cache ?? []);
  useEffect(() => {
    if (cache === null) void load().then(setList);
  }, []);
  return list;
}

export const avatarPath = (a: DefaultAvatar) => `/avatars/${a.file}`;
