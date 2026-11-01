// Per-shape facts for the formation picker. Every number comes from
// formationsReport.json, a copy of data/eval/formations_report.json
// (`shapes.<shape>`) plus the tank delta-v from cubesat/scenario_models.py
// (see README.md in this folder). Missing numbers read "unmeasured".
import report from "./formationsReport.json";
import styles from "./FormationFacts.module.css";

interface ShapeFacts {
  scenario?: string;
  cw_min_sep_m?: number | null;
  cw_worst_sep_any_along_track_drift_m?: number | null;
  cw_coverage?: number | null;
  hold_dv_per_orbit_max_sat_mps?: number | null;
  switch_from_cartwheel?: {
    feasible?: boolean | null;
    per_sat?: { sat: number; dv_l1_mps: number | null }[];
  };
}

const SHAPES = report.shapes as Record<string, ShapeFacts | undefined>;
const TANK_MPS: number | null =
  typeof report.tank_dv_mps === "number" ? report.tank_dv_mps : null;

function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

function metres(v: number | null | undefined): string {
  return isNum(v) ? `${Math.round(v).toLocaleString("en-US")} m` : "unmeasured";
}

function percent(v: number | null | undefined): string {
  return isNum(v) ? `${(v * 100).toFixed(1)} %` : "unmeasured";
}

function mps(v: number | null | undefined): string {
  return isNum(v) ? `${v.toFixed(2)} m/s` : "unmeasured";
}

export default function FormationFacts({ shape }: { shape: string }) {
  const f = SHAPES[shape];
  const base = SHAPES.cartwheel;
  if (f === undefined) {
    return (
      <div className={styles.facts} aria-label="Formation facts">
        <p className={styles.caption}>No report numbers for this shape: unmeasured.</p>
      </div>
    );
  }

  const coverageLoss =
    shape !== "cartwheel" &&
    isNum(f.cw_coverage) &&
    isNum(base?.cw_coverage) &&
    f.cw_coverage < base.cw_coverage;

  const drift = f.cw_worst_sep_any_along_track_drift_m;
  const perSat = f.switch_from_cartwheel?.per_sat ?? [];
  const allZero = perSat.length > 0 && perSat.every((p) => p.dv_l1_mps === 0);

  return (
    <div className={styles.facts} aria-label="Formation facts">
      <p className={styles.caption}>
        Report case: 6 satellites, 8 km amplitude (string: 8 km spacing). Your run may
        use other numbers.
      </p>
      <dl className={styles.list}>
        <div className={styles.row}>
          <dt>Closest approach</dt>
          <dd>{metres(f.cw_min_sep_m)}</dd>
        </div>
        <div className={styles.row}>
          <dt>Coverage</dt>
          <dd>
            {percent(f.cw_coverage)}
            {coverageLoss && (
              <span className={styles.lossBadge}>
                Less than cartwheel ({percent(base?.cw_coverage)})
              </span>
            )}
          </dd>
        </div>
        <div className={styles.row}>
          <dt>Fuel to hold, per orbit</dt>
          <dd>{mps(f.hold_dv_per_orbit_max_sat_mps)} for the hungriest satellite</dd>
        </div>
      </dl>

      <p className={styles.drift}>
        {!isNum(drift) ? (
          <span>Dead satellite drift: unmeasured.</span>
        ) : drift > 0 ? (
          <span className={styles.safe}>
            A drifting dead sat stays at least {metres(drift)} from every neighbour.
          </span>
        ) : (
          <span className={styles.hazard}>A drifting dead sat can reach a neighbour.</span>
        )}
      </p>

      <div className={styles.switch}>
        <p className={styles.switchTitle}>Fuel to switch from cartwheel</p>
        {perSat.length === 0 ? (
          <p className={styles.caption}>unmeasured</p>
        ) : allZero ? (
          <p className={styles.caption}>None: cartwheel is the starting shape.</p>
        ) : (
          <ul className={styles.bars}>
            {perSat.map((p) => {
              const frac =
                isNum(p.dv_l1_mps) && TANK_MPS !== null && TANK_MPS > 0
                  ? Math.min(1, p.dv_l1_mps / TANK_MPS)
                  : 0;
              return (
                <li key={p.sat} className={styles.barRow}>
                  <span className={styles.barLabel}>SAT-{p.sat + 1}</span>
                  <span
                    className={styles.track}
                    role="meter"
                    aria-label={`SAT-${p.sat + 1} fuel to switch`}
                    aria-valuemin={0}
                    aria-valuemax={TANK_MPS ?? undefined}
                    aria-valuenow={isNum(p.dv_l1_mps) ? p.dv_l1_mps : undefined}
                  >
                    <span className={styles.fill} style={{ width: `${frac * 100}%` }} />
                  </span>
                  <span className={styles.barValue}>{mps(p.dv_l1_mps)}</span>
                </li>
              );
            })}
          </ul>
        )}
        <p className={styles.caption}>
          Out of a {TANK_MPS !== null ? mps(TANK_MPS) : "unmeasured"} tank; planning model
          (CW), L1 upper bound.
        </p>
      </div>
    </div>
  );
}
