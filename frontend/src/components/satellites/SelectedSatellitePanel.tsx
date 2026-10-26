// Selected satellite detail panel — FRONTEND_SPEC §7.7.
// Adapts to Simplified vs. Advanced view mode:
// - Simplified mode: Concise summary of the selected satellite (Role, Target
//   slot, Distance to slot, and latest task transition).
// - Advanced mode: Full Pre/Post-Replan comparison, LVLH state vectors (r, v),
//   cumulative Δv, full role/task history, and display-only telemetry advisor.
// Zero raw hex (§13.1), strict Sentence case (§13.2).
import { useMemo } from "react";
import { useSimStore } from "../../stores/simStore";
import { useUiStore } from "../../stores/uiStore";
import { historyFor, suspectFor } from "../../stores/roleHistoryStore";
import type { RoleHistoryEntry } from "../../stores/roleHistoryStore";
import { distanceToSeat, fitFormation } from "../../utils/geometry";
import { satelliteStatusColor } from "../../utils/colors";
import { formatMsPerS } from "../../utils/format";
import chrome from "../../styles/chrome.module.css";
import styles from "./SelectedSatellitePanel.module.css";

const ROLE_SEMANTICS: Record<string, string> = {
  leader: "Formation reference & role coordinator",
  imager: "Ground-imaging payload sensor",
  sensor: "Ground-imaging payload sensor",
  downlink: "Ground-station telemetry relay",
};

function entryText(entry: RoleHistoryEntry): string {
  if (entry.kind === "recovered") {
    return entry.note !== null ? entry.note : "formation recovered";
  }
  if (entry.kind === "failed") {
    const parts = ["failed"];
    if (entry.role !== null) parts.push("as " + entry.role);
    if (entry.targetSlot !== null) parts.push("holding " + entry.targetSlot);
    if (entry.note !== null) parts.push("(" + entry.note + ")");
    return parts.join(" ");
  }
  const slotChanged =
    entry.targetSlot !== null && entry.targetSlot !== entry.oldTargetSlot;
  const roleChanged = entry.role !== null && entry.role !== entry.oldRole;
  if (!slotChanged && !roleChanged) return "";
  if (slotChanged) {
    const base =
      entry.oldTargetSlot !== null
        ? "took over " + entry.targetSlot + " (was " + entry.oldTargetSlot + ")"
        : "took over " + entry.targetSlot;
    if (entry.note !== null) {
      const who = entry.note.match(/^SAT-\d+/);
      const trigger =
        who !== null ? "after " + who[0] + " failed" : "after: " + entry.note;
      return base + " " + trigger;
    }
    return base;
  }
  return entry.oldRole !== null
    ? "took on the " + entry.role + " role (was " + entry.oldRole + ")"
    : "took on the " + entry.role + " role";
}

function Section(props: { title: string; children: React.ReactNode }) {
  return (
    <section className={styles.section}>
      <h3 className={styles.sectionTitle}>{props.title}</h3>
      {props.children}
    </section>
  );
}

function Row(props: { label: string; children: React.ReactNode }) {
  return (
    <div className={styles.row}>
      <span className={styles.label}>{props.label}</span>
      <span className={styles.mono}>{props.children}</span>
    </div>
  );
}

function Vec(props: { label: string; v: [number, number, number]; unit: string }) {
  const components = props.v.map((c) => c.toFixed(1)).join(", ");
  return (
    <div className={styles.row}>
      <span className={styles.label}>{props.label}</span>
      <span className={styles.mono}>
        [{" " + components + " "}] {props.unit}
      </span>
    </div>
  );
}

