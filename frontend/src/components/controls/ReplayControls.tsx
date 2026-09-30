// Replay controls — §6.2 / §7.8. The backend owns replay playback
// (POST /replay/*) and streams frames over the same /ws/state socket, so the
// UI is identical to live mode. Seek is a range slider over the log's measured
// end time (read once from GET /replay/file) plus the numeric input for exact
// values; without a measured end time only the numeric input is offered.
import { useEffect, useState } from "react";
import { backend, replayFileText } from "../../api/backend";
import { useSimStore } from "../../stores/simStore";
import { useReplayStore } from "../../stores/replayStore";
import { formatSimTime } from "../../utils/format";
import chrome from "../../styles/chrome.module.css";
import styles from "./ReplayControls.module.css";

const SPEEDS = [1, 10, 100, 500];

/** End time of a replay log [s]: the t of its last parseable line. Null when
 * the file cannot be read — the slider is hidden rather than the duration
 * guessed (repo invariant 1). */
async function logDuration(filename: string): Promise<number | null> {
  const text = await replayFileText(filename);
  if (text === null) return null;
  const lines = text.split("\n");
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i].trim();
    if (line === "") continue;
    try {
      const t = (JSON.parse(line) as { t?: unknown }).t;
      if (typeof t === "number" && Number.isFinite(t)) return t;
    } catch {
      continue; // skip unparsable tail lines, keep scanning backwards
    }
  }
  return null;
}

export default function ReplayControls() {
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
      await backend.replayLoad(selected, playbackSpeed);
      resetStore();
      setActiveFile(selected);
      setIsPlaying(true);
      setMode("replay");
      setDuration(await logDuration(selected)); // measured end time for the slider
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

  return (
    <section className={styles.controls} aria-label="Replay controls">
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
      </div>
      <div className={chrome.btnRow}>
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
      </div>
      <div className={styles.loadRow}>
        <input
          className={chrome.input}
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
        <select
          className={chrome.select}
          value={playbackSpeed}
          disabled={!replay || busy}
          onChange={(e) => {
            const speed = Number(e.target.value);
            setPlaybackSpeed(speed);
            run(() => backend.replaySpeed(speed));
          }}
          aria-label="Replay speed"
        >
          {SPEEDS.map((s) => (
            <option key={s} value={s}>
              {s}×
            </option>
          ))}
        </select>
      </div>
      <div className={styles.loadRow}>
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
      </div>
      {replay && duration !== null && (
        <div className={styles.seekRow}>
          <label className={chrome.fieldLabel} htmlFor="replay-seek">
            Seek timeline — time {formatSimTime(simTime)} of t + {duration.toFixed(1)} s
          </label>
          <input
            id="replay-seek"
            type="range"
            className={styles.seek}
            min={0}
            max={duration}
            step={1}
            value={sliderT ?? simTime ?? 0}
            disabled={busy}
            onChange={(e) => setSliderT(Number(e.target.value))}
            onPointerUp={commitSliderSeek}
            onKeyUp={commitSliderSeek}
            aria-valuetext={formatSimTime(sliderT ?? simTime)}
          />
        </div>
      )}
      {mode !== "replay" && activeFile === null && (
        <p className={chrome.hint}>No replay file loaded. Select a log file to play.</p>
      )}
      {replay && activeFile !== null && (
        <p className={chrome.hint}>Loaded log: {activeFile}</p>
      )}
      {error !== null && <p className={chrome.errorText}>{error}</p>}
    </section>
  );
}
