// Replay transport bar — §7.8. The backend owns replay playback (POST
// /replay/*) and streams frames over the same /ws/state socket as live mode,
// so the visualization needs no replay-specific path. Play/pause/restart and
// speed go to the session; the scrub slider seeks over the log's MEASURED end
// time (read once from GET /replay/file) — without a measured duration the
// slider is hidden, never guessed (repo invariant 1).
//
// Home: the replay page mounts this component (the §7.8 transport is the
// page's core). The live console no longer hosts it — its replay entry
// points navigate to #/replay. `compact` condenses the same controls into
// fewer rows for a narrow band; every function (load/play/pause/restart/
// speed/seek/stop/file picker) survives in both variants. The element keeps
// id="replay-controls" so legacy scroll targets still land somewhere sane.
import { useEffect, useState } from "react";
import { backend, replayLogDuration } from "../../api/backend";
import { useSimStore } from "../../stores/simStore";
import { useReplayStore } from "../../stores/replayStore";
import { useUiStore } from "../../stores/uiStore";
import { formatSimTime } from "../../utils/format";
import chrome from "../../styles/chrome.module.css";
import styles from "./ReplayControls.module.css";

// Transport speeds for the demo (§7.8): 0.5×–10×. Default 10× so a loaded log
// visibly moves — a 5676 s log takes 95 minutes at 1×.
const SPEEDS = [0.5, 1, 2, 5, 10];
const DEFAULT_SPEED = 10;

interface Props {
  /** Narrow-band variant: same controls, fewer rows, tighter padding. */
  compact?: boolean;
}

