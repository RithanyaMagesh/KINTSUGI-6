// Full-screen live HUD — the Telemetry drawer (T). Everything the stream
// carries, one tab at a time: mission parameters, the per-satellite table,
// three charts, the event log and the role changes. Values are measured or
// shown as a dash (repo invariant 1).
import { useEffect, useState } from "react";
import { useSimStore } from "../../stores/simStore";
import { useRecoveryStore, selectLatestFailure } from "../../stores/recoveryStore";
import { useHistoryStore } from "../../stores/historyStore";
import { useUiStore } from "../../stores/uiStore";
import FormationDeviationChart from "../dashboard/FormationDeviationChart";
import SelectedSatellitePanel from "../satellites/SelectedSatellitePanel";
import RiskPanel from "./RiskPanel";
import { missionStateColor } from "../../utils/colors";
import GroundCoverageChart from "../dashboard/GroundCoverageChart";
import InterSatDistanceChart from "../dashboard/InterSatDistanceChart";
import DvChart from "../dashboard/DvChart";
import RoleTable from "../dashboard/RoleTable";
import RecoveryLog from "../recovery/RecoveryLog";
import EventLog from "../events/EventLog";
import FleetTable from "./FleetTable";
import { clock, faultLabel, km, slotLabel, stateLabel } from "./hudFormat";
import styles from "./ImmersiveLive.module.css";

const TABS = [
  { id: "mission", label: "Mission" },
  { id: "fleet", label: "Satellites" },
  { id: "selected", label: "Selected" },
  { id: "charts", label: "Charts" },
  { id: "events", label: "Events" },
  { id: "roles", label: "Roles" },
] as const;
type TabId = (typeof TABS)[number]["id"];

const CHARTS = [
  { id: "coverage", label: "Coverage" },
  { id: "separation", label: "Separation" },
  { id: "deviation", label: "Formation error" },
  { id: "dv", label: "Fuel" },
] as const;
type ChartId = (typeof CHARTS)[number]["id"];

const DASH = "–";
const POLICY_NAME: Record<string, string> = {
  hungarian: "Best-fit reassignment",
  even_split: "Even spacing",
  hungarian_keepout: "Best-fit, avoiding the dead satellite",
};
const pct = (v: number | null | undefined) => (v == null ? DASH : `${(v * 100).toFixed(1)}%`);
const meters = (v: number | null | undefined) => (v == null ? DASH : v >= 1000 ? `${km(v)} km` : `${v.toFixed(0)} m`);

function Row({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className={styles.paramRow}>
      <dt>{label}</dt>
      <dd style={tone !== undefined ? { color: tone } : undefined}>{value}</dd>
    </div>
  );
}

