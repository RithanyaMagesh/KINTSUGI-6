// Telemetry panel — the operator's answers to "what is happening and why":
// §13.3 readout rows on top (label sans muted · value mono 28px+, tooltip
// explains what the metric means and why it is watched — definitions from
// §7.5/§8.7, no invented numbers), the §7.5 charts behind underline tabs
// (§13.3: underline indicators, never sliding-pill tabs), the §8.1 role
// table as a collapsible section, and the §7.7 selected-satellite panel.
// Every value traces to the stream or a derivation on streamed values;
// absent values render "unmeasured" (invariant 1).
import { useState } from "react";
import { useSimStore } from "../../stores/simStore";
import { useHistoryStore } from "../../stores/historyStore";
import { healthBand } from "../../utils/health";
import ReadoutRow from "../dashboard/ReadoutRow";
import GroundCoverageChart from "../dashboard/GroundCoverageChart";
import FormationDeviationChart from "../dashboard/FormationDeviationChart";
import InterSatDistanceChart from "../dashboard/InterSatDistanceChart";
import DvChart from "../dashboard/DvChart";
import MissionHealthScore from "../dashboard/MissionHealthScore";
import RoleTable from "../dashboard/RoleTable";
import SelectedSatellitePanel from "../satellites/SelectedSatellitePanel";
import chrome from "../../styles/chrome.module.css";
import styles from "./RightPanel.module.css";

const TABS = [
  { id: "coverage", label: "Coverage" },
  { id: "deviation", label: "Deviation" },
  { id: "separation", label: "Separation" },
  { id: "dv", label: "Delta-v" },
  { id: "health", label: "Health" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function RightPanel() {
  const metrics = useSimStore((s) => s.metrics);
  const satellites = useSimStore((s) => s.satellites);
  const [tab, setTab] = useState<TabId>("coverage");

  // Δv used, swarm total: arithmetic on streamed values only — never invented.
  const dvTotal = satellites.reduce((sum, s) => sum + s.dv_used, 0);
  const hasSats = satellites.length > 0;

  // Fleet counts from sats[].status (§7.5): active = not failed (healthy,
  // reconfiguring, recovered); re-renders only when the counts move.
  const failed = satellites.reduce((n, s) => (s.status === "failed" ? n + 1 : n), 0);
  const active = satellites.length - failed;

  // Mission health: the sampler's last derived value (utils/health.ts, §8.7,
  // measured inputs only) and the §8.7 band. Primitive selectors — RightPanel
  // re-renders only when the score or the reference actually changes.
  const health = useHistoryStore((s) =>
    s.samples.length > 0 ? s.samples[s.samples.length - 1].health : null,
  );
  const minSepRef = useHistoryStore((s) => s.minSepRef);
  const band = health === null ? null : healthBand(health);

  // Roving tabindex + arrow keys on the tablist (§13.3 interactive states).
  const onTabKeyDown = (e: React.KeyboardEvent) => {
    const idx = TABS.findIndex((t) => t.id === tab);
    let next: number;
    if (e.key === "ArrowRight") next = (idx + 1) % TABS.length;
    else if (e.key === "ArrowLeft") next = (idx + TABS.length - 1) % TABS.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = TABS.length - 1;
    else return;
    e.preventDefault();
    setTab(TABS[next].id);
    document.getElementById(`telemetry-tab-${TABS[next].id}`)?.focus();
  };

  return (
    <aside className={`${chrome.panel} ${styles.panel}`}>
      <h2 className={chrome.panelTitle}>Telemetry</h2>
      <div className={styles.readouts}>
        <ReadoutRow
          label="Ground coverage"
          value={metrics.coverage === undefined ? null : metrics.coverage}
          format={(v) => `${(v * 100).toFixed(1)} %`}
          tip="Share of ground targets the swarm can observe. The primary mission metric: stable before failure, sharp drop at failure, recovery after replanning (spec 7.5)."
        />
        <ReadoutRow
          label="Minimum separation"
          value={metrics.minSep}
          format={(v) => `${v.toFixed(1)} m`}
          tip="Distance between the two closest satellites. Watched against the session's first measured clearance — a dip toward it is collision risk (spec 7.5)."
          context={minSepRef === null ? undefined : `reference ${minSepRef.toFixed(0)} m`}
        />
        <ReadoutRow
          label="Mission health score"
          value={health}
          format={(v) => `${v.toFixed(0)} / 100`}
          tip="One judge-facing number: 0.5 x coverage + 0.3 x formation quality + 0.2 x safety, computed only from measured inputs (spec 8.7)."
          context={band === null ? undefined : `${band} band`}
        />
        <ReadoutRow
          label="Satellites active / failed"
          value={hasSats ? `${active} active · ${failed} failed` : null}
          tip="Live fleet health from sats[].status — how many satellites are flying versus failed; the degradation picture at a glance (spec 7.5)."
        />
        <ReadoutRow
          label="Detection latency"
          value={metrics.detectionLatencyS}
          format={(v) => `${v.toFixed(2)} s`}
          tip="t_detect − t_fail: how quickly the swarm flagged the failure after injection (spec 7.5)."
        />
        <ReadoutRow
          label="Delta-v used (sum)"
          value={hasSats ? dvTotal : null}
          format={(v) => `${v.toFixed(2)} m/s`}
          tip="Sum of dv_used across all satellites — the thrust budget the mission has spent so far (spec 7.5)."
        />
      </div>

      <div role="tablist" aria-label="Telemetry charts" className={styles.tabs} onKeyDown={onTabKeyDown}>
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`telemetry-tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls="telemetry-chart-panel"
            tabIndex={tab === t.id ? 0 : -1}
            className={styles.tab}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div
        role="tabpanel"
        id="telemetry-chart-panel"
        aria-labelledby={`telemetry-tab-${tab}`}
        className={styles.chartPanel}
      >
        {tab === "coverage" && <GroundCoverageChart />}
        {tab === "deviation" && <FormationDeviationChart />}
        {tab === "separation" && <InterSatDistanceChart />}
        {tab === "dv" && <DvChart />}
        {tab === "health" && <MissionHealthScore />}
      </div>

      {/* §8.1 role reallocation — collapsible to keep the panel dense; the
          old-role column is still the simStore frame diff (no invented field). */}
      <details className={styles.roles}>
        <summary className={styles.rolesSummary}>Role reassignment</summary>
        <div className={styles.rolesBody}>
          <RoleTable />
        </div>
      </details>

      <h2 className={chrome.panelTitle}>Selected satellite</h2>
      <div className={styles.detail}>
        <SelectedSatellitePanel />
      </div>
    </aside>
  );
}
