// Full-screen live HUD — the at-a-glance readouts. Five numbers, all straight
// off the stream (repo invariant 1): absent values render a dash, never a
// guess. Everything deeper lives in the Telemetry drawer.
import { useSimStore } from "../../stores/simStore";
import { useRecoveryStore, selectLatestFailure } from "../../stores/recoveryStore";
import { km } from "./hudFormat";
import styles from "./ImmersiveLive.module.css";


interface ReadoutProps {
  label: string;
  value: string;
  unit?: string;
  note?: string;
  tone?: string;
}

function Readout({ label, value, unit, note, tone }: ReadoutProps) {
  return (
    <div className={styles.readout}>
      <span className={styles.readoutLabel}>{label}</span>
      <span className={styles.readoutValue} style={tone !== undefined ? { color: tone } : undefined}>
        {value}
        {unit !== undefined && value !== "–" && <span className={styles.readoutUnit}>{unit}</span>}
      </span>
      {note !== undefined && <span className={styles.readoutNote}>{note}</span>}
    </div>
  );
}

export default function HudMetrics() {
  const sats = useSimStore((s) => s.satellites);
  const metrics = useSimStore((s) => s.metrics);
  const failure = useRecoveryStore(selectLatestFailure);

  const total = sats.length;
  const lost = sats.filter((s) => s.status === "failed").length;
  const leader = sats.find((s) => s.role === "leader" && s.status !== "failed") ?? null;
  // Decentral runs have no leader by design: the swarm holds its functions.
  const decentral = useSimStore((s) => s.consensusRounds !== null);
  const dv = sats.reduce((sum, s) => sum + s.dv_used, 0);

  const cov = metrics.coverage ?? null;
  const pre = failure?.coverage.pre ?? null;
  let covNote: string | undefined;
  if (cov !== null && pre !== null) {
    const d = (cov - pre) * 100;
    covNote = `${d >= 0 ? "+" : "−"}${Math.abs(d).toFixed(1)} pts vs before the fault`;
  }

  const sep = metrics.minSep ?? null;
  const keepOut = useSimStore((s) => s.minSepM); // scenario's floor; null = unknown
  const sepTone = sep !== null && keepOut !== null && sep < keepOut ? "var(--status-failed)" : undefined;

  return (
    <section className={styles.metrics} aria-label="Key mission readouts">
      <Readout
        label="Ground coverage"
        value={cov === null ? "–" : (cov * 100).toFixed(1)}
        unit="%"
        note={covNote}
      />
      <Readout
        label="Closest approach"
        value={sep === null ? "–" : km(sep, 1)}
        unit="km"
        note={keepOut === null ? undefined : `Keep-out ${km(keepOut, keepOut % 1000 === 0 ? 0 : 1)} km`}
        tone={sepTone}
      />
      <Readout
        label="Satellites flying"
        value={total === 0 ? "–" : `${total - lost}`}
        unit={`of ${total}`}
        note={lost > 0 ? `${lost} lost` : undefined}
        tone={lost > 0 ? "var(--status-failed)" : undefined}
      />
      <Readout
        label="Leader"
        value={total === 0 ? "–" : leader !== null ? leader.id : decentral ? "None, shared" : "Vacant"}
        tone={total > 0 && leader === null && !decentral ? "var(--status-failed)" : undefined}
      />
      <Readout label="Fuel spent" value={total === 0 ? "–" : dv.toFixed(2)} unit="m/s Δv" />
    </section>
  );
}
