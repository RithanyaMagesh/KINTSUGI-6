import { useEffect, useState } from "react";
import { backend } from "../../api/backend";
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

  return (
    <aside className={`${chrome.panel} ${styles.panel}`}>
      <h2 className={chrome.panelTitle}>Scenario</h2>
      <ScenarioSelector
        scenarios={scenarios}
        selected={selected}
        loading={loading}
        error={loadError}
        onSelect={setSelected}
      />
      <SimulationControls scenario={selected || null} />
      <FailureInjectionPanel />
      <h2 className={chrome.panelTitle}>Satellites</h2>
      <SatelliteList />
    </aside>
  );
}
