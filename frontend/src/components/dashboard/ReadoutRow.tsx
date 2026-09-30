// One readout row — §13.3: label (sans, muted) · value (mono, ink, 28px+).
// A null value renders the literal string "unmeasured" (repo invariant 1).
import styles from "./ReadoutRow.module.css";

interface Props {
  label: string;
  value: number | null | undefined;
  format: (v: number) => string;
}

export default function ReadoutRow({ label, value, format }: Props) {
  return (
    <div className={styles.row}>
      <span className={styles.label}>{label}</span>
      <span className={styles.value}>
        {value === null || value === undefined ? "unmeasured" : format(value)}
      </span>
    </div>
  );
}
