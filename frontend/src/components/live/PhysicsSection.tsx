// Physics + controls fieldset for the builder (extracted to keep
// ScenarioBuilder under the ~300-line style rule). Data-driven: every labeled
// number input is one FIELD_DEFS entry, so the form stays uniform and each
// label/tooltip is grounded in cubesat/scenario.py field descriptions or
// docs/MASTER_PROMPT.md — no invented explanations. Gains and the sensor grid
// collapse into the "Advanced physics" details (collapsed by default, per the
// live-page brief).
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
    label: "a_max (m/s²)",
    step: "0.005",
    min: "0.0001",
    tip: "Thrust saturation. 0.01 m/s² is the documented engine default — cold-gas class for an ~8 kg CubeSat (MASTER_PROMPT 3.4, labeled assumption).",
  },
  {
    key: "seed",
    id: "builder-seed",
    label: "Seed",
    step: "1",
    min: "0",
    tip: "RNG seed. Same scenario + seed gives a byte-identical log (repo invariant 2).",
  },
  {
    key: "speed",
    id: "builder-speed",
    label: "Speed (×)",
    step: "10",
    min: "1",
    tip: "Wire playback multiplier; the backend default is 100 (cubesat/wire.py StartRequest).",
  },
  {
    key: "durationS",
    id: "builder-duration",
    label: "Duration (s)",
    step: "100",
    min: "1",
    tip: "Simulated duration in seconds (cubesat/scenario.py duration_s).",
  },
  {
    key: "dtS",
    id: "builder-dt",
    label: "dt (s)",
    step: "0.5",
    min: "0.1",
    max: "10",
    tip: "Fixed integration step, seconds; the validator allows 0 < dt <= 10 (cubesat/scenario.py).",
  },
];

const ADVANCED_FIELDS: FieldDef[] = [
  {
    key: "wn",
    id: "builder-wn",
    label: "wn (rad/s)",
    step: "0.005",
    min: "0.0001",
    tip: "PD natural frequency, rad/s (cubesat/scenario.py Gains).",
  },
  {
    key: "zeta",
    id: "builder-zeta",
    label: "zeta",
    step: "0.1",
    min: "0.1",
    tip: "PD damping ratio (cubesat/scenario.py Gains).",
  },
  {
    key: "fovHalfAngleDeg",
    id: "builder-fov",
    label: "Imager FOV half-angle (deg)",
    step: "0.5",
    min: "0.1",
    max: "45",
    tip: "Imager half field of view, degrees; 0 < fov <= 45 (cubesat/scenario.py Sensor).",
  },
  {
    key: "gridStepKm",
    id: "builder-gridstep",
    label: "Grid step (km)",
    step: "0.5",
    min: "0.1",
    tip: "Target grid spacing in the (y, z) plane, km (cubesat/scenario.py Sensor).",
  },
  {
    key: "gridExtentKm",
    id: "builder-gridextent",
    label: "Grid extent (km)",
    step: "5",
    min: "1",
    tip: "Half-extent of the square target grid, km (cubesat/scenario.py Sensor).",
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
      <legend className={chrome.panelTitle}>Physics and controls</legend>
      <div className={styles.fieldGrid}>{renderFields(MAIN_FIELDS, values, onNumber, disabled)}</div>
      <details className={styles.advanced}>
        <summary className={styles.advancedSummary}>Advanced physics</summary>
        <div className={styles.fieldGrid}>
          {renderFields(ADVANCED_FIELDS, values, onNumber, disabled)}
        </div>
      </details>
    </fieldset>
  );
}
