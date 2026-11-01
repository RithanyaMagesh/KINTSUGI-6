// Selected satellite detail. Simplified view: a short summary (role, slot,
// distance to slot, fuel spent, status, latest change). Advanced view adds the
// before/after replan comparison, position and speed, and the full history.
import { useMemo } from "react";
import { useSimStore } from "../../stores/simStore";
import { useUiStore } from "../../stores/uiStore";
import { historyFor } from "../../stores/roleHistoryStore";
import type { RoleHistoryEntry } from "../../stores/roleHistoryStore";
import { distanceToSeat, fitFormation } from "../../utils/geometry";
import { formatMsPerS } from "../../utils/format";
import { clock, faultLabel, roleLabel, rolesLabel, satLabel } from "../live/hudFormat";
import { FuelBar, SatFlags } from "../live/SatBits";
import { slotLabel } from "../recovery/RecoveryLog";
import chrome from "../../styles/chrome.module.css";
import styles from "./SelectedSatellitePanel.module.css";

const ROLE_SEMANTICS: Record<string, string> = {
  leader: "Keeps the formation reference and hands out roles",
  imager: "Images the ground",
  sensor: "Images the ground",
  downlink: "Relays data to the ground station",
};

function entryText(entry: RoleHistoryEntry): string {
  if (entry.kind === "recovered") {
    return entry.note !== null ? entry.note : "formation recovered";
  }
  if (entry.kind === "failed") {
    const parts = ["failed"];
    if (entry.role !== null) parts.push("as " + roleLabel(entry.role));
    if (entry.targetSlot !== null) parts.push("holding " + slotLabel(entry.targetSlot));
    if (entry.note !== null) parts.push("(" + faultLabel(entry.note) + ")");
    return parts.join(" ");
  }
  const slotChanged =
    entry.targetSlot !== null && entry.targetSlot !== entry.oldTargetSlot;
  const roleChanged = entry.role !== null && entry.role !== entry.oldRole;
  if (!slotChanged && !roleChanged) return "";
  if (slotChanged) {
    const base =
      entry.oldTargetSlot !== null
        ? "took over " + slotLabel(entry.targetSlot ?? "") + " (was " + slotLabel(entry.oldTargetSlot) + ")"
        : "took over " + slotLabel(entry.targetSlot ?? "");
    if (entry.note !== null) {
      const who = entry.note.match(/^SAT-\d+/);
      return who !== null ? base + " after " + who[0] + " failed" : base;
    }
    return base;
  }
  return entry.oldRole !== null
    ? "became " + roleLabel(entry.role ?? "") + " (was " + roleLabel(entry.oldRole) + ")"
    : "became " + roleLabel(entry.role ?? "");
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
      <span className={styles.value}>{props.children}</span>
    </div>
  );
}

