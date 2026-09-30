// Formation geometry derived from MEASURED positions only — §7.5 "formation
// deviation, derived from r vs slot references" and §8.3 ghost slots.
//
// The wire carries positions and target-slot NAMES but not slot coordinates
// (cubesat/wire.py deliberate cut: slot geometry is not on the wire). Slot
// references are therefore reconstructed from the live swarm itself, using the
// locked formation structure:
//   - cubesat/hcw.py slot_initial_state: every seat rides ONE common drift-free
//     2:1 passive-relative ellipse, x = A cos(p), y = -2A sin(p), z = A cos(p);
//   - cubesat/sim.py build_slots: seats are equally phased on that ellipse and
//     sat i starts on slot i.
// Each frame we fit the ellipse amplitude A and the common formation phase Φ
// from the measured positions of the flying (non-failed) satellites — nothing
// is invented; when the fit is impossible (too few satellites flying) the
// result is flagged not-ok and the UI renders "unmeasured".

import type { Satellite } from "../types/satellite";

export interface FormationFit {
  ok: boolean;
  amplitude: number; // fit ellipse amplitude A [m]
  phase: number; // common formation phase Φ [rad]
  deviationMean: number | null; // mean |r_sat - seat| over flying sats [m]
  /** Seat index -> LVLH seat position [m]. Index iteration, never set order. */
  seats: Map<number, [number, number, number]>;
}

/** Seat index of a satellite: its assigned target slot when one was assigned
 * (cubesat/wire.py assignment_map), else its own 1-based id (sim.py: sat i
 * starts on slot i). SAT-1 -> 0. */
export function seatIndexOf(sat: Satellite): number {
  if (sat.targetSlot !== undefined && sat.targetSlot.startsWith("slot_")) {
    const j = Number.parseInt(sat.targetSlot.slice("slot_".length), 10);
    if (Number.isInteger(j) && j >= 0) return j;
  }
  const i = Number.parseInt(sat.id.replace("SAT-", ""), 10);
  return Number.isInteger(i) ? i - 1 : 0;
}

function ellipsePoint(a: number, p: number): [number, number, number] {
  // x = A cos p, y = -2A sin p, z = A cos p  (hcw.py slot_initial_state)
  const c = a * Math.cos(p);
  const s = -2 * a * Math.sin(p);
  return [c, s, c];
}

/** Fit the common formation ellipse + phase from measured positions and place
 * every seat. `nSeats` sizes the seat pattern when it exceeds the observed
 * satellite count. Failed satellites are excluded from the fit (they coast
 * ballistically, off the formation ellipse); reconfiguring satellites too when
 * any satellite is holding a seat — they are mid-transfer and would bias the
 * phase fit, but their deviation is still measured against their target seat. */
export function fitFormation(sats: Satellite[], nSeats: number): FormationFit {
  const flying = sats.filter((s) => s.status !== "failed");
  if (flying.length === 0) {
    return { ok: false, amplitude: 0, phase: 0, deviationMean: null, seats: new Map() };
  }
  const holding = flying.filter((s) => s.status !== "reconfiguring");
  const fitSet = holding.length > 0 ? holding : flying;

  // Per-satellite polar coords on the 2:1 ellipse: A_j = sqrt(x^2 + (y/2)^2),
  // theta_j = atan2(-y/2, x). z is ignored for the fit (z = A cos p shares the
  // x phase; amplitude comes from the radial/along-track plane).
  let cosSum = 0;
  let sinSum = 0;
  let ampSum = 0;
  for (const sat of fitSet) {
    const [x, y] = sat.r;
    const uy = -y / 2;
    const amp = Math.hypot(x, uy);
    if (amp < 1e-6) continue; // at the ellipse centre the phase is undefined
    ampSum += amp;
    const theta = Math.atan2(uy, x);
    const d = theta - (2 * Math.PI * seatIndexOf(sat)) / nSeats;
    cosSum += Math.cos(d);
    sinSum += Math.sin(d);
  }

  const measured = fitSet.filter((s) => {
    const [x, y] = s.r;
    return Math.hypot(x, -y / 2) >= 1e-6;
  });
  if (measured.length === 0 || ampSum <= 0) {
    return { ok: false, amplitude: 0, phase: 0, deviationMean: null, seats: new Map() };
  }

  const phase = Math.atan2(sinSum, cosSum); // circular mean of theta_j - 2pi*j/N
  const amplitude = ampSum / measured.length;
  if (!Number.isFinite(phase) || !Number.isFinite(amplitude) || amplitude <= 0) {
    return { ok: false, amplitude: 0, phase: 0, deviationMean: null, seats: new Map() };
  }

  // Seats: index iteration over the seat range (never set/dict order).
  const seats = new Map<number, [number, number, number]>();
  for (let j = 0; j < nSeats; j++) {
    seats.set(j, ellipsePoint(amplitude, phase + (2 * Math.PI * j) / nSeats));
  }

  // Deviation of each flying satellite from its own seat, mean over the swarm.
  let devSum = 0;
  for (const sat of flying) {
    const seat = seats.get(seatIndexOf(sat));
    if (seat === undefined) continue;
    devSum += Math.hypot(sat.r[0] - seat[0], sat.r[1] - seat[1], sat.r[2] - seat[2]);
  }
  const deviationMean = devSum / flying.length;

  return { ok: true, amplitude, phase, deviationMean, seats };
}

/** Distance from one satellite to its own seat [m]; null when the fit is not
 * possible — the UI renders "unmeasured" (repo invariant 1). */
export function distanceToSeat(sat: Satellite, fit: FormationFit): number | null {
  if (!fit.ok) return null;
  const seat = fit.seats.get(seatIndexOf(sat));
  if (seat === undefined) return null;
  return Math.hypot(sat.r[0] - seat[0], sat.r[1] - seat[1], sat.r[2] - seat[2]);
}
