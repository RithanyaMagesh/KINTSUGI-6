// One editable failure row for the builder's failures table (extracted to
// keep ScenarioBuilder under the ~300-line style rule). Mode option text
// carries the engine's one-line description (cubesat/scenario.py
// FailureMode docstring); the time input holds raw text while editing and
// snaps back to the committed value on junk.
import { useState } from "react";
import chrome from "../../styles/chrome.module.css";
import { MODE_DESCRIPTION, type FailureMode, type FailureRow } from "./scenarioDraft";
import styles from "./LivePage.module.css";

interface Props {
  row: FailureRow;
  maxSat: number;
  disabled: boolean;
  onChange: (patch: Partial<FailureRow>) => void;
  onRemove: () => void;
}

export default function FailureRowView({ row, maxSat, disabled, onChange, onRemove }: Props) {
  const [tText, setTText] = useState(String(row.t));
  // Sync from the row when the seat list shrinks or the row is edited elsewhere.
  const [seenT, setSeenT] = useState(row.t);
  if (seenT !== row.t) {
    setSeenT(row.t);
    setTText(String(row.t));
  }

  function commitT(): void {
    const v = Number(tText);
    if (tText.trim() !== "" && Number.isFinite(v)) onChange({ t: Math.max(0, v) });
    setTText(String(row.t)); // junk snaps back to the committed value
  }

  return (
    <tr>
      <td>
        <select
          className={chrome.select}
          aria-label={`Failure satellite (SAT-${row.satId + 1})`}
          value={row.satId}
          disabled={disabled}
          onChange={(e) => onChange({ satId: Number(e.target.value) })}
        >
          {Array.from({ length: maxSat }, (_, i) => (
            <option key={i} value={i}>
              {`SAT-${i + 1}`}
            </option>
          ))}
        </select>
      </td>
      <td>
        <input
          className={`${chrome.input} ${styles.cellInput}`}
          type="number"
          min="0"
          step="1"
          value={tText}
          disabled={disabled}
          aria-label={`Failure time in seconds for SAT-${row.satId + 1}`}
          onChange={(e) => setTText(e.target.value)}
          onBlur={commitT}
        />
      </td>
      <td>
        <select
          className={chrome.select}
          aria-label={`Failure mode for SAT-${row.satId + 1}: ${MODE_DESCRIPTION[row.mode]}`}
          value={row.mode}
          disabled={disabled}
          onChange={(e) => onChange({ mode: e.target.value as FailureMode })}
        >
          {(Object.keys(MODE_DESCRIPTION) as FailureMode[]).map((m) => (
            <option key={m} value={m}>
              {`${m} — ${MODE_DESCRIPTION[m]}`}
            </option>
          ))}
        </select>
      </td>
      <td>
        <button
          type="button"
          className={chrome.btn}
          disabled={disabled}
          aria-label={`Remove failure of SAT-${row.satId + 1} at t=${row.t} s`}
          onClick={onRemove}
        >
          Remove
        </button>
      </td>
    </tr>
  );
}
