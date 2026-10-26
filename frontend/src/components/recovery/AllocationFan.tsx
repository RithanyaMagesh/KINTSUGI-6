// AllocationFan — Image 1 inspired SVG cubic-bezier diagram mapping
// Left: Swarm Satellites (SAT-1..N) -> Center: Hungarian Solver (linear_sum_assignment)
// -> Right: 2:1 CW Target Slots (slot_0..k-1) with live slot error (m).
// Directly visualizes the Problem Statement's core algorithmic step:
// rectangular Hungarian assignment (rows = survivors, cols = candidate slots)
// and role re-election after a failure.
// Every value derives strictly from simStore + recoveryStore + fitFormation;
// absent values render "unmeasured" (repo invariant 1). Zero raw hex (§13.1).
import { useSimStore } from "../../stores/simStore";
import { useUiStore } from "../../stores/uiStore";
import { useRecoveryStore, selectLatestFailure } from "../../stores/recoveryStore";
import { distanceToSeat, fitFormation, seatIndexOf } from "../../utils/geometry";
import styles from "./AllocationFan.module.css";

const ROW_H = 34;
const PAD_Y = 20;
const SVG_W = 310;
const LEFT_X = 76;
const MID_X = 155;
const RIGHT_X = 234;

export default function AllocationFan() {
  const satellites = useSimStore((s) => s.satellites);
  const missionState = useSimStore((s) => s.missionState);
  const policy = useSimStore((s) => s.policy);
  const reassignment = useSimStore((s) => s.lastReassignment);
  const selectedId = useUiStore((s) => s.selectedSatelliteId);
  const selectSatellite = useUiStore((s) => s.selectSatellite);
  const latestFailure = useRecoveryStore(selectLatestFailure);

  if (satellites.length === 0) {
    return (
      <div className={styles.empty}>
        Waiting for simulation data — launch a live run or load a replay to inspect the
        survivor-to-slot Hungarian allocation fan.
      </div>
    );
  }

  const nSats = satellites.length;
  const fit = fitFormation(satellites, Math.max(nSats, 1));

  // Build ordered slot list from current assignments (or default seat indices)
  const slotMap = new Map<number, { slotName: string; satId: string | null; role: string | null; dist: number | null; moved: boolean }>();
  for (let j = 0; j < nSats; j++) {
    slotMap.set(j, {
      slotName: "slot_" + j,
      satId: null,
      role: null,
      dist: null,
      moved: false,
    });
  }

  const reassignRowMap = new Map<string, { oldRole: string | null; newRole: string | null; targetSlot: string | null }>();
  if (reassignment !== null) {
    for (const r of reassignment.rows) {
      reassignRowMap.set(r.satelliteId, r);
    }
  }

  for (const sat of satellites) {
    if (sat.status === "failed") continue;
    const j = seatIndexOf(sat);
    const d = distanceToSeat(sat, fit);
    const rRow = reassignRowMap.get(sat.id);
    const defaultSlot = "slot_" + (Number.parseInt(sat.id.replace("SAT-", ""), 10) - 1);
    const moved =
      sat.status === "reconfiguring" ||
      (sat.targetSlot !== undefined && sat.targetSlot !== defaultSlot) ||
      (rRow !== undefined && rRow.oldRole !== null && rRow.oldRole !== rRow.newRole);
    slotMap.set(j, {
      slotName: sat.targetSlot ?? "slot_" + j,
      satId: sat.id,
      role: sat.role,
      dist: d,
      moved,
    });
  }

  const slots = Array.from(slotMap.entries()).sort((a, b) => a[0] - b[0]);
  const svgH = Math.max(nSats, slots.length) * ROW_H + PAD_Y * 2;
  const solverY = svgH / 2;

  const policyText = policy !== null && policy !== "" ? policy : "hungarian";
  const costText =
    reassignment !== null && reassignment.costTotal !== null
      ? reassignment.costTotal.toFixed(2)
      : "unmeasured";

  return (
    <section className={styles.wrap} aria-label="Survivor to slot allocation fan">
      <div className={styles.headerRow}>
        <span className={styles.headerLabel}>SURVIVORS (ROWS)</span>
        <span className={styles.headerCenter}>SOLVER: {policyText.toUpperCase()}</span>
        <span className={styles.headerRight}>2:1 CW SLOTS (COLS)</span>
      </div>

      <div className={styles.diagramHost}>
        <svg
          viewBox={`0 0 ${SVG_W} ${svgH}`}
          className={styles.svg}
          role="img"
          aria-label="Bezier allocation fan mapping surviving satellites to target slots"
        >
          {/* Bezier curves from each satellite (left) through solver hub (center) to target slot (right) */}
          {satellites.map((sat, i) => {
            const ySat = PAD_Y + i * ROW_H + ROW_H / 2;
            const failed = sat.status === "failed";
            const isSelected = sat.id === selectedId;
            if (failed) {
              // Crimson stub for failed satellite (coasts ballistically, excluded from Hungarian rows)
              return (
                <g key={`curve-${sat.id}`}>
                  <line
                    x1={LEFT_X}
                    y1={ySat}
                    x2={LEFT_X + 26}
                    y2={ySat}
                    stroke="var(--status-failed)"
                    strokeWidth="1.5"
                    strokeDasharray="3 2"
                  />
                  <text
                    x={LEFT_X + 30}
                    y={ySat + 3}
                    fill="var(--status-failed)"
                    fontSize="9"
                    fontFamily="var(--font-mono)"
                  >
                    ✕ COASTING
                  </text>
                </g>
              );
            }

            const j = seatIndexOf(sat);
            const ySlot = PAD_Y + j * ROW_H + ROW_H / 2;
            const slotInfo = slotMap.get(j);
            const moved = slotInfo?.moved ?? false;
            const strokeColor = isSelected
              ? "var(--focus-ring)"
              : moved
                ? "var(--status-caution)"
                : "var(--status-nominal)";
            const strokeOpacity = isSelected ? 0.98 : moved ? 0.88 : 0.45;
            const strokeW = isSelected ? 2.2 : moved ? 1.8 : 1.2;

            // Smooth cubic bezier: Left -> Mid -> Right
            const dPath =
              `M ${LEFT_X} ${ySat} ` +
              `C ${LEFT_X + 42} ${ySat}, ${MID_X - 38} ${solverY}, ${MID_X} ${solverY} ` +
              `C ${MID_X + 38} ${solverY}, ${RIGHT_X - 42} ${ySlot}, ${RIGHT_X} ${ySlot}`;

            return (
              <path
                key={`curve-${sat.id}`}
                d={dPath}
                fill="none"
                stroke={strokeColor}
                strokeWidth={strokeW}
                strokeOpacity={strokeOpacity}
              />
            );
          })}

          {/* Center Solver Hub Node */}
          <rect
            x={MID_X - 24}
            y={solverY - 18}
            width={48}
            height={36}
            rx={4}
            fill="var(--panel-raised)"
            stroke={
              missionState === "REPLANNING" || missionState === "RECONFIGURING"
                ? "var(--status-caution)"
                : "var(--border-strong)"
            }
            strokeWidth="1.2"
          />
          <text
            x={MID_X}
            y={solverY - 3}
            textAnchor="middle"
            fill="var(--ink)"
            fontSize="8.5"
            fontFamily="var(--font-mono)"
          >
            LSA
          </text>
          <text
            x={MID_X}
            y={solverY + 9}
            textAnchor="middle"
            fill="var(--status-caution)"
            fontSize="8"
            fontFamily="var(--font-mono)"
          >
            {costText === "unmeasured" ? "NOMINAL" : `J=${costText}`}
          </text>

          {/* Left nodes: Satellites */}
          {satellites.map((sat, i) => {
            const y = PAD_Y + i * ROW_H + ROW_H / 2;
            const failed = sat.status === "failed";
            const isSelected = sat.id === selectedId;
            const dotCol = failed
              ? "var(--status-failed)"
              : sat.status === "reconfiguring"
                ? "var(--status-caution)"
                : sat.role === "leader"
                  ? "var(--status-leader)"
                  : "var(--status-nominal)";
            const roleCode =
              sat.role === "leader" ? "LDR" : sat.role === "downlink" ? "DLK" : "IMG";

            return (
              <g
                key={`left-${sat.id}`}
                className={styles.clickableNode}
                onClick={() => selectSatellite(sat.id)}
              >
                <rect
                  x={2}
                  y={y - 12}
                  width={LEFT_X - 4}
                  height={24}
                  rx={3}
                  fill={isSelected ? "var(--panel-raised)" : "var(--bg)"}
                  stroke={isSelected ? "var(--focus-ring)" : failed ? "var(--status-failed)" : "var(--border)"}
                  strokeWidth="1"
                />
                <circle cx={11} cy={y} r={3.2} fill={dotCol} />
                <text
                  x={18}
                  y={y + 3.5}
                  fill={failed ? "var(--status-failed)" : "var(--ink)"}
                  fontSize="9.5"
                  fontFamily="var(--font-mono)"
                >
                  {sat.id} {failed ? "DEAD" : roleCode}
                </text>
              </g>
            );
          })}

          {/* Right nodes: Candidate 2:1 CW Slots */}
          {slots.map(([j, info], idx) => {
            const y = PAD_Y + idx * ROW_H + ROW_H / 2;
            const occupied = info.satId !== null;
            const vacatedByFail =
              !occupied && latestFailure?.vacatedSlot === info.slotName;
            const borderCol = info.moved
              ? "var(--status-caution)"
              : occupied
                ? "var(--border-strong)"
                : "var(--border)";
            const errStr =
              info.dist !== null ? `${info.dist.toFixed(0)}m` : occupied ? "—" : "OPEN";

            return (
              <g key={`right-${j}`}>
                <rect
                  x={RIGHT_X + 2}
                  y={y - 12}
                  width={SVG_W - RIGHT_X - 4}
                  height={24}
                  rx={3}
                  fill="var(--bg)"
                  stroke={borderCol}
                  strokeWidth="1"
                />
                <text
                  x={RIGHT_X + 8}
                  y={y - 1}
                  fill={occupied ? "var(--ink)" : "var(--ink-faint)"}
                  fontSize="9"
                  fontFamily="var(--font-mono)"
                >
                  {info.slotName}
                </text>
                <text
                  x={RIGHT_X + 8}
                  y={y + 9}
                  fill={
                    info.moved
                      ? "var(--status-caution)"
                      : vacatedByFail
                        ? "var(--status-failed)"
                        : "var(--ink-muted)"
                  }
                  fontSize="8"
                  fontFamily="var(--font-mono)"
                >
                  {occupied ? `${info.satId} (${errStr})` : vacatedByFail ? "VACATED" : "UNUSED"}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      <div className={styles.footerMeta}>
        <span>
          Total assignment cost:{" "}
          <strong className={styles.monoVal}>{costText}</strong>
        </span>
        <span>
          Mean slot error:{" "}
          <strong className={styles.monoVal}>
            {fit.ok && fit.deviationMean !== null ? `${fit.deviationMean.toFixed(1)} m` : "unmeasured"}
          </strong>
        </span>
      </div>
    </section>
  );
}
