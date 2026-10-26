// RightPanel — View-Aware Telemetry & Inspector.
// Adapts automatically to Simplified vs. Advanced view mode:
// - Simplified mode (default): 3 core readout rows (Ground coverage, Minimum
//   separation, Satellites active / failed), the Ground coverage chart, and a
//   compact Selected satellite card.
// - Advanced mode: All 6 readout rows + 4 strictly tabbed inspector panels
//   (Charts | Satellite detail | Role reassignment | Events & AI risk) so
//   panels never stack on top of each other.
// Every value traces strictly to the stream; absent values render "unmeasured"
// (repo invariant 1). Zero raw hex (§13.1).
import { useState } from "react";
import { useSimStore } from "../../stores/simStore";
import { useHistoryStore } from "../../stores/historyStore";
import { useRecoveryStore, selectLatestFailure } from "../../stores/recoveryStore";
import { useUiStore } from "../../stores/uiStore";
import { healthBand } from "../../utils/health";
import ReadoutRow from "../dashboard/ReadoutRow";
import GroundCoverageChart from "../dashboard/GroundCoverageChart";
import FormationDeviationChart from "../dashboard/FormationDeviationChart";
import InterSatDistanceChart from "../dashboard/InterSatDistanceChart";
import DvChart from "../dashboard/DvChart";
import MissionHealthScore from "../dashboard/MissionHealthScore";
import RoleTable from "../dashboard/RoleTable";
import RecoveryLog from "../recovery/RecoveryLog";
import EventLog from "../events/EventLog";
import RiskPanel from "../live/RiskPanel";
import SelectedSatellitePanel from "../satellites/SelectedSatellitePanel";
import chrome from "../../styles/chrome.module.css";
import styles from "./RightPanel.module.css";

const INSPECTOR_TABS = [
  { id: "charts", label: "Charts" },
  { id: "satellite", label: "Satellite" },
  { id: "reassignment", label: "Reassignment" },
  { id: "events", label: "Events & AI" },
] as const;

type InspectorTabId = (typeof INSPECTOR_TABS)[number]["id"];

const CHART_TABS = [
  { id: "coverage", label: "Coverage" },
  { id: "separation", label: "Separation" },
  { id: "deviation", label: "Deviation" },
  { id: "dv", label: "Delta-v" },
  { id: "health", label: "Health" },
] as const;

type ChartTabId = (typeof CHART_TABS)[number]["id"];

