// One editable failure row for the builder's failures table (extracted to
// keep ScenarioBuilder under the ~300-line style rule). Mode option text
// carries the engine's one-line description (cubesat/scenario.py
// FailureMode docstring); the time input holds raw text while editing and
// snaps back to the committed value on junk.
import { useState } from "react";
import chrome from "../../styles/chrome.module.css";
import { MODE_DESCRIPTION, type FailureMode, type FailureRow } from "./scenarioDraft";
import { faultLabel } from "./hudFormat";
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
  const [degradeText, setDegradeText] = useState(String(row.degrade_s ?? 600));

  // Sync from the row when the seat list shrinks or the row is edited elsewhere.
  const [seenT, setSeenT] = useState(row.t);
  if (seenT !== row.t) {
    setSeenT(row.t);
    setTText(String(row.t));
  }

  const [seenDegrade, setSeenDegrade] = useState(row.degrade_s);
  if (seenDegrade !== row.degrade_s) {
    setSeenDegrade(row.degrade_s);
    setDegradeText(String(row.degrade_s ?? 600));
  }

  function commitT(): void {
    const v = Number(tText);
    if (tText.trim() !== "" && Number.isFinite(v)) onChange({ t: Math.max(0, v) });
    setTText(String(row.t)); // junk snaps back to the committed value
  }

  function commitDegrade(): void {
    const v = Number(degradeText);
    if (degradeText.trim() !== "" && Number.isFinite(v)) {
      onChange({ degrade_s: Math.max(0, v) });
    }
    setDegradeText(String(row.degrade_s ?? 600));
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
          aria-label={`Fault for SAT-${row.satId + 1}: ${MODE_DESCRIPTION[row.mode]}`}
          value={row.mode}
          disabled={disabled}
          onChange={(e) => {
            const nextMode = e.target.value as FailureMode;
            onChange({
              mode: nextMode,
              degrade_s: nextMode === "EPS_DEGRADE" ? (row.degrade_s ?? 600) : undefined,
            });
          }}
        >
          {(Object.keys(MODE_DESCRIPTION) as FailureMode[]).map((m) => (
            <option key={m} value={m}>
              {faultLabel(m)}
            </option>
          ))}
        </select>
        {row.mode === "EPS_DEGRADE" && (
          <input
            className={`${chrome.input} ${styles.cellInput}`}
            type="number"
            min="0"
            step="10"
            value={degradeText}
            disabled={disabled}
            placeholder="Fade (s)"
            title="Fade time in seconds"
            aria-label={`Fade time in seconds for SAT-${row.satId + 1}`}
            onChange={(e) => setDegradeText(e.target.value)}
            onBlur={commitDegrade}
            style={{ marginTop: "4px" }}
          />
        )}
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
