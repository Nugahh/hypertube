import type { CSSProperties } from "react";

// how the subtitles look: kept in this browser, like the volume of a player
export type FontKey = "monoserif" | "serif" | "monosans" | "sans" | "casual" | "caps";
export type ColorKey = "white" | "black" | "blue" | "cyan" | "green" | "yellow" | "red" | "purple";
export type SubStyle = {
  size: "s" | "m" | "l";
  font: FontKey;
  shadow: boolean;
  color: ColorKey;
  opacity: number; // of the text, 0.25 to 1
  bg: "white" | "black";
  bgOpacity: number; // of the background, 0 (none) to 1
};

export const DEFAULT_STYLE: SubStyle = { size: "m", font: "sans", shadow: true, color: "white", opacity: 1, bg: "black", bgOpacity: 0 };
export const SIZE_KEYS: SubStyle["size"][] = ["s", "m", "l"];
export const COLORS: Record<ColorKey, string> = {
  white: "#ffffff", black: "#000000", blue: "#3f5fc7", cyan: "#70dbd4", green: "#9ad84a", yellow: "#f9d14e", red: "#c42b21", purple: "#a83ab0",
};
export const BACKGROUNDS: Record<SubStyle["bg"], string> = { white: "#ffffff", black: "#000000" };
// the six families every player offers: monospaced and proportional serif, monospaced and proportional sans, casual, small capitals
export const FONTS: Record<FontKey, CSSProperties> = {
  monoserif: { fontFamily: '"Courier New", Courier, monospace' },
  serif: { fontFamily: 'Georgia, "Times New Roman", serif' },
  monosans: { fontFamily: 'ui-monospace, Menlo, Consolas, "Lucida Console", monospace' },
  sans: { fontFamily: 'system-ui, "Helvetica Neue", Arial, sans-serif' },
  casual: { fontFamily: '"Comic Sans MS", "Segoe Print", "Chalkboard SE", "Marker Felt", cursive' },
  caps: { fontFamily: 'system-ui, "Helvetica Neue", Arial, sans-serif', fontVariant: "small-caps" },
};

const SIZES = { s: "clamp(14px,2vw,26px)", m: "clamp(18px,2.6vw,34px)", l: "clamp(24px,3.4vw,46px)" };
const SHADOW = "0 0 4px #000,0 0 4px #000,0 2px 6px #000";

const rgba = (hex: string, alpha: number) => {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${alpha})`;
};

export function loadStyle(): SubStyle {
  try {
    const saved = JSON.parse(localStorage.getItem("subStyle") ?? "{}");
    const among = <T extends string>(value: unknown, allowed: readonly T[], fallback: T): T => (allowed.includes(value as T) ? (value as T) : fallback);
    const level = (value: unknown, min: number, fallback: number) => (typeof value === "number" && value >= min && value <= 1 ? value : fallback);
    return {
      size: among(saved.size, SIZE_KEYS, DEFAULT_STYLE.size),
      font: among(saved.font, Object.keys(FONTS) as FontKey[], DEFAULT_STYLE.font),
      shadow: typeof saved.shadow === "boolean" ? saved.shadow : DEFAULT_STYLE.shadow,
      color: among(saved.color, Object.keys(COLORS) as ColorKey[], DEFAULT_STYLE.color),
      opacity: level(saved.opacity, 0.25, DEFAULT_STYLE.opacity),
      bg: among(saved.bg, ["white", "black"] as const, DEFAULT_STYLE.bg),
      bgOpacity: level(saved.bgOpacity, 0, DEFAULT_STYLE.bgOpacity),
    };
  } catch {
    return DEFAULT_STYLE; // no storage (private window) or something else in the slot
  }
}

export function saveStyle(style: SubStyle) {
  try {
    localStorage.setItem("subStyle", JSON.stringify(style));
  } catch {
    /* kept for this session only */
  }
}

// the paragraph carries the size, the text inside it the rest (a background that follows each line)
export const boxStyle = (s: SubStyle): CSSProperties => ({ fontSize: SIZES[s.size] });
export const textStyle = (s: SubStyle): CSSProperties => ({
  ...FONTS[s.font],
  color: rgba(COLORS[s.color], s.opacity),
  background: s.bgOpacity > 0 ? rgba(BACKGROUNDS[s.bg], s.bgOpacity) : "transparent",
  textShadow: s.shadow ? SHADOW : "none",
  padding: s.bgOpacity > 0 ? "0.05em 0.4em" : 0,
  borderRadius: 4,
  boxDecorationBreak: "clone",
  WebkitBoxDecorationBreak: "clone",
});
