// Physics + controls fieldset for the builder (extracted to keep
// ScenarioBuilder under the ~300-line style rule). Data-driven: every labeled
// number input is one FIELD_DEFS entry, so the form stays uniform. Gains and
// the sensor grid collapse into a details block (collapsed by default).
import chrome from "../../styles/chrome.module.css";
import NumberField from "./NumberField";
import type { NumberValues } from "./scenarioDraft";
import styles from "./LivePage.module.css";

type NumberKey = keyof NumberValues;

interface FieldDef {
  key: NumberKey;
  id: string;
  label: string;
  step: string;
  min?: string;
  max?: string;
  tip: string;
}

const MAIN_FIELDS: FieldDef[] = [
  {
    key: "aMax",
    id: "builder-amax",
    label: "Max thrust (m/s²)",
    step: "0.005",
    min: "0.0001",
    tip: "The most acceleration a thruster can give. 0.01 m/s² is roughly a small cold-gas thruster on an 8 kg CubeSat.",
  },
  {
    key: "seed",
    id: "builder-seed",
    label: "Seed",
    step: "1",
    min: "0",
    tip: "Random seed. The same settings and seed always give the same run.",
  },
  {
    key: "speed",
    id: "builder-speed",
    label: "Speed (×)",
    step: "10",
    min: "1",
    tip: "How many times faster than real time the run plays.",
  },
  {
    key: "durationS",
    id: "builder-duration",
    label: "Duration (s)",
    step: "100",
    min: "1",
    tip: "How long the simulated run lasts, in seconds.",
  },
  {
    key: "dtS",
    id: "builder-dt",
    label: "Time step (s)",
    step: "0.5",
    min: "0.1",
    max: "10",
    tip: "Simulation time step, in seconds (up to 10).",
  },
];

const ADVANCED_FIELDS: FieldDef[] = [
  {
    key: "wn",
    id: "builder-wn",
    label: "Controller speed (rad/s)",
    step: "0.005",
    min: "0.0001",
    tip: "How quickly each satellite steers back toward its slot.",
  },
  {
    key: "zeta",
    id: "builder-zeta",
    label: "Controller damping",
    step: "0.1",
    min: "0.1",
    tip: "How much the steering avoids overshooting the slot; 1 means no overshoot.",
  },
  {
    key: "fovHalfAngleDeg",
    id: "builder-fov",
    label: "Imager FOV half-angle (deg)",
    step: "0.5",
    min: "0.1",
    max: "45",
    tip: "Half the imager's field of view, in degrees (up to 45).",
  },
  {
    key: "gridStepKm",
    id: "builder-gridstep",
    label: "Grid step (km)",
    step: "0.5",
    min: "0.1",
    tip: "Spacing of the ground points used to measure coverage, in km.",
  },
  {
    key: "gridExtentKm",
    id: "builder-gridextent",
    label: "Grid extent (km)",
    step: "5",
    min: "1",
    tip: "Half the width of the square ground area used to measure coverage, in km.",
  },
];

interface Props {
  values: NumberValues;
  onNumber: (key: NumberKey, v: number) => void;
  disabled: boolean;
}

function renderFields(
  defs: FieldDef[],
  values: NumberValues,
  onNumber: Props["onNumber"],
  disabled: boolean,
) {
  return defs.map((f) => (
    <NumberField
      key={f.id}
      id={f.id}
      label={f.label}
      value={values[f.key]}
      onCommit={(v) => onNumber(f.key, v)}
      step={f.step}
      min={f.min}
      max={f.max}
      tip={f.tip}
      disabled={disabled}
    />
  ));
}

export default function PhysicsSection({ values, onNumber, disabled }: Props) {
  return (
    <fieldset className={styles.group} disabled={disabled}>
      <legend className={chrome.panelTitle}>Physics</legend>
      <div className={styles.fieldGrid}>{renderFields(MAIN_FIELDS, values, onNumber, disabled)}</div>
      <details className={styles.advanced}>
        <summary className={styles.advancedSummary}>Controller and imager</summary>
        <div className={styles.fieldGrid}>
          {renderFields(ADVANCED_FIELDS, values, onNumber, disabled)}
        </div>
      </details>
    </fieldset>
  );
}
