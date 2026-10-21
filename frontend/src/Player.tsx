import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { getAudio, saveProgress, streamUrl, subtitleUrl, type AudioTrack, type Movie, type MovieDetails } from "./api";
import { clock, formatSize } from "./format";
import { useI18n } from "./i18n";
import { BackIcon, ExitFullscreenIcon, ForwardIcon, FullscreenIcon, MuteIcon, PauseIcon, PlayIcon, SubtitlesIcon, VolumeIcon } from "./icons";
import TracksPanel from "./TracksPanel";
import { useApi } from "./useApi";

const SKIP = 10; // seconds
const entities: Record<string, string> = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&nbsp;": " " };
// a cue's text as plain text: no markup (<i>, <c.yellow>…), a few entities decoded; React escapes it when it is drawn
const plain = (cue: string) => cue.replace(/<[^>]+>/g, "").replace(/&(amp|lt|gt|nbsp);/g, (e) => entities[e]);

// the video takes the whole window, with our own controls: the browser's built-in bar cannot hold an
// "Audio & subtitles" button. The controls fade after a few seconds without activity, unless it is paused.
export default function Player({ movie, details, resumeAt = 0, onBack, onChanged }: {
  movie: Movie;
  details: MovieDetails | null;
  resumeAt?: number; // seconds: where the member stopped last time
  onBack: () => void;
  onChanged: () => void;
}) {
  const { t, lang } = useI18n();
  const box = useRef<HTMLDivElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const [failed, setFailed] = useState(false);
  const [started, setStarted] = useState(false);
  const [idle, setIdle] = useState(false);
  const [paused, setPaused] = useState(true);
  const [time, setTime] = useState(0);
  const [length, setLength] = useState(0);
  const [buffered, setBuffered] = useState(0);
  const [volume, setVolume] = useState(1);
  const [muted, setMuted] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [panel, setPanel] = useState(false);
  const [opened, setOpened] = useState(false); // the audio tracks are only looked up once the panel was opened
  const [sub, setSub] = useState<string | null | undefined>(undefined); // undefined: the automatic choice
  const from = resumeAt > 5 ? Math.floor(resumeAt) : 0; // a few seconds in is not worth a jump
  const [audio, setAudio] = useState({ index: 0, start: from }); // a converted stream starts there
  const [cue, setCue] = useState("");
  const seekTo = useRef(from); // a file the browser plays as it is jumps there once it is loaded

  const tracks = useApi<AudioTrack[] | null>((signal) => (opened ? getAudio(movie.id, signal) : Promise.resolve(null)), null, [movie.id, opened]);
  const subs = details?.subtitles ?? [];
  const original = details?.language ?? "en"; // most films are in English when TMDb does not say
  // the member's language is shown by default, unless it is the language the film was made in
  const automatic = lang !== original ? subs.find((s) => s.lang === lang)?.ref ?? null : null;
  const selected = sub === undefined ? automatic : sub;

  // another audio track goes through the converter, which restarts the film where it was and cannot seek: then the
  // times shown are the film's (the stream's time plus where it started) and the seek bar is off
  const native = details?.native !== false;
  const converted = !native || audio.index > 0;
  const src = converted ? streamUrl(movie.id, audio.index, audio.start) : streamUrl(movie.id);
  const offset = converted ? audio.start : 0;
  const seekable = !converted && Number.isFinite(length) && length > 0;
  // a converted stream only knows what it has produced so far: the length is TMDb's runtime, or not shown
  const total = seekable ? length : details?.runtime ? details.runtime * 60 : 0;
  const position = offset + time;
  const live = useRef({ converted, offset });
  live.current = { converted, offset };

  // where the member is goes to the server every 10 s while playing, and when the player closes ("continue watching")
  const where = useRef({ id: movie.id, position: 0, total: 0, playing: false });
  where.current = { id: movie.id, position, total, playing: !paused };
  useEffect(() => {
    const report = () => {
      const w = where.current;
      if (w.total > 0 && w.position > 5) saveProgress(w.id, w.position, w.total).catch(() => {});
    };
    const timer = setInterval(() => where.current.playing && report(), 10000);
    return () => {
      clearInterval(timer);
      report();
    };
  }, [movie.id]);

  function toggle() {
    const v = video.current;
    if (!v) return;
    if (v.paused) v.play().catch(() => {}); // a play() the browser refuses is not an error worth showing
    else v.pause();
  }
  function skip(seconds: number) {
    const v = video.current;
    if (v && !live.current.converted && Number.isFinite(v.duration)) v.currentTime = Math.min(Math.max(v.currentTime + seconds, 0), v.duration);
  }
  function setVolumeTo(x: number) {
    const v = video.current;
    if (!v) return;
    v.volume = Math.min(Math.max(x, 0), 1);
    v.muted = v.volume === 0;
  }
  // after a mouse click the focus goes back to the page, so Space pauses; a keyboard press keeps its focus
  const press = (action: () => void) => (e: React.MouseEvent<HTMLButtonElement>) => {
    action();
    if (e.detail > 0) e.currentTarget.blur();
  };
  const toggleFullscreen = () => (document.fullscreenElement ? document.exitFullscreen() : box.current?.requestFullscreen());

  useEffect(() => {
    document.body.style.overflow = "hidden"; // no page scrollbar beside the video
    const onFullscreen = () => setFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", onFullscreen);
    return () => {
      document.body.style.overflow = "";
      document.removeEventListener("fullscreenchange", onFullscreen);
      if (document.fullscreenElement) void document.exitFullscreen();
    };
  }, []);

  useEffect(() => {
    let timer = 0;
    const wake = () => {
      setIdle(false);
      clearTimeout(timer);
      timer = window.setTimeout(() => setIdle(true), 3000);
    };
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (e.key === "Escape") {
        // closes the panel first, then goes back to the movie sheet instead of closing everything
        e.stopPropagation();
        return panel ? setPanel(false) : onBack();
      }
      wake();
      if (target.closest("input, select, textarea")) return; // typing or choosing in the panel
      const onButton = !!target.closest("button");
      switch (e.key) {
        case " ":
        case "k":
          if (!onButton) {
            e.preventDefault();
            toggle();
          }
          break;
        case "ArrowLeft":
          return skip(-SKIP);
        case "ArrowRight":
          return skip(SKIP);
        case "ArrowUp":
          e.preventDefault();
          return setVolumeTo((video.current?.volume ?? 1) + 0.1);
        case "ArrowDown":
          e.preventDefault();
          return setVolumeTo((video.current?.volume ?? 1) - 0.1);
        case "m":
          if (video.current) video.current.muted = !video.current.muted;
          break;
        case "f":
          void toggleFullscreen();
      }
    };
    wake();
    window.addEventListener("mousemove", wake);
    window.addEventListener("keydown", onKey, true);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("mousemove", wake);
      window.removeEventListener("keydown", onKey, true);
    };
  }, [onBack, panel]);

  // the chosen subtitle track is loaded but not drawn by the browser: we draw it (above the controls, and shifted
  // by where a converted stream started), the others are off. The tracks are in the same order as `subs`.
  const key = subs.map((s) => s.ref).join();
  useEffect(() => {
    const v = video.current;
    if (!v) return;
    const want = subs.findIndex((s) => s.ref === selected);
    const apply = () => [...v.textTracks].forEach((track, i) => (track.mode = i === want ? "hidden" : "disabled"));
    const draw = () => {
      const cues = want >= 0 ? v.textTracks[want]?.cues : null;
      const at = live.current.offset + v.currentTime;
      const now = cues ? [...cues].filter((c) => at >= c.startTime && at < c.endTime).map((c) => plain((c as VTTCue).text)) : [];
      setCue(now.join("\n"));
    };
    apply();
    v.textTracks.addEventListener("addtrack", apply);
    const timer = setInterval(draw, 250);
    return () => {
      v.textTracks.removeEventListener("addtrack", apply);
      clearInterval(timer);
      setCue("");
    };
  }, [key, selected]);

  function chooseAudio(index: number) {
    if (index === audio.index) return;
    const at = Math.floor(position); // the position in the film, whatever stream it comes from
    seekTo.current = native && index === 0 ? at : 0; // the original file can seek: no need to restart the stream
    setAudio({ index, start: native && index === 0 ? 0 : at });
    setStarted(false);
  }

  const status = failed
    ? t("player.error")
    : details?.state === "ready"
      ? t("player.ready")
      : details && details.progress > 0
        ? t("player.downloading", { pct: Math.round(details.progress * 100), peers: details.peers, speed: formatSize(details.rate) })
        : t("player.waiting");
  const pct = (x: number) => `${total ? Math.min(100, (x / total) * 100) : 0}%`;
  const hidden = idle && started && !failed && !panel && !paused;

  return (
    <div ref={box} className={`player${hidden ? " idle" : ""}`} role="dialog" aria-modal="true" aria-label={movie.title}>
      {/* the browser asks the server for ranges of the file: playback starts as soon as the first pieces are there */}
      <video
        ref={video}
        src={src}
        autoPlay
        playsInline
        onClick={toggle}
        onDoubleClick={() => void toggleFullscreen()}
        onPlay={() => setPaused(false)}
        onPause={() => setPaused(true)}
        onPlaying={() => setStarted(true)}
        onWaiting={() => setStarted(false)}
        onTimeUpdate={(e) => {
          setTime(e.currentTarget.currentTime);
          const b = e.currentTarget.buffered;
          setBuffered(b.length ? b.end(b.length - 1) : 0);
        }}
        onDurationChange={(e) => setLength(e.currentTarget.duration)}
        onVolumeChange={(e) => {
          setVolume(e.currentTarget.volume);
          setMuted(e.currentTarget.muted);
        }}
        onLoadedMetadata={(e) => {
          const v = e.currentTarget;
          // a converted stream already starts at the right place (its URL says where), and the end is not a place to resume
          if (seekTo.current && !live.current.converted && (!Number.isFinite(v.duration) || seekTo.current < v.duration - 5)) v.currentTime = seekTo.current;
          seekTo.current = 0;
        }}
        onError={() => setFailed(true)}
      >
        {subs.map((s) => (
          <track key={s.ref} kind="subtitles" srcLang={s.lang} label={s.label} src={subtitleUrl(movie.id, s.ref)} />
        ))}
      </video>

      {cue && <p className="subtitle" aria-live="off">{cue}</p>}

      <div className="player-bar">
        <button className="back" onClick={onBack} aria-label={t("player.back")}>←</button>
        <span className="player-title">{movie.title}</span>
      </div>

      <div className="player-controls">
        <input
          type="range"
          className="seek"
          min={0}
          max={total || 1}
          step={0.5}
          value={total ? Math.min(position, total) : 0}
          disabled={!seekable}
          onChange={(e: ChangeEvent<HTMLInputElement>) => video.current && (video.current.currentTime = Number(e.target.value))}
          style={{ "--played": pct(position), "--buffered": pct(offset + buffered) } as React.CSSProperties}
          aria-label={t("player.seek")}
          aria-valuetext={clock(position)}
        />
        <div className="controls-row">
          <button className="ctl" onClick={press(toggle)} aria-label={paused ? t("player.play") : t("player.pause")}>{paused ? <PlayIcon /> : <PauseIcon />}</button>
          <button className="ctl" onClick={press(() => skip(-SKIP))} disabled={!seekable} aria-label={t("player.back10")}><BackIcon /></button>
          <button className="ctl" onClick={press(() => skip(SKIP))} disabled={!seekable} aria-label={t("player.forward10")}><ForwardIcon /></button>
          <button className="ctl" onClick={press(() => video.current && (video.current.muted = !video.current.muted))} aria-label={muted ? t("player.unmute") : t("player.mute")}>
            {muted || volume === 0 ? <MuteIcon /> : <VolumeIcon />}
          </button>
          <input type="range" className="volume" min={0} max={1} step={0.05} value={muted ? 0 : volume} onChange={(e) => setVolumeTo(Number(e.target.value))} aria-label={t("player.volume")} />
          <span className="time">{clock(position)}{total ? ` / ${clock(total)}` : ""}</span>
          <span className="spacer" />
          <button
            className="ctl wide"
            aria-expanded={panel}
            aria-haspopup="dialog"
            onClick={press(() => {
              setPanel((p) => !p);
              setOpened(true);
            })}
          >
            <SubtitlesIcon />
            <span>{t("player.tracks")}</span>
          </button>
          <button className="ctl" onClick={press(() => void toggleFullscreen())} aria-label={fullscreen ? t("player.exitFullscreen") : t("player.fullscreen")}>
            {fullscreen ? <ExitFullscreenIcon /> : <FullscreenIcon />}
          </button>
        </div>
      </div>

      {panel && (
        <TracksPanel
          movie={movie}
          subs={subs}
          selected={selected}
          audio={tracks.loading ? null : tracks.data}
          audioIndex={audio.index}
          onApply={(chosenSub, chosenAudio) => {
            setSub(chosenSub);
            chooseAudio(chosenAudio);
            setPanel(false);
          }}
          onCancel={() => setPanel(false)}
          onChanged={onChanged}
        />
      )}
      {(!started || failed) && <p className="player-status" role="status">{status}</p>}
    </div>
  );
}
