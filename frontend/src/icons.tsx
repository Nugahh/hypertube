import type { ReactNode } from "react";

// the player's own icons (the browser's built-in controls cannot be extended, so the controls are drawn here)
const icon = (path: ReactNode) => () => (
  <svg viewBox="0 0 24 24" width="26" height="26" fill="currentColor" aria-hidden="true">{path}</svg>
);

export const PlayIcon = icon(<path d="M8 5v14l11-7z" />);
export const PauseIcon = icon(<path d="M6 5h4v14H6zM14 5h4v14h-4z" />);
export const BackIcon = icon(
  <>
    <path d="M12 5V2L7 6l5 4V7a6 6 0 1 1-6 6H4a8 8 0 1 0 8-8z" />
    <text x="12" y="16.5" fontSize="7" fontWeight="700" textAnchor="middle">10</text>
  </>,
);
export const ForwardIcon = icon(
  <>
    <path d="M12 5V2l5 4-5 4V7a6 6 0 1 0 6 6h2a8 8 0 1 1-8-8z" />
    <text x="12" y="16.5" fontSize="7" fontWeight="700" textAnchor="middle">10</text>
  </>,
);
export const VolumeIcon = icon(<path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3A4.5 4.5 0 0 0 14 8v8a4.5 4.5 0 0 0 2.5-4zM14 3.2v2.1a7 7 0 0 1 0 13.4v2.1a9 9 0 0 0 0-17.6z" />);
export const MuteIcon = icon(<path d="M3 9v6h4l5 5V4L7 9H3zm13.6 3-2.6-2.6 1.4-1.4 2.6 2.6 2.6-2.6 1.4 1.4-2.6 2.6 2.6 2.6-1.4 1.4-2.6-2.6-2.6 2.6-1.4-1.4z" />);
export const FullscreenIcon = icon(<path d="M5 5h5v2H7v3H5V5zm9 0h5v5h-2V7h-3V5zM5 14h2v3h3v2H5v-5zm12 0h2v5h-5v-2h3v-3z" />);
export const ExitFullscreenIcon = icon(<path d="M8 5h2v5H5V8h3V5zm6 0h2v3h3v2h-5V5zM5 14h5v5H8v-3H5v-2zm9 0h5v2h-3v3h-2v-5z" />);
export const SubtitlesIcon = icon(<path d="M4 4h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-6l-4 4v-4H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zm2 6v2h5v-2H6zm7 0v2h5v-2h-5zm-7 4v2h3v-2H6zm5 0v2h7v-2h-7z" />);