export default function RightPanel() {
  const viewMode = useUiStore((s) => s.viewMode);
  const metrics = useSimStore((s) => s.metrics);
  const satellites = useSimStore((s) => s.satellites);
  const latestFailure = useRecoveryStore(selectLatestFailure);
  const [inspectorTab, setInspectorTab] = useState<InspectorTabId>("charts");
  const [chartTab, setChartTab] = useState<ChartTabId>("coverage");

  const dvTotal = satellites.reduce((sum, s) => sum + s.dv_used, 0);
  const hasSats = satellites.length > 0;

  const failed = satellites.reduce((n, s) => (s.status === "failed" ? n + 1 : n), 0);
  const active = satellites.length - failed;

  const health = useHistoryStore((s) =>
    s.samples.length > 0 ? s.samples[s.samples.length - 1].health : null,
  );
  const minSepRef = useHistoryStore((s) => s.minSepRef);
  const band = health === null ? null : healthBand(health);

  const preCov = latestFailure?.coverage.pre ?? null;
  const covNow = metrics.coverage ?? null;
  let covContext: string | undefined;
  if (preCov !== null && covNow !== null) {
    const diffPts = (covNow - preCov) * 100;
    const sign = diffPts >= 0 ? "+" : "";
    covContext = `${sign}${diffPts.toFixed(1)} pts vs ${(preCov * 100).toFixed(1)}% pre-fault`;
  }

  const sepContext =
    minSepRef !== null
      ? `2000 m keep-out · ref ${minSepRef.toFixed(0)} m`
      : "2000 m keep-out floor";

  const latencyVal = metrics.detectionLatencyS ?? latestFailure?.detectionLatencyS ?? null;

  return (
    <aside className={`${chrome.panel} ${styles.panel}`} aria-label="Swarm telemetry">
      <div className={styles.titleRow}>
        <h2 className={chrome.panelTitle}>Swarm telemetry</h2>
        <span className={styles.fleetTag}>
          {hasSats ? `${active}/${satellites.length} active` : "Standby"}
        </span>
      </div>

      {/* Primary Readout Rows: 3 in Simplified mode, 6 in Advanced mode */}
      <div className={styles.readouts}>
        <ReadoutRow
          label="Ground coverage"
          value={metrics.coverage === undefined ? null : metrics.coverage}
          format={(v) => `${(v * 100).toFixed(1)} %`}
          tip="Share of ground targets observed by healthy imagers. Drops when an imager fails; recovers as survivors re-phase around the formation (spec 7.5)."
          context={covContext}
        />
        <ReadoutRow
          label="Minimum separation"
          value={metrics.minSep}
          format={(v) => `${v.toFixed(0)} m`}
          tip="Closest pair distance across the swarm (including coasting dead satellites). Must remain above the 2000 m keep-out safety floor (spec 7.5)."
          context={sepContext}
        />
        <ReadoutRow
          label="Satellites active / failed"
          value={hasSats ? active : null}
          format={() => `${active} / ${failed}`}
          tip="Count of healthy/reconfiguring satellites vs failed satellites."
        />

        {viewMode === "advanced" && (
          <>
            <ReadoutRow
              label="Mission health score"
              value={health}
              format={(v) => `${v.toFixed(0)} / 100${band ? ` (${band})` : ""}`}
              tip="Composite 0-100 score combining ground coverage, formation slot tracking, and separation margin."
            />
            <ReadoutRow
              label="Detection latency"
              value={latencyVal}
              format={(v) => `${v.toFixed(1)} s`}
              tip="t_detect − t_fail: time from fault injection until 3 missed heartbeats trigger autonomous Hungarian replanning (spec 7.5)."
            />
            <ReadoutRow
              label="Delta-v used (sum)"
              value={hasSats ? dvTotal : null}
              format={(v) => `${v.toFixed(2)} m/s`}
              tip="Total propellant (Δv) burned by saturated PD thrusters across all satellites during slot reconfiguration (spec 7.5)."
            />
          </>
        )}
      </div>

      {/* Simplified Mode: Primary Coverage Chart + Selected Satellite Summary */}
      {viewMode === "simplified" ? (
        <div className={styles.simplifiedBody}>
          <div className={styles.chartBox}>
            <GroundCoverageChart />
          </div>
          <div className={styles.detailBox}>
            <h3 className={chrome.panelTitle}>Selected satellite</h3>
            <SelectedSatellitePanel />
          </div>
        </div>
      ) : (
        /* Advanced Mode: Strictly Tabbed Engineering Inspector (Zero Stacking) */
        <div className={styles.advancedBody}>
          <div role="tablist" aria-label="Engineering inspector tabs" className={styles.tabs}>
            {INSPECTOR_TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                role="tab"
                id={`inspector-tab-${t.id}`}
                aria-selected={inspectorTab === t.id}
                className={styles.tab}
                onClick={() => setInspectorTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div
            role="tabpanel"
            aria-labelledby={`inspector-tab-${inspectorTab}`}
            className={styles.tabContent}
          >
            {inspectorTab === "charts" && (
              <div className={styles.chartsSection}>
                <div role="tablist" aria-label="Telemetry chart type" className={styles.subTabs}>
                  {CHART_TABS.map((ct) => (
                    <button
                      key={ct.id}
                      type="button"
                      role="tab"
                      aria-selected={chartTab === ct.id}
                      className={styles.subTab}
                      onClick={() => setChartTab(ct.id)}
                    >
                      {ct.label}
                    </button>
                  ))}
                </div>
                {chartTab === "coverage" && <GroundCoverageChart />}
                {chartTab === "separation" && <InterSatDistanceChart />}
                {chartTab === "deviation" && <FormationDeviationChart />}
                {chartTab === "dv" && <DvChart />}
                {chartTab === "health" && <MissionHealthScore />}
              </div>
            )}

            {inspectorTab === "satellite" && (
              <div className={styles.detail}>
                <SelectedSatellitePanel />
              </div>
            )}

            {inspectorTab === "reassignment" && (
              <div className={styles.reassignmentSection}>
                <RoleTable />
                <div className={styles.sectionDivider} />
                <RecoveryLog />
              </div>
            )}

            {inspectorTab === "events" && (
              <div className={styles.eventsSection}>
                <RiskPanel />
                <div className={styles.sectionDivider} />
                <EventLog />
              </div>
            )}
          </div>
        </div>
      )}
    </aside>
  );
}
