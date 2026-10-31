// Spectator camera — ride along with any satellite. The camera follow itself
// is the scene's fly-to (selecting a satellite flies to it and follows); this
// bar steps the selection through the whole swarm (‹ ›, ←/→) and can tour it
// on a timer (Auto).
import { useEffect, useState } from "react";
import { useSimStore } from "../../stores/simStore";
import { useUiStore } from "../../stores/uiStore";
import { roleLabel, statusLabel } from "./hudFormat";
import { satelliteStatusColor } from "../../utils/colors";
import styles from "./ImmersiveLive.module.css";

const TOUR_MS = 7000;

/** Satellite ids in natural order (SAT-2 before SAT-10). */
export function spectatorOrder(): string[] {
  return useSimStore
    .getState()
    .satellites.map((s) => s.id)
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
}

/** Step the spectated satellite by `dir` (+1 next, -1 previous), wrapping. */
export function spectateStep(dir: 1 | -1): void {
  const ids = spectatorOrder();
  if (ids.length === 0) return;
  const cur = useUiStore.getState().selectedSatelliteId;
  const i = cur === null ? -1 : ids.indexOf(cur);
  const next = i < 0 ? (dir === 1 ? 0 : ids.length - 1) : (i + dir + ids.length) % ids.length;
  useUiStore.getState().selectSatellite(ids[next]);
}

/** Start spectating: keep the current pick, else start with the leader. */
export function spectateStart(): void {
  if (useUiStore.getState().selectedSatelliteId !== null) return;
  const sats = useSimStore.getState().satellites;
  const first = sats.find((s) => s.role === "leader" && s.status !== "failed") ?? sats[0];
  if (first !== undefined) useUiStore.getState().selectSatellite(first.id);
}

export default function SpectatorBar({ onExit }: { onExit(): void }) {
  const [auto, setAuto] = useState(false);
  const selectedId = useUiStore((s) => s.selectedSatelliteId);
  const sat = useSimStore((s) => s.satellites.find((x) => x.id === selectedId) ?? null);
  const count = useSimStore((s) => s.satellites.length);
  const ids = spectatorOrder();
  const pos = selectedId === null ? 0 : ids.indexOf(selectedId) + 1;

  useEffect(() => {
    if (!auto) return;
    const t = window.setInterval(() => spectateStep(1), TOUR_MS);
    return () => window.clearInterval(t);
  }, [auto]);

  return (
    <div className={styles.spectator} role="group" aria-label="Spectator camera">
      <button type="button" className={styles.specBtn} onClick={() => spectateStep(-1)} aria-label="Previous satellite" title="Previous (←)">
        ‹
      </button>
      <div className={styles.specInfo} aria-live="polite">
        <span className={styles.specName}>
          {sat !== null && (
            <span className={styles.statusPip} style={{ background: satelliteStatusColor(sat.status) }} aria-hidden="true" />
          )}
          {selectedId ?? "No satellite"}
          {sat !== null && <span className={styles.specRole}>{roleLabel(sat.role)}</span>}
        </span>
        <span className={styles.specMeta}>
          {sat !== null ? `${statusLabel(sat.status)}, ${pos} of ${count}` : `${count} satellites`}
        </span>
      </div>
      <button type="button" className={styles.specBtn} onClick={() => spectateStep(1)} aria-label="Next satellite" title="Next (→)">
        ›
      </button>
      <button type="button" className={styles.seg} aria-pressed={auto} onClick={() => setAuto((v) => !v)} title="Tour every satellite automatically">
        Auto
      </button>
      <button type="button" className={styles.seg} onClick={onExit} title="Back to the whole Earth (Esc)">
        Exit
      </button>
    </div>
  );
}
