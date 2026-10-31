// One readout row — §13.3: label (sans, muted) left · value (mono, ink,
// 28px+) right, grouped in a table-like column — never a metric-card grid.
// A null/undefined value renders the literal string "unmeasured" (repo
// invariant 1). Optional `tip`: a one-liner that says what the metric means
// and why an operator watches it (no invented numbers), shown on hover and
// keyboard focus via a pure-CSS tooltip. Optional `context`: a small line
// under the value — never a substitute for the value itself.
import { useId } from "react";
import styles from "./ReadoutRow.module.css";

interface Props {
  label: string;
  value: number | string | null | undefined;
  format?: (v: number) => string;
  tip?: string;
  context?: string;
}

export default function ReadoutRow({ label, value, format, tip, context }: Props) {
  const tipId = useId();
  const hasValue = !(value === null || value === undefined || value === "");
  const shown = typeof value === "number" ? (format ? format(value) : String(value)) : value;

  const labelEl = (
    <span
      className={tip ? `${styles.label} ${styles.labelTip}` : styles.label}
      tabIndex={tip ? 0 : undefined}
      aria-describedby={tip ? tipId : undefined}
    >
      {label}
    </span>
  );

  return (
    <div className={styles.row}>
      {tip ? (
        <>
          {labelEl}
          <span role="tooltip" id={tipId} className={styles.tip}>
            {tip}
          </span>
        </>
      ) : (
        labelEl
      )}
      <span className={styles.valueWrap}>
        <span className={styles.value}>{hasValue ? shown : "unmeasured"}</span>
        {context !== undefined && hasValue ? (
          <span className={styles.context}>{context}</span>
        ) : null}
      </span>
    </div>
  );
}