export default function SelectedSatellitePanel() {
  const viewMode = useUiStore((s) => s.viewMode);
  const satellites = useSimStore((s) => s.satellites);
  const reassignment = useSimStore((s) => s.lastReassignment);
  const selectedId = useUiStore((s) => s.selectedSatelliteId);
  const selectSatellite = useUiStore((s) => s.selectSatellite);
  const sat = satellites.find((s) => s.id === selectedId) ?? null;
  const verdict = suspectFor(selectedId);
  const history = historyFor(selectedId);

  const timeline = useMemo(
    () => [...history].sort((a, b) => a.t - b.t),
    [history],
  );

  if (sat === null) {
    return (
      <p className={chrome.hint}>
        Click any satellite in the 3D view or fleet list to inspect its role and slot assignment.
      </p>
    );
  }

  const fit = fitFormation(satellites, Math.max(satellites.length, 1));
  const dist = distanceToSeat(sat, fit);
  const semantics =
    sat.status === "failed"
      ? "Coasting ballistic obstacle (2.0 km keep-out)"
      : ROLE_SEMANTICS[sat.role];

  const rRow =
    reassignment !== null
      ? reassignment.rows.find((r) => r.satelliteId === sat.id) ?? null
      : null;
  const lastReassignEntry =
    [...timeline].reverse().find((e) => e.kind === "reassignment" || e.kind === "failed") ?? null;

  const preRole =
    rRow?.oldRole ??
    lastReassignEntry?.oldRole ??
    (lastReassignEntry?.kind === "failed" ? lastReassignEntry.role : null) ??
    sat.role;
  const defaultInitialSlot =
    "slot_" + String(Math.max(0, Number.parseInt(sat.id.replace("SAT-", ""), 10) - 1));
  const preSlot =
    lastReassignEntry?.oldTargetSlot ??
    (lastReassignEntry?.kind === "failed" ? lastReassignEntry.targetSlot : null) ??
    defaultInitialSlot;
  const postSlot = sat.status === "failed" ? "none (coasting)" : (sat.targetSlot ?? defaultInitialSlot);
  const roleShifted = preRole !== sat.role;
  const slotShifted = preSlot !== postSlot;

  const latestTransition =
    timeline.length > 0 ? entryText(timeline[timeline.length - 1]) : "";

  if (viewMode === "simplified") {
    return (
      <div className={styles.panel}>
        <div className={styles.header}>
          <div className={styles.targetTitleGroup}>
            <span className={styles.id}>{sat.id}</span>
            <span
              className={styles.statusBadge}
              style={{
                color: satelliteStatusColor(sat.status),
                borderColor: satelliteStatusColor(sat.status),
              }}
            >
              {sat.status}
            </span>
          </div>
          <button
            type="button"
            className={styles.clearBtn}
            onClick={() => selectSatellite(null)}
          >
            Clear
          </button>
        </div>

        <Row label="Role">{sat.role}</Row>
        <Row label="Target slot">{postSlot}</Row>
        <Row label="Slot error">
          {dist === null ? "unmeasured" : dist.toFixed(1) + " m"}
        </Row>
        <Row label="Propellant (Δv)">{formatMsPerS(sat.dv_used)}</Row>
        {latestTransition !== "" && (
          <p className={styles.reason}>Latest change: {latestTransition}</p>
        )}
      </div>
    );
  }

  return (
    <div className={styles.panel}>
      <div className={styles.header}>
        <div className={styles.targetTitleGroup}>
          <span className={styles.id}>{sat.id}</span>
          <span
            className={styles.statusBadge}
            style={{
              color: satelliteStatusColor(sat.status),
              borderColor: satelliteStatusColor(sat.status),
            }}
          >
            {sat.status}
          </span>
        </div>
        <button
          type="button"
          className={styles.clearBtn}
          onClick={() => selectSatellite(null)}
          title="Clear satellite selection"
        >
          Clear
        </button>
      </div>

      {/* Pre-Replan vs Post-Replan Comparison */}
      <div className={styles.intelGrid} aria-label="Pre and post replan comparison">
        <div className={styles.intelCol}>
          <span className={styles.intelHeader}>Initial state</span>
          <div className={styles.intelLine}>
            <span>Role</span>
            <strong className={styles.mono}>{preRole}</strong>
          </div>
          <div className={styles.intelLine}>
            <span>Slot</span>
            <strong className={styles.mono}>{preSlot}</strong>
          </div>
        </div>
        <div className={styles.intelCol}>
          <span className={styles.intelHeader}>Current state</span>
          <div className={styles.intelLine}>
            <span>Role</span>
            <strong
              className={styles.mono}
              style={{ color: roleShifted ? "var(--status-caution)" : "var(--ink)" }}
            >
              {sat.role}
            </strong>
          </div>
          <div className={styles.intelLine}>
            <span>Slot</span>
            <strong
              className={styles.mono}
              style={{
                color:
                  sat.status === "failed"
                    ? "var(--status-failed)"
                    : slotShifted
                      ? "var(--status-caution)"
                      : "var(--ink)",
              }}
            >
              {postSlot}
            </strong>
          </div>
        </div>
      </div>

      <Section title="Identity & mission function">
        <Row label="Role">{sat.role}</Row>
        <div className={styles.row}>
          <span className={styles.label}>Function</span>
          <span className={styles.explain}>{semantics ?? "unmeasured"}</span>
        </div>
        {sat.failureType !== undefined && (
          <Row label="Failure mode">{sat.failureType}</Row>
        )}
      </Section>

      <Section title="LVLH state vector & slot convergence">
        <Vec label="Position r" v={sat.r} unit="m" />
        <p className={styles.caption}>x radial · y along-track · z cross-track (LVLH)</p>
        <Vec label="Velocity v" v={sat.v} unit="m/s" />
        <Row label="Assigned target slot">{sat.targetSlot ?? "unassigned"}</Row>
        <Row label="Distance to target">
          {dist === null ? "unmeasured" : dist.toFixed(1) + " m"}
        </Row>
        <Row label="Cumulative Δv used">{formatMsPerS(sat.dv_used)}</Row>
      </Section>

      <Section title="Role and task history">
        {timeline.length === 0 ? (
          <p className={styles.reason}>No role or task changes measured yet.</p>
        ) : (
          <>
            {timeline.length >= 250 && (
              <p className={styles.caption}>Showing latest 250 transitions.</p>
            )}
            <ol className={styles.timeline}>
              {timeline.map((entry) => {
                const text = entryText(entry);
                if (text === "") return null;
                return (
                  <li key={entry.kind + "-" + entry.t} className={styles.timelineRow}>
                    <span className={styles.timelineT}>t+{Math.round(entry.t)}s</span>
                    <span className={styles.timelineText}>{text}</span>
                  </li>
                );
              })}
            </ol>
          </>
        )}
      </Section>

      <details className={styles.advisorDetails}>
        <summary className={styles.advisorSummary}>
          <span>Telemetry anomaly advisor</span>
          <span className={styles.advisorTag}>Display-only</span>
        </summary>
        <div className={styles.advisorBody}>
          <div className={styles.row}>
            <span className={styles.label}>Suspect flag</span>
            {verdict === null ? (
              <span className={styles.mono}>unmeasured</span>
            ) : verdict.suspect ? (
              <span className={styles.suspectLabel}>
                suspect · {verdict.score.toFixed(2)}
              </span>
            ) : (
              <span className={styles.mono}>nominal</span>
            )}
          </div>
          {verdict !== null && verdict.suspect && (
            <p className={styles.reason}>{verdict.reason}</p>
          )}
          {sat.risk !== undefined && <Row label="LightGBM risk">{sat.risk.toFixed(2)}</Row>}
          <p className={styles.caption}>
            Advisory telemetry readout only — never triggers replanning before the 3-heartbeat
            protocol confirms failure.
          </p>
        </div>
      </details>
    </div>
  );
}