function MissionTab() {
  const s = useSimStore();
  const failure = useRecoveryStore(selectLatestFailure);
  const failures = useRecoveryStore((r) => r.failures.length);
  const sats = s.satellites;
  const lost = sats.filter((x) => x.status === "failed").length;
  const dv = sats.reduce((a, x) => a + x.dv_used, 0);
  const maxDv = sats.reduce((a, x) => Math.max(a, x.dv_used), 0);
  const holder = (role: string) => sats.find((x) => x.role === role && x.status !== "failed")?.id ?? "Vacant";
  const latency = s.metrics.detectionLatencyS ?? failure?.detectionLatencyS ?? null;
  const sepRef = useHistoryStore((h) => h.minSepRef);
  const pre = failure?.coverage.pre ?? null;
  const cov = s.metrics.coverage ?? null;
  const covVsPre =
    cov !== null && pre !== null
      ? `${cov >= pre ? "+" : "−"}${Math.abs((cov - pre) * 100).toFixed(1)} pts`
      : DASH;
  const roleCounts: Record<string, number> = {};
  for (const x of sats) {
    if (x.status === "failed") continue;
    const r = x.role.startsWith("sensor") || x.role.startsWith("imager") ? "imager" : x.role;
    roleCounts[r] = (roleCounts[r] ?? 0) + 1;
  }
  const rolesText = Object.keys(roleCounts)
    .sort()
    .map((r) => `${roleCounts[r]} ${r}`)
    .join(", ");

  return (
    <div className={styles.tabBody}>
      <h3 className={styles.groupTitle}>Now</h3>
      <dl className={styles.params}>
        <Row label="Mission state" value={stateLabel(s.missionState)} tone={missionStateColor(s.missionState)} />
        <Row label="Simulation time" value={s.simTime === null ? DASH : `${clock(s.simTime)}  (${s.simTime.toFixed(0)} s)`} />
        <Row label="Ground coverage" value={pct(s.metrics.coverage)} />
        <Row label="Coverage vs before the fault" value={covVsPre} />
        <Row label="Closest approach" value={meters(s.metrics.minSep)} />
        <Row label="Keep-out floor" value={meters(s.minSepM)} />
        <Row label="Closest approach at start" value={meters(sepRef)} />
      </dl>

      <h3 className={styles.groupTitle}>Swarm</h3>
      <dl className={styles.params}>
        <Row label="Satellites" value={sats.length === 0 ? DASH : `${sats.length - lost} flying, ${lost} lost`} />
        <Row label="Flying, by role" value={sats.length === 0 ? DASH : rolesText || DASH} />
        <Row label="Leader" value={sats.length === 0 ? DASH : holder("leader")} />
        <Row label="Downlink" value={sats.length === 0 ? DASH : holder("downlink")} />
        <Row label="Fuel spent, total" value={sats.length === 0 ? DASH : `${dv.toFixed(2)} m/s`} />
        <Row label="Fuel spent, most by one" value={sats.length === 0 ? DASH : `${maxDv.toFixed(2)} m/s`} />
      </dl>

      <h3 className={styles.groupTitle}>Last failure</h3>
      {failure === null ? (
        <p className={styles.empty}>No failure yet. Inject one from Setup, or click a satellite.</p>
      ) : (
        <dl className={styles.params}>
          <Row label="Satellite" value={failure.satId} tone="var(--status-failed)" />
          <Row label="Fault" value={faultLabel(failure.mode ?? undefined) || DASH} />
          <Row label="Failed at" value={clock(failure.tFail)} />
          <Row label="Detected after" value={latency === null ? DASH : `${latency.toFixed(1)} s`} />
          <Row label="Slot left empty" value={failure.vacatedSlot ? slotLabel(failure.vacatedSlot) : DASH} />
          <Row label="Coverage before" value={pct(failure.coverage.pre)} />
          <Row label="Coverage low point" value={pct(failure.coverage.min)} />
          <Row
            label="Recovered"
            value={failure.recovered ? "Yes" : "Not yet"}
            tone={failure.recovered ? "var(--status-repaired)" : undefined}
          />
          <Row label="Failures this run" value={String(failures)} />
        </dl>
      )}

      <h3 className={styles.groupTitle}>Run</h3>
      <dl className={styles.params}>
        <Row label="Scenario" value={s.scenario ?? DASH} />
        <Row label="Seed" value={s.seed === null ? DASH : String(s.seed)} />
        <Row label="Recovery method" value={s.policy === null ? DASH : (POLICY_NAME[s.policy] ?? s.policy)} />
        <Row
          label="Last replan"
          value={
            s.lastReassignment === null
              ? DASH
              : s.lastReassignment.keptFormation
                ? "Kept formation, no move"
                : (POLICY_NAME[s.lastReassignment.method ?? ""] ?? s.lastReassignment.method ?? DASH)
          }
        />
        <Row label="Mode" value={s.mode === "live" ? "Live" : s.mode === "replay" ? "Replay" : "Stopped"} />
        <Row
          label="Backend"
          value={s.connection === "connected" ? "Connected" : s.connection === "reconnecting" ? "Reconnecting" : "Disconnected"}
          tone={s.connection === "connected" ? "var(--status-nominal)" : "var(--status-failed)"}
        />
      </dl>
    </div>
  );
}

export default function TelemetryDrawer() {
  const [tab, setTab] = useState<TabId>("mission");
  const selectedId = useUiStore((u) => u.selectedSatelliteId);
  // Clicking a satellite in 3D jumps straight to its details.
  useEffect(() => {
    if (selectedId !== null) setTab("selected");
  }, [selectedId]);
  const [chart, setChart] = useState<ChartId>("coverage");

  return (
    <div className={styles.drawerInner}>
      <div role="tablist" aria-label="Telemetry" className={styles.tabs}>
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={styles.tab}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" className={styles.tabScroll}>
        {tab === "mission" && <MissionTab />}
        {tab === "fleet" && <FleetTable />}
        {tab === "selected" &&
          (selectedId === null ? (
            <p className={styles.empty}>Click a satellite in the 3D view or the Satellites tab.</p>
          ) : (
            <SelectedSatellitePanel />
          ))}
        {tab === "charts" && (
          <div className={styles.tabBody}>
            <div role="tablist" aria-label="Chart" className={styles.subTabs}>
              {CHARTS.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  role="tab"
                  aria-selected={chart === c.id}
                  className={styles.seg}
                  onClick={() => setChart(c.id)}
                >
                  {c.label}
                </button>
              ))}
            </div>
            {chart === "coverage" && <GroundCoverageChart />}
            {chart === "separation" && <InterSatDistanceChart />}
            {chart === "deviation" && <FormationDeviationChart />}
            {chart === "dv" && <DvChart />}
          </div>
        )}
        {tab === "events" && (
          <div className={styles.tabBody}>
            <RiskPanel />
            <EventLog />
          </div>
        )}
        {tab === "roles" && (
          <div className={styles.tabBody}>
            <RoleTable />
            <RecoveryLog />
          </div>
        )}
      </div>
    </div>
  );
}