export default function SelectedSatellitePanel() {
  const viewMode = useUiStore((s) => s.viewMode);
  const satellites = useSimStore((s) => s.satellites);
  const reassignment = useSimStore((s) => s.lastReassignment);
  const selectedId = useUiStore((s) => s.selectedSatelliteId);
  const sat = satellites.find((s) => s.id === selectedId) ?? null;
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
      ? "Drifting; the others keep clear of it"
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
  const postSlot = sat.status === "failed" ? "None, drifting" : (sat.targetSlot ?? defaultInitialSlot);
  const roleShifted = preRole !== sat.role;
  const slotShifted = preSlot !== postSlot;

  const latestTransition =
    timeline.length > 0 ? entryText(timeline[timeline.length - 1]) : "";

  const distText = dist === null ? "unmeasured" : dist.toFixed(1) + " m";

  if (viewMode === "simplified") {
    return (
      <div className={styles.panel}>
        <Row label="Status">
          {satLabel(sat)}
          <SatFlags sat={sat} />
        </Row>
        <Row label="Role">
          {rolesLabel(sat)}
          {sat.originalRole !== undefined && sat.originalRole !== sat.role && <> (was {roleLabel(sat.originalRole).toLowerCase()})</>}
        </Row>
        <Row label="Slot">{slotLabel(postSlot)}</Row>
        <Row label="Distance to slot">{distText}</Row>
        <Row label="Fuel">{sat.fuelMpsLeft !== undefined ? <FuelBar sat={sat} /> : formatMsPerS(sat.dv_used) + " spent"}</Row>
        {latestTransition !== "" && (
          <p className={styles.reason}>Latest change: {latestTransition}</p>
        )}
      </div>
    );
  }

  return (
    <div className={styles.panel}>
      <div className={styles.intelGrid} aria-label="Before and after the replan">
        <div className={styles.intelCol}>
          <span className={styles.intelHeader}>At start</span>
          <div className={styles.intelLine}>
            <span>Role</span>
            <strong className={styles.value}>{roleLabel(preRole)}</strong>
          </div>
          <div className={styles.intelLine}>
            <span>Slot</span>
            <strong className={styles.value}>{slotLabel(preSlot)}</strong>
          </div>
        </div>
        <div className={styles.intelCol}>
          <span className={styles.intelHeader}>Now</span>
          <div className={styles.intelLine}>
            <span>Role</span>
            <strong
              className={styles.value}
              style={{ color: roleShifted ? "var(--status-caution)" : "var(--ink)" }}
            >
              {roleLabel(sat.role)}
            </strong>
          </div>
          <div className={styles.intelLine}>
            <span>Slot</span>
            <strong
              className={styles.value}
              style={{
                color:
                  sat.status === "failed"
                    ? "var(--status-failed)"
                    : slotShifted
                      ? "var(--status-caution)"
                      : "var(--ink)",
              }}
            >
              {slotLabel(postSlot)}
            </strong>
          </div>
        </div>
      </div>

      <Section title="Role">
        <Row label="Status">
          {satLabel(sat)}
          <SatFlags sat={sat} />
        </Row>
        <Row label="Role">
          {rolesLabel(sat)}
          {sat.originalRole !== undefined && sat.originalRole !== sat.role && <> (was {roleLabel(sat.originalRole).toLowerCase()})</>}
        </Row>
        <div className={styles.row}>
          <span className={styles.label}>Job</span>
          <span className={styles.explain}>{semantics ?? "unmeasured"}</span>
        </div>
        {sat.failureType !== undefined && <Row label="Fault">{faultLabel(sat.failureType)}</Row>}
      </Section>

      <Section title="Position and slot">
        <Row label="Position">
          {sat.r.map((c) => c.toFixed(1)).join(", ")} m
        </Row>
        <p className={styles.caption}>Radial, along-track and cross-track offset from the orbit reference.</p>
        <Row label="Speed">{formatMsPerS(Math.hypot(...sat.v))}</Row>
        <Row label="Slot">{slotLabel(postSlot)}</Row>
        <Row label="Distance to slot">{distText}</Row>
        <Row label="Fuel">{sat.fuelMpsLeft !== undefined ? <FuelBar sat={sat} /> : formatMsPerS(sat.dv_used) + " spent"}</Row>
      </Section>

      <Section title="Role and task history">
        {timeline.length === 0 ? (
          <p className={styles.reason}>No role or task changes yet.</p>
        ) : (
          <>
            {timeline.length >= 250 && (
              <p className={styles.caption}>Showing the latest 250 changes.</p>
            )}
            <ol className={styles.timeline}>
              {timeline.map((entry) => {
                const text = entryText(entry);
                if (text === "") return null;
                return (
                  <li key={entry.kind + "-" + entry.t} className={styles.timelineRow}>
                    <span className={styles.timelineT}>{clock(entry.t)}</span>
                    <span className={styles.timelineText}>{text}</span>
                  </li>
                );
              })}
            </ol>
          </>
        )}
      </Section>
    </div>
  );
}
