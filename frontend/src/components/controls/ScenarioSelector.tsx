// Scenario dropdown — lists GET /scenarios (the backend lists
// data/scenarios/*.json). "Add your own scenario…" opens CustomScenarioModal;
// a successful upload returns the refreshed listing and the saved file name
// (cubesat/api.py /scenarios/upload), which are merged into the options and
// selected — without touching LeftPanel's fetch state. Loading, empty and
// error states keep stable dimensions (§13.3).
import { useState } from "react";
import CustomScenarioModal from "./CustomScenarioModal";
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
  const [uploaded, setUploaded] = useState<string[]>([]);
  const [modalOpen, setModalOpen] = useState(false);

  // Uploaded files join the listing; dedupe keeps the props listing
  // authoritative whenever LeftPanel refetches.
  const seen = new Set(scenarios);
  const merged = [...scenarios];
  for (const file of uploaded) {
    if (!seen.has(file)) {
      seen.add(file);
      merged.push(file);
    }
  }

  function handleUploaded(filename: string | null, listing: string[] | null): void {
    if (listing !== null) {
      setUploaded(listing); // union below absorbs any stale props listing
    } else if (filename !== null) {
      setUploaded([...uploaded, filename]);
    }
    if (filename !== null) onSelect(filename);
    setModalOpen(false);
  }

  return (
    <div className={styles.group}>
      <label className={chrome.fieldLabel} htmlFor="scenario-select">
        Scenario file
      </label>
      <select
        id="scenario-select"
        className={chrome.select}
        value={selected}
        disabled={loading || merged.length === 0}
        onChange={(e) => onSelect(e.target.value)}
      >
        {loading && <option value="">Loading scenarios…</option>}
        {!loading && merged.length === 0 && <option value="">No scenarios found</option>}
        {merged.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </select>
      {error !== null && <p className={chrome.errorText}>{error}</p>}
      {error !== null && (
        <p className={chrome.hint}>Start the backend, then reload this page to retry.</p>
      )}
      <button className={chrome.btn} onClick={() => setModalOpen(true)}>
        Add your own scenario…
      </button>
      {modalOpen && (
        <CustomScenarioModal onClose={() => setModalOpen(false)} onUploaded={handleUploaded} />
      )}
    </div>
  );
}
