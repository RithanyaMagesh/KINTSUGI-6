// Labeled numeric input for the builder (§13.3: visible label, ordinary
// borders, disabled state, keyboard focus ring from globals.css). Holds the
// raw text while editing so intermediate values ("0.", "-") survive typing;
// on blur/Enter it commits a finite number upward and snaps back to the
// committed value otherwise — no fake state, stable dimensions. Range bounds
// stay the server's authority (cubesat/scenario.py; its 422 detail is shown
// verbatim on the run button's error row).
import { useEffect, useState } from "react";
import chrome from "../../styles/chrome.module.css";
import styles from "./LivePage.module.css";

interface Props {
  id: string;
  label: string;
  value: number;
  onCommit: (v: number) => void;
  step?: string;
  min?: string;
  max?: string;
  /** Native tooltip; copy grounded in cubesat/scenario.py field descriptions
   * or docs/MASTER_PROMPT.md — no invented explanations. */
  tip?: string;
  disabled?: boolean;
}

export default function NumberField({
  id,
  label,
  value,
  onCommit,
  step,
  min,
  max,
  tip,
  disabled = false,
}: Props) {
  const [text, setText] = useState(String(value));
  useEffect(() => {
    setText(String(value));
  }, [value]);

  function commit(raw: string): void {
    const v = Number(raw);
    if (raw.trim() !== "" && Number.isFinite(v)) onCommit(v);
    setText(String(value)); // snap back to the committed value when input is junk
  }

  return (
    <div className={styles.field}>
      <label className={chrome.fieldLabel} htmlFor={id} title={tip}>
        {label}
      </label>
      <input
        id={id}
        className={`${chrome.input} ${styles.numberInput}`}
        type="number"
        inputMode="decimal"
        step={step}
        min={min}
        max={max}
        value={text}
        disabled={disabled}
        title={tip}
        aria-invalid={false}
        onChange={(e) => setText(e.target.value)}
        onBlur={(e) => commit(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit(e.currentTarget.value);
        }}
      />
    </div>
  );
}
