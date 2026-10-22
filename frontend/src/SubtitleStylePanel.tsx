import type { PointerEvent } from "react";
import { useI18n } from "./i18n";
import { BACKGROUNDS, boxStyle, COLORS, FONTS, SIZE_KEYS, textStyle, type ColorKey, type FontKey, type SubStyle } from "./subtitleStyle";

const SEGMENT_SIZES = { s: "15px", m: "20px", l: "26px" };

// the opacity in steps: a thin line with a dot per level, the chosen one is bigger
function Levels({ value, min, label, onChange }: { value: number; min: number; label: string; onChange: (v: number) => void }) {
  const levels = Array.from({ length: Math.round((1 - min) / 0.25) + 1 }, (_, i) => min + i * 0.25);
  // the dot follows the pointer (a click, or a drag along the line) and settles on the nearest level
  const pick = (e: PointerEvent<HTMLDivElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const edge = 15; // from the border to the centre of the first and the last dot
    const at = Math.min(1, Math.max(0, (e.clientX - box.left - edge) / (box.width - 2 * edge)));
    const next = levels[Math.round(at * (levels.length - 1))];
    if (e.type === "pointerdown") e.currentTarget.setPointerCapture(e.pointerId);
    if (next !== value) onChange(next);
  };
  return (
    <div className="levels" role="radiogroup" aria-label={label} onPointerDown={pick} onPointerMove={(e) => e.buttons === 1 && pick(e)}>
      {levels.map((v) => (
        <button key={v} role="radio" aria-checked={value === v} aria-label={`${Math.round(v * 100)} %`} title={`${Math.round(v * 100)} %`} className={value === v ? "on" : ""} onClick={() => onChange(v)}><i /></button>
      ))}
    </div>
  );
}

// the look of the subtitles: size, font, color, shadow, background; every change shows at once, on the sample and on the film
export default function SubtitleStylePanel({ style, onChange, onEnter, onLeave }: {
  style: SubStyle;
  onChange: (s: SubStyle) => void;
  onEnter: () => void;
  onLeave: () => void;
}) {
  const { t } = useI18n();
  const set = (changes: Partial<SubStyle>) => onChange({ ...style, ...changes });
  return (
    <div className="tracks substyle" role="dialog" aria-label={t("player.subStyle")} onPointerEnter={onEnter} onPointerLeave={onLeave}>
      <p className="style-sample" style={boxStyle(style)}><span style={textStyle(style)}>{t("style.sample")}</span></p>

      <h3>{t("style.text")}</h3>
      <div className="style-card segments" role="group" aria-label={t("style.text")}>
        {SIZE_KEYS.map((k) => (
          <button key={k} className={style.size === k ? "on" : ""} aria-pressed={style.size === k} style={{ fontSize: SEGMENT_SIZES[k] }} onClick={() => set({ size: k })}>{t(`style.size.${k}`)}</button>
        ))}
      </div>

      <div className="style-card">
        <div className="fonts" role="group" aria-label={t("style.font")}>
          {(Object.keys(FONTS) as FontKey[]).map((k) => (
            <button key={k} className={style.font === k ? "on" : ""} aria-pressed={style.font === k} aria-label={t(`style.font.${k}`)} title={t(`style.font.${k}`)} style={FONTS[k]} onClick={() => set({ font: k })}>
              {k === "caps" ? <>A<small>A</small></> : "Aa"}
            </button>
          ))}
        </div>
        <div className="switch-row">
          <span>{t("style.shadow")}</span>
          <button className={`switch${style.shadow ? " on" : ""}`} role="switch" aria-checked={style.shadow} aria-label={t("style.shadow")} onClick={() => set({ shadow: !style.shadow })}><i /></button>
        </div>
      </div>

      <div className="style-card">
        <div className="swatches" role="group" aria-label={t("style.color")}>
          {(Object.keys(COLORS) as ColorKey[]).map((k) => (
            <button key={k} className={style.color === k ? "on" : ""} aria-pressed={style.color === k} aria-label={t(`style.color.${k}`)} title={t(`style.color.${k}`)} style={{ background: COLORS[k] }} onClick={() => set({ color: k })} />
          ))}
        </div>
        <Levels value={style.opacity} min={0.25} label={t("style.opacity")} onChange={(opacity) => set({ opacity })} />
      </div>

      <h3>{t("style.background")}</h3>
      <div className="style-card">
        <div className="swatches" role="group" aria-label={t("style.background")}>
          {(Object.keys(BACKGROUNDS) as SubStyle["bg"][]).map((k) => (
            <button key={k} className={style.bg === k ? "on" : ""} aria-pressed={style.bg === k} aria-label={t(`style.color.${k}`)} title={t(`style.color.${k}`)} style={{ background: BACKGROUNDS[k] }} onClick={() => set({ bg: k })} />
          ))}
        </div>
        <Levels value={style.bgOpacity} min={0} label={t("style.opacity")} onChange={(bgOpacity) => set({ bgOpacity })} />
      </div>
    </div>
  );
}
