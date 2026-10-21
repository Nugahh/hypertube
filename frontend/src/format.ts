import type { Movie } from "./api";

const GRADIENTS = [
  "linear-gradient(160deg,#c0392b,#2b0a0a)",
  "linear-gradient(160deg,#c2561c,#3a1450)",
  "linear-gradient(160deg,#2b5fb8,#0b1630)",
  "linear-gradient(160deg,#6b6b78,#16161d)",
  "linear-gradient(160deg,#5b2a86,#14081f)",
  "linear-gradient(160deg,#8d1c2e,#12060a)",
  "linear-gradient(160deg,#a8863a,#2a1f0b)",
];

// stable colour per movie: shown under the cover, and alone when there is no cover
export const gradient = (id: number) => GRADIENTS[id % GRADIENTS.length];
export const poster = (m: Movie) => ({ backgroundImage: `${m.cover ? `url(${m.cover}), ` : ""}${gradient(m.id)}` });

export const formatSize = (n: number) =>
  n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n >= 1e6 ? `${Math.round(n / 1e6)} MB` : `${Math.max(1, Math.round(n / 1e3))} kB`;
export const initials = (name: string) => name.split(" ").map((w) => w[0]).join("").slice(0, 2).toUpperCase();
export const meta = (m: Movie) => [m.year, m.resolution, formatSize(m.size)].filter(Boolean).join(" · ");
