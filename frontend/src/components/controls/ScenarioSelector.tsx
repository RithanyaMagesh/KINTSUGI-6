// Scenario dropdown — reads GET /scenarios (the backend lists
// data/scenarios/*.json). Loading, empty and error states keep stable
// dimensions (§13.3).
import chrome from "../../styles/chrome.module.css";
import styles from "./ScenarioSelector.module.css";

interface Props {
  scenarios: string[];
  selected: string;
  loading: boolean;
  error: string | null;
  onSelect: (name: string) => void;
}

export default function ScenarioSelector({ scenarios, selected, loading, error, onSelect }: Props) {
  return (
    <div className={styles.group}>
      <label className={chrome.fieldLabel} htmlFor="scenario-select">
        Scenario file
      </label>
      <select
        id="scenario-select"
        className={chrome.select}
        value={selected}
        disabled={loading || scenarios.length === 0}
        onChange={(e) => onSelect(e.target.value)}
      >
        {loading && <option value="">Loading scenarios…</option>}
        {!loading && scenarios.length === 0 && <option value="">No scenarios found</option>}
        {scenarios.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </select>
      {error !== null && <p className={chrome.errorText}>{error}</p>}
      {error !== null && (
        <p className={chrome.hint}>Start the backend, then reload this page to retry.</p>
      )}
    </div>
  );
}
