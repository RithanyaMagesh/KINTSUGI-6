// Small per-satellite pieces the v2 engine adds: a fuel bar against the tank
// and subsystem icons. Both render nothing on v1 frames (keys absent).
import type { Satellite } from "../../types/satellite";
import styles from "./SatBits.module.css";

/** Fuel left against the tank, where tank = spent + left (both measured). */
export function FuelBar({ sat, compact = false }: { sat: Satellite; compact?: boolean }) {
  if (sat.fuelMpsLeft === undefined) return <>{sat.dv_used.toFixed(2)}{compact ? "" : " m/s spent"}</>;
  const tank = sat.dv_used + sat.fuelMpsLeft;
  const frac = tank > 0 ? sat.fuelMpsLeft / tank : 0;
  const tone = sat.status === "failed" ? "var(--ink-faint)" : frac <= 0 ? "var(--status-failed)" : frac < 0.25 ? "var(--status-caution)" : "var(--status-nominal)";
  return (
    <span className={styles.fuel} title={`${sat.fuelMpsLeft.toFixed(2)} of ${tank.toFixed(2)} m/s left`}>
      <span className={styles.track} aria-hidden="true">
        <span className={styles.fill} style={{ width: `${frac * 100}%`, background: tone }} />
      </span>
      <span className={styles.fuelText}>{sat.fuelMpsLeft.toFixed(2)}{compact ? "" : ` of ${tank.toFixed(2)} m/s left`}</span>
    </span>
  );
}

const PATHS = {
  camera: "M3 6h3l1.5-2h5L14 6h3v9H3z M10 13.5a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  radio: "M10 11v6 M6.5 7.5a5 5 0 0 1 7 0 M4 5a8.5 8.5 0 0 1 12 0 M10 11a1 1 0 1 0 0-.01",
  thruster: "M7 3h6v6l3 8H4l3-8z M8 17v2 M12 17v2",
};

function Icon({ path, bad, label }: { path: string; bad: boolean; label: string }) {
  return (
    <svg
      className={styles.icon}
      viewBox="0 0 20 20"
      role="img"
      aria-label={label}
      style={{ color: bad ? "var(--status-failed)" : "var(--ink-faint)" }}
    >
      <title>{label}</title>
      <path d={path} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Camera, radio and thruster state icons; red when that part has failed. */
export function SatFlags({ sat }: { sat: Satellite }) {
  if (sat.payloadOk === undefined && sat.radioOk === undefined && sat.stuck === undefined) return null;
  return (
    <span className={styles.flags}>
      {sat.payloadOk !== undefined && (
        <Icon path={PATHS.camera} bad={!sat.payloadOk} label={sat.payloadOk ? "Camera working" : "Camera failed"} />
      )}
      {sat.radioOk !== undefined && (
        <Icon path={PATHS.radio} bad={!sat.radioOk} label={sat.radioOk ? "Radio working" : "Radio silent"} />
      )}
      {sat.stuck !== undefined && (
        <Icon path={PATHS.thruster} bad={sat.stuck} label={sat.stuck ? "Thruster stuck open" : "Thruster closed"} />
      )}
    </span>
  );
}