export default function ReplayControls({ compact = false }: Props) {
  const mode = useSimStore((s) => s.mode);
  const setMode = useSimStore((s) => s.setMode);
  const resetStore = useSimStore((s) => s.reset);
  const simTime = useSimStore((s) => s.simTime);
  const isPlaying = useReplayStore((s) => s.isPlaying);
  const setIsPlaying = useReplayStore((s) => s.setIsPlaying);
  const activeFile = useReplayStore((s) => s.activeFile);
  const setActiveFile = useReplayStore((s) => s.setActiveFile);
  const playbackSpeed = useReplayStore((s) => s.playbackSpeed);
  const setPlaybackSpeed = useReplayStore((s) => s.setPlaybackSpeed);

  const [files, setFiles] = useState<string[]>([]);
  const [selected, setSelected] = useState("");
  const [seekTo, setSeekTo] = useState("0");
  const [duration, setDuration] = useState<number | null>(null);
  const [sliderT, setSliderT] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // The store defaults to the backend's 100× (cubesat/wire.py StartRequest);
  // normalize once so the select always shows a value it actually offers.
  const speed = SPEEDS.includes(playbackSpeed) ? playbackSpeed : DEFAULT_SPEED;
  useEffect(() => {
    if (!SPEEDS.includes(useReplayStore.getState().playbackSpeed)) {
      useReplayStore.getState().setPlaybackSpeed(DEFAULT_SPEED);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    backend
      .replayFiles()
      .then((data) => {
        if (!cancelled) setFiles(data.files);
      })
      .catch(() => {
        if (!cancelled) setFiles([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // The mission brief's "Open replay mode" sets uiStore.replayModeRequested
  // and loads the latest log itself; preselect that same latest log here so
  // the dropdown reflects the running replay. Reactive (not mount-only) so
  // the flag is consumed whenever this bar is mounted, in either flag/files
  // arrival order. One-shot: consumed once it acts.
  const replayModeRequested = useUiStore((s) => s.replayModeRequested);
  useEffect(() => {
    if (!replayModeRequested || files.length === 0) return;
    setSelected(files[files.length - 1]);
    useUiStore.getState().setReplayModeRequested(false);
  }, [replayModeRequested, files]);

  // Replay loaded from OUTSIDE this bar (mission brief, a page's "Open
  // replay" entry) never runs loadSelected, so the measured log duration
  // would be missing and the scrub slider hidden. Measure it whenever a
  // replay session is active with an unread duration — same source as
  // loadSelected.
  useEffect(() => {
    if (mode !== "replay" || activeFile === null) return;
    let cancelled = false;
    replayLogDuration(activeFile)
      .then((d) => {
        if (!cancelled && d !== null) setDuration(d);
      })
      .catch(() => {
        // unreadable tail: duration stays null, the honest hint shows instead
      });
    return () => {
      cancelled = true;
    };
  }, [mode, activeFile]);

  async function run(action: () => Promise<unknown>, after?: () => void) {
    setBusy(true);
    setError(null);
    try {
      await action();
      after?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Replay command failed");
    } finally {
      setBusy(false);
    }
  }

  const replay = mode === "replay";

  async function loadSelected(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await backend.replayLoad(selected, speed);
      resetStore();
      setActiveFile(selected);
      setIsPlaying(true);
      setMode("replay");
      setDuration(await replayLogDuration(selected)); // measured end time for the slider
    } catch (err) {
      setError(err instanceof Error ? err.message : "Replay command failed");
    } finally {
      setBusy(false);
    }
  }

  function commitSliderSeek(): void {
    if (sliderT === null) return;
    const t = sliderT;
    setSliderT(null);
    void run(() => backend.replaySeek(t));
  }

  const seekInput = (
    <>
      <input
        className={`${chrome.input} ${styles.input}`}
        type="number"
        min={0}
        step={10}
        value={seekTo}
        disabled={!replay || busy}
        onChange={(e) => setSeekTo(e.target.value)}
        aria-label="Seek to sim time in seconds"
      />
      <button
        className={chrome.btn}
        disabled={!replay || busy || seekTo === ""}
        onClick={() => run(() => backend.replaySeek(Number(seekTo)))}
      >
        Seek
      </button>
    </>
  );

  return (
    <section
      id="replay-controls"
      tabIndex={-1}
      className={`${styles.controls} ${compact ? styles.compact : ""}`}
      aria-label="Replay controls"
      aria-busy={busy}
    >
      <div className={styles.transportRow}>
        <span
          className={replay ? styles.badgeActive : styles.badge}
          aria-label={replay ? "Replay mode active" : "No replay loaded"}
        >
          Replay
        </span>
        <button
          className={chrome.btn}
          disabled={!replay || isPlaying || busy}
          onClick={() => run(backend.replayResume, () => setIsPlaying(true))}
        >
          Play
        </button>
        <button
          className={chrome.btn}
          disabled={!replay || !isPlaying || busy}
          onClick={() => run(backend.replayPause, () => setIsPlaying(false))}
        >
          Pause
        </button>
        <button
          className={chrome.btn}
          disabled={!replay || busy}
          onClick={() => run(() => backend.replaySeek(0), () => setIsPlaying(true))}
        >
          Restart
        </button>
        <label className={`${chrome.fieldLabel} ${styles.inlineLabel}`} htmlFor="replay-speed">
          Speed
        </label>
        <select
          id="replay-speed"
          className={chrome.select}
          value={speed}
          disabled={!replay || busy}
          onChange={(e) => {
            const next = Number(e.target.value);
            setPlaybackSpeed(next);
            run(() => backend.replaySpeed(next));
          }}
        >
          {SPEEDS.map((s) => (
            <option key={s} value={s}>
              {s}×
            </option>
          ))}
        </select>
        {replay && (
          <span className={styles.timeMono}>
            {formatSimTime(simTime)}
            {duration !== null ? ` of t + ${duration.toFixed(1)} s` : ""}
          </span>
        )}
      </div>
      {replay && duration !== null && (
        <div className={styles.seekRow}>
          <label className={chrome.fieldLabel} htmlFor="replay-seek">
            Scrub — {formatSimTime(simTime)} of t + {duration.toFixed(1)} s
          </label>
          <input
            id="replay-seek"
            type="range"
            className={styles.seek}
            min={0}
            max={duration}
            step={1}
            value={sliderT ?? simTime ?? 0}
            disabled={!replay || busy}
            onChange={(e) => setSliderT(Number(e.target.value))}
            onPointerUp={commitSliderSeek}
            onKeyUp={commitSliderSeek}
            aria-valuetext={formatSimTime(sliderT ?? simTime)}
          />
        </div>
      )}
      <div className={styles.loadRow}>
        <select
          className={chrome.select}
          value={selected}
          disabled={files.length === 0 || busy}
          onChange={(e) => setSelected(e.target.value)}
          aria-label="Replay log file"
        >
          {files.length === 0 && <option value="">No replay logs found</option>}
          {files.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
        <button
          className={chrome.btn}
          disabled={selected === "" || busy}
          onClick={() => void loadSelected()}
        >
          Load replay
        </button>
        <button
          className={chrome.btn}
          disabled={!replay || busy}
          onClick={() =>
            run(backend.replayStop, () => {
              resetStore();
              setActiveFile(null);
              setIsPlaying(false);
              setMode("stopped");
              setDuration(null);
              setSliderT(null);
            })
          }
        >
          Stop replay
        </button>
        {compact && seekInput}
        {activeFile !== null && <span className={styles.fileMono}>{activeFile}</span>}
      </div>
      {!compact && (
        <div className={styles.loadRow}>
          {seekInput}
        </div>
      )}
      {replay && duration === null && (
        <p className={chrome.hint}>Log duration unreadable — use the exact seek input.</p>
      )}
      {!compact && replay && activeFile === null && (
        <p className={chrome.hint}>
          Replay session in progress — the session greeting does not report the file name.
        </p>
      )}
      {!replay && activeFile === null && (
        <p className={chrome.hint}>No replay file loaded. Select a log file to play.</p>
      )}
      {error !== null && <p className={chrome.errorText}>{error}</p>}
    </section>
  );
}
