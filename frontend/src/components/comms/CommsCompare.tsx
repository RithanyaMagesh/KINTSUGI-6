// Central vs decentral leader work, laser mesh vs star (Track C, C5 matrix).
// Every number comes from commsReport.json, a value-for-value subset of
// data/eval/comms_report.json (its `command` field regenerates it). 16 kill
// sets per cell, two deaths at 1200 s and 1500 s. No ranking: the decentral
// vacancy depends on the one-round-per-tick assumption, so the round-time
// sensitivity sits right next to it.
import report from "./commsReport.json";
import styles from "./CommsCompare.module.css";

interface Row {
  cell: string;
  killed: number[];
  critical_vacancy_s: number | null;
  function_vacancy_s: number | null;
  split_brain_s: number | null;
  consensus_rounds_max: number | null;
  function_vacancy_s_by_round_time: Record<string, number> | null;
}

const CELLS = [
  { id: "laser-mesh-central", title: "Mesh, central leader" },
  { id: "laser-star-central", title: "Star, central leader" },
  { id: "laser-mesh-decentral", title: "Mesh, consensus auction" },
  { id: "laser-star-decentral", title: "Star, consensus auction" },
] as const;

const rows = report.rows as Row[];
const UNMEASURED = "unmeasured";

function nums(cell: string, pick: (r: Row) => number | null | undefined): number[] {
  const out: number[] = [];
  for (const r of rows) {
    if (r.cell !== cell) continue;
    const v = pick(r);
    if (typeof v === "number" && Number.isFinite(v)) out.push(v);
  }
  return out;
}

const fmt = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1));

/** "mean 12.3 s (range 0 to 40 s)" or "unmeasured". */
function spread(vs: number[], unit: string): string {
  if (vs.length === 0) return UNMEASURED;
  const mean = vs.reduce((a, b) => a + b, 0) / vs.length;
  const lo = Math.min(...vs);
  const hi = Math.max(...vs);
  return lo === hi ? `${fmt(lo)} ${unit} in every run` : `mean ${fmt(mean)} ${unit} (range ${fmt(lo)} to ${fmt(hi)})`;
}

function CellCard({ id, title }: { id: string; title: string }) {
  const n = rows.filter((r) => r.cell === id).length;
  const critical = nums(id, (r) => r.critical_vacancy_s);
  const fnVac = nums(id, (r) => r.function_vacancy_s);
  const split = nums(id, (r) => r.split_brain_s);
  const rounds = nums(id, (r) => r.consensus_rounds_max);
  const splitRuns = split.filter((v) => v > 0).length;
  return (
    <section className={styles.card} aria-label={title}>
      <h4 className={styles.cardTitle}>{title}</h4>
      <dl className={styles.list}>
        <div>
          <dt>Leader work left vacant</dt>
          <dd>{spread(critical, "s")}</dd>
        </div>
        <div>
          <dt>Any leader function vacant</dt>
          <dd>{spread(fnVac, "s")}</dd>
        </div>
        <div>
          <dt>Split-brain (two holders)</dt>
          <dd style={splitRuns > 0 ? { color: "var(--status-caution)" } : undefined}>
            {split.length === 0 ? UNMEASURED : `${splitRuns} of ${split.length} runs, up to ${fmt(Math.max(...split))} s`}
          </dd>
        </div>
        <div>
          <dt>Auction rounds, most in one run</dt>
          <dd>{rounds.length === 0 ? UNMEASURED : `${fmt(Math.max(...rounds))} rounds (a count)`}</dd>
        </div>
      </dl>
      <p className={styles.foot}>{n} kill sets</p>
    </section>
  );
}

/** Mean function vacancy if one auction round took τ seconds instead of 2 s. */
function Sensitivity() {
  const taus = ["0.1", "0.5", "2.0"];
  const dec = CELLS.filter((c) => c.id.endsWith("decentral"));
  return (
    <table className={styles.table}>
      <caption className={styles.caption}>
        Function vacancy if one auction round took this long (a model over the same runs, not a new simulation; 2 s is the engine
        assumption)
      </caption>
      <thead>
        <tr>
          <th scope="col">Round time</th>
          {dec.map((c) => (
            <th key={c.id} scope="col">{c.title}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {taus.map((t) => (
          <tr key={t}>
            <th scope="row">{t} s</th>
            {dec.map((c) => (
              <td key={c.id}>{spread(nums(c.id, (r) => r.function_vacancy_s_by_round_time?.[t]), "s")}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const VERDICT_TEXT: Record<string, string> = {
  "C5-H7": "Decentral mesh has no split-brain",
  "C5-H8": "Decentral star split-brains when the hub dies",
  "C5-H9": "Decentral fills leader work at least as fast as central",
};

const plain = (t: string) => t.replace(/>=/g, "at least").replace(/<=/g, "at most").replace(/\|/g, "");
/** "4 of 16" when the threshold counts kill sets ("15/16"), else the bare value. */
function measured(threshold: string, value: number): string {
  const m = /\/(\d+)/.exec(threshold);
  return m !== null ? `${fmt(value)} of ${m[1]}` : fmt(value);
}

export default function CommsCompare() {
  const verdicts = report.verdicts as Record<string, { threshold: string; value: number; verdict: string }>;
  return (
    <details className={styles.details}>
      <summary className={styles.summary}>Central leader vs consensus auction (evaluation runs)</summary>
      <div className={styles.body}>
        <p className={styles.note}>
          Same two-death scenario in every cell (deaths at {report.failure_times_s.map((t) => `${t} s`).join(" and ")}), each pair of
          satellites killed once. These are recorded evaluation runs, not this live run. Laser parameters and the 2 s round time are
          assumptions.
        </p>
        <div className={styles.grid}>
          {CELLS.map((c) => (
            <CellCard key={c.id} id={c.id} title={c.title} />
          ))}
        </div>
        <div className={styles.tableWrap}>
          <Sensitivity />
        </div>
        <h4 className={styles.cardTitle}>Pre-registered checks</h4>
        <ul className={styles.verdicts}>
          {Object.entries(verdicts).map(([k, v]) => (
            <li key={k}>
              {VERDICT_TEXT[k] ?? k}: {v.verdict === "PASS" ? "held" : "did not hold"} (needed {plain(v.threshold)}, measured{" "}
              {measured(v.threshold, v.value)})
            </li>
          ))}
        </ul>
        <p className={styles.source}>
          Source: data/eval/comms_report.json, made by <span className={styles.cmd}>{report.command}</span> ({report.preregistration}).
        </p>
      </div>
    </details>
  );
}
