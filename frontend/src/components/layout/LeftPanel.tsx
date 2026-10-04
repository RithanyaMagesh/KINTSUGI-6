// Left panel — §12.1 scenario panel: a Mission readout block first (scenario,
// seed, satellite counts, counts by role — every value straight from the
// simStore stream or derived from streamed statuses/roles; absent values
// render "unmeasured", repo invariant 1), then the console controls, then the
// satellite list hosted unchanged (another agent owns SatelliteList).
import { useEffect, useState } from "react";
import { backend } from "../../api/backend";
import { useSimStore } from "../../stores/simStore";
import { UNMEASURED } from "../../utils/format";
import ScenarioSelector from "../controls/ScenarioSelector";
import SimulationControls from "../controls/SimulationControls";
import FailureInjectionPanel from "../controls/FailureInjectionPanel";
import SatelliteList from "../satellites/SatelliteList";
import chrome from "../../styles/chrome.module.css";
import styles from "./LeftPanel.module.css";

export default function LeftPanel() {
  const [scenarios, setScenarios] = useState<string[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const satellites = useSimStore((s) => s.satellites);
  const scenario = useSimStore((s) => s.scenario);
  const seed = useSimStore((s) => s.seed);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchScenarios();
    return () => {
      cancelled = true;
    };

    async function fetchScenarios() {
      try {
        const data = await backend.scenarios();
        if (!cancelled) {
          setScenarios(data.scenarios);
          setLoadError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : "Scenario listing failed");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
  }, []);

  // Counts derived from streamed statuses/roles only. Deterministic ordering
  // (sorted by role name) — no map-order dependence (invariant 2).
  const hasSats = satellites.length > 0;
  const healthy = satellites.filter((s) => s.status === "healthy").length;
  const failed = satellites.filter((s) => s.status === "failed").length;
  const roleCounts = new Map<string, number>();
  for (const sat of satellites) {
    roleCounts.set(sat.role, (roleCounts.get(sat.role) ?? 0) + 1);
  }
  const rolesText = [...roleCounts.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([role, count]) => `${role} ${count}`)
    .join(" · ");

  return (
    <aside className={`${chrome.panel} ${styles.panel}`}>
      <section className={styles.block} aria-label="Mission">
        <h2 className={chrome.panelTitle}>Mission</h2>
        <div className={styles.rows}>
          <div className={styles.row}>
            <span className={styles.rowLabel}>Scenario</span>
            <span className={styles.rowValue}>{scenario ?? UNMEASURED}</span>
          </div>
          <div className={styles.row}>
            <span className={styles.rowLabel}>Seed</span>
            <span className={styles.rowValue}>{seed === null ? UNMEASURED : String(seed)}</span>
          </div>
          <div className={styles.row}>
            <span className={styles.rowLabel}>Satellites healthy / failed</span>
            <span className={styles.rowValue}>
              {hasSats ? `${healthy} / ${failed}` : UNMEASURED}
            </span>
          </div>
          <div className={styles.row}>
            <span className={styles.rowLabel}>Satellites by role</span>
            <span className={styles.rowValue}>{hasSats ? rolesText : UNMEASURED}</span>
          </div>
        </div>
      </section>

      <section className={styles.block} aria-label="Controls">
        <h2 className={chrome.panelTitle}>Controls</h2>
        <ScenarioSelector
          scenarios={scenarios}
          selected={selected}
          loading={loading}
          error={loadError}
          onSelect={setSelected}
        />
        <SimulationControls scenario={selected || null} />
        <FailureInjectionPanel />
      </section>

      <section className={styles.block} aria-label="Satellites">
        <h2 className={chrome.panelTitle}>Satellites</h2>
        <SatelliteList />
      </section>
    </aside>
  );
}
