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
// fewer rows for a narrow band; every function (play/pause/restart/speed/
// seek/stop) survives in both variants. While a recording is loaded
// (replayStore.activeFile set — the page's gallery is the selector), the
// file dropdown stands down for a quiet "Playing <file>" readout and a
// "Change recording" button that returns focus to the gallery; the dropdown
// only shows when nothing is loaded, and its value always follows
// activeFile so it can never disagree with the session. The element keeps
// id="replay-controls" so legacy scroll targets still land somewhere sane.
import { useEffect, useState } from "react";
import { backend, replayLogDuration } from "../../api/backend";
import { useSimStore } from "../../stores/simStore";
import { useRecoveryStore } from "../../stores/recoveryStore";
import { useRoleHistoryStore } from "../../stores/roleHistoryStore";
import { useHistoryStore } from "../../stores/historyStore";
import { useReplayStore } from "../../stores/replayStore";
import { useUiStore } from "../../stores/uiStore";
import { clock } from "../live/hudFormat";
import chrome from "../../styles/chrome.module.css";
import styles from "./ReplayControls.module.css";

// Transport speeds for the demo (§7.8): 0.5×–10×. Default 10× so a loaded log
// visibly moves — a 5676 s log takes 95 minutes at 1×.
const SPEEDS = [0.5, 1, 2, 5, 10];
const DEFAULT_SPEED = 10;

const RUN_LABELS: Record<string, string> = {
  firefly_swarm: "Six satellites on FIREFLY-1's real orbit",
  two_failure: "Two satellites lost",
  cascading_n8: "Eight satellites, three failures in a row",
  leader_failure_6sat: "Leader lost, then an imager",
  single_failure_n4: "Four satellites, leader lost and replaced",
  nominal: "Nominal orbit, no failures",
};

/** Plain-English title for a recorded run; never the raw log filename. */
export function runTitle(filename: string): string {
  const name = filename.replace(/\.jsonl$/, "");
  const run = /_run(\d+)$/.exec(name);
  const base = name.replace(/_run\d+$/, "");
  const title = RUN_LABELS[base] ?? base.charAt(0).toUpperCase() + base.slice(1).replace(/_/g, " ");
  return run !== null ? `${title}, run ${run[1]}` : title;
}

/** Clear every per-run store so the next frames start a clean story. */
export function resetRunStores(): void {
  useSimStore.getState().reset();
  useRecoveryStore.getState().resetForNewRun();
  useRoleHistoryStore.getState().resetForNewRun();
  useHistoryStore.getState().reset();
}

/** Backward seek / restart: wipe the "future" the stores already saw, but keep
 * the session's identity and replay mode. */
export function rewindStores(): void {
  const { scenario, seed, policy, minSepM } = useSimStore.getState();
  resetRunStores();
  useSimStore.getState().setSessionMeta({ scenario, seed, policy, minSepM });
  useSimStore.getState().setMode("replay");
}

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
  const [filesError, setFilesError] = useState<string | null>(null);
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
      .catch((err: unknown) => {
        if (!cancelled) {
          setFiles([]);
          setFilesError(err instanceof Error ? err.message : "unknown error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // The dropdown mirrors the session, never a stale local pick: a run loaded
  // through the page's gallery (or any other path) updates the selection, so
  // after Stop the list shows the recording that actually played.
  useEffect(() => {
    if (activeFile !== null) setSelected(activeFile);
  }, [activeFile]);

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
      // Reset BEFORE loading: the backend pushes the first frames right away.
      resetRunStores();
      useUiStore.getState().setRunSpeed(speed);
      await backend.replayLoad(selected, speed);
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

  function seek(t: number, after?: () => void): void {
    const now = useSimStore.getState().simTime;
    // Going back: forget later events, or dead satellites read as recovered.
    if (now !== null && t < now) rewindStores();
    void run(() => backend.replaySeek(t), after);
  }

  function commitSliderSeek(): void {
    if (sliderT === null) return;
    const t = sliderT;
    setSliderT(null);
    seek(t);
  }

  function stopReplay(): void {
    void run(backend.replayStop, () => {
      resetStore();
      setActiveFile(null);
      setIsPlaying(false);
      setMode("stopped");
      setDuration(null);
      setSliderT(null);
    });
  }

  // "Change recording" hands focus back to the page's run gallery — the
  // gallery is the selector, this bar only plays. No-op if this bar is ever
  // mounted without a gallery.
  function focusGallery(): void {
    document.getElementById("replay-gallery")?.focus();
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
        aria-label="Jump to time in seconds"
      />
      <button
        className={chrome.btn}
        disabled={!replay || busy || seekTo === ""}
        onClick={() => seek(Number(seekTo))}
      >
        Jump
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
          onClick={() => seek(0, () => setIsPlaying(true))}
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
            useUiStore.getState().setRunSpeed(next);
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
            {clock(simTime)}
            {duration !== null ? ` of ${clock(duration)}` : ""}
          </span>
        )}
      </div>
      {replay && duration !== null && (
        <div className={styles.seekRow}>
          <label className={chrome.fieldLabel} htmlFor="replay-seek">
            Position {clock(simTime)} of {clock(duration)}
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
            aria-valuetext={clock(sliderT ?? simTime)}
          />
        </div>
      )}
      {activeFile !== null ? (
        // A recording is loaded (via the page's gallery or this bar): one
        // selector only — the dropdown stands down for a quiet readout.
        <div className={styles.loadRow}>
          <span className={styles.playingState}>{isPlaying ? "Playing" : "Paused"}</span>
          <span className={styles.fileMono}>{runTitle(activeFile)}</span>
          <button type="button" className={chrome.btn} onClick={focusGallery}>
            Change recording
          </button>
          <button type="button" className={chrome.btn} disabled={!replay || busy} onClick={stopReplay}>
            Stop replay
          </button>
          {compact && seekInput}
        </div>
      ) : (
        // Nothing loaded: the fallback file picker (also this bar's
        // standalone path). Empty state when the backend lists no logs.
        <div className={styles.loadRow}>
          <select
            className={chrome.select}
            value={selected}
            disabled={files.length === 0 || busy}
            onChange={(e) => setSelected(e.target.value)}
            aria-label="Recorded run"
          >
            {files.length === 0 && <option value="">No recorded runs found</option>}
            {files.map((f) => (
              <option key={f} value={f}>
                {runTitle(f)}
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
          <button type="button" className={chrome.btn} disabled={!replay || busy} onClick={stopReplay}>
            Stop replay
          </button>
          {compact && seekInput}
        </div>
      )}
      {!compact && (
        <div className={styles.loadRow}>
          {seekInput}
        </div>
      )}
      {replay && duration === null && (
        <p className={chrome.hint}>Run length unknown, so use the time box to jump.</p>
      )}
      {!compact && replay && activeFile === null && (
        <p className={chrome.hint}>
          A replay is already playing; pick a run to start a new one.
        </p>
      )}
      {!replay && activeFile === null && (
        <p className={chrome.hint}>Nothing loaded yet. Pick a run to replay.</p>
      )}
      {filesError !== null && (
        <p className={chrome.errorText}>Could not list recorded runs: {filesError}</p>
      )}
      {error !== null && <p className={chrome.errorText}>{error}</p>}
    </section>
  );
}
