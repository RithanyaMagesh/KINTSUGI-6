// Replay controls — §6.2. The backend owns replay playback (POST /replay/*)
// and streams frames over the same /ws/state socket, so the UI is identical
// to live mode. Buttons disabled until a replay is loaded.
import { useEffect, useState } from "react";
import { backend } from "../../api/backend";
import { useSimStore } from "../../stores/simStore";
import { useReplayStore } from "../../stores/replayStore";
import chrome from "../../styles/chrome.module.css";
import styles from "./ReplayControls.module.css";

const SPEEDS = [1, 10, 100, 500];

export default function ReplayControls() {
  const mode = useSimStore((s) => s.mode);
  const setMode = useSimStore((s) => s.setMode);
  const resetStore = useSimStore((s) => s.reset);
  const isPlaying = useReplayStore((s) => s.isPlaying);
  const setIsPlaying = useReplayStore((s) => s.setIsPlaying);
  const activeFile = useReplayStore((s) => s.activeFile);
  const setActiveFile = useReplayStore((s) => s.setActiveFile);
  const playbackSpeed = useReplayStore((s) => s.playbackSpeed);
  const setPlaybackSpeed = useReplayStore((s) => s.setPlaybackSpeed);

  const [files, setFiles] = useState<string[]>([]);
  const [selected, setSelected] = useState("");
  const [seekTo, setSeekTo] = useState("0");
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
          onClick={() =>
            run(
              () => backend.replayLoad(selected, playbackSpeed),
              () => {
                resetStore();
                setActiveFile(selected);
                setIsPlaying(true);
                setMode("replay");
              },
            )
          }
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
        <button
          className={chrome.btn}
          disabled={!replay || busy}
          onClick={() =>
            run(backend.replayStop, () => {
              resetStore();
              setActiveFile(null);
              setIsPlaying(false);
              setMode("stopped");
            })
          }
        >
          Stop replay
        </button>
      </div>
      {replay && activeFile !== null && (
        <p className={chrome.hint}>Loaded log: {activeFile}</p>
      )}
      {error !== null && <p className={chrome.errorText}>{error}</p>}
    </section>
  );
}
