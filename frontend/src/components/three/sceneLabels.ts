// Screen-space label layout — the decluttering layer (§22 + the 2026-09-30
// verdict, reworked after the 2026-10-04 "ring of boxes" verdict: eight labels
// fanned around a tight cluster and overlapped the markers). DOM labels are
// placed by JS (not CSS2DRenderer) so the controller owns collision
// resolution: priority failed > selected > leader > reconfiguring >
// recovered > others, lowest priority hidden first when crowded — a hidden
// label's data stays available in the satellite list / detail panel. Anchor
// discipline: a label never covers a marker pixel (every dot reserves a clear
// square sized to the outermost marker geometry, MARKER_CLEAR) and every
// placed label gets a 1px leader tick back to ITS dot, so an offset label
// always reads as anchored. The rung ladder stays within ~2 label-heights of
// the dot — a tight formation HIDES labels instead of fanning them around the
// cluster. Deterministic: stable sort by (priority, id), fixed rung ladder —
// no Math.random, no dict iteration order.
import styles from "./SwarmScene.module.css";
import { MARKER_CLEAR, MARKER_EXTENT } from "./sceneSatellites";

export interface LabelItem {
  el: HTMLElement;
  /** Anchor = centre of the dot the label names, CSS px in viewport space. */
  x: number;
  y: number;
  /** Disc radius on screen + 2 (as passed by the controller) — scaled up to
   * the marker clear radius for collision tests and leader ticks. */
  dotR: number;
  /** Lower = placed (and kept visible) first. */
  priority: number;
  /** Deterministic tie-break (satellite id). */
  tie: string;
  show: boolean;
}

interface Rect {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

const GAP = 6; // px clearance between the dot's clear square and the label
const PAD = 2; // px inflation of every rect for collision tests
const LEADER_MIN = 3; // below this gap the label hugs the marker — no tick
/** Placement ladder: preferred above the dot, then below / right / left, the
 * four corner diagonals (support-corrected, see layout), then one label-row
 * farther above/below. Every rung keeps the label within ~2 label-heights of
 * its dot; when none fits the label hides (lowest priority first). Fixed
 * order = deterministic. [ux, uy, row] — unit direction + row offset. */
const DIRS: ReadonlyArray<readonly [number, number, number]> = [
  [0, -1, 0],
  [0, 1, 0],
  [1, 0, 0],
  [-1, 0, 0],
  [0.7071, -0.7071, 0],
  [-0.7071, -0.7071, 0],
  [0.7071, 0.7071, 0],
  [-0.7071, 0.7071, 0],
  [0, -1, 1],
  [0, 1, 1],
];

/** §22 + the decluttering ask: failed > selected > leader > reconfiguring >
 * recovered > others; ties break by satellite id (deterministic). Slot
 * captions always lose (priority 10, set by the caller). */
export function labelPriority(
  status: string,
  role: string,
  selectedId: string | null,
  id: string,
): number {
  if (status === "failed") return 0;
  if (id === selectedId) return 1;
  if (role === "leader") return 2;
  if (status === "reconfiguring") return 3;
  if (status === "recovered") return 4;
  return 5;
}

export class LabelLayer {
  readonly root: HTMLDivElement;
  /** element -> cached size + the text/weight key it was measured for. Weak
   * so disposed records vanish without bookkeeping. */
  private measured = new WeakMap<HTMLElement, { key: string; w: number; h: number }>();
  /** label element -> its leader tick (created lazily, painted under it). */
  private leaders = new Map<HTMLElement, HTMLDivElement>();

  constructor() {
    this.root = document.createElement("div");
    this.root.className = styles.labelLayer;
  }

  /** One layout pass over ALL label candidates (shown or not — hidden
   * candidates still contribute their marker clear square to the occupied
   * set, so a placed label never covers another satellite's marker). */
  layout(items: LabelItem[]): void {
    for (const child of Array.from(this.root.children)) {
      (child as HTMLElement).style.visibility = "hidden";
    }
    const occupied: Rect[] = [];
    for (const it of items) {
      const r = it.dotR * MARKER_CLEAR + PAD;
      occupied.push({ x0: it.x - r, y0: it.y - r, x1: it.x + r, y1: it.y + r });
    }
    const shown = items.filter((it) => it.show).sort((a, b) =>
      a.priority !== b.priority ? a.priority - b.priority : a.tie < b.tie ? -1 : a.tie > b.tie ? 1 : 0,
    );
    for (const it of shown) {
      const size = this.measure(it.el);
      if (size === null) continue;
      const hw = size.w / 2 + PAD;
      const hh = size.h / 2 + PAD;
      const clearR = it.dotR * MARKER_CLEAR;
      let placed = false;
      for (const [ux, uy, row] of DIRS) {
        // Support-correct radial offset: along unit direction u the dot's
        // clear square extends (|ux|+|uy|)*clearR and the label box extends
        // |ux|*hw + |uy|*hh, so this distance leaves exactly GAP between the
        // two — corners AND faces clear, unlike a per-axis scaling.
        const su = (Math.abs(ux) + Math.abs(uy)) * clearR;
        const ru = Math.abs(ux) * hw + Math.abs(uy) * hh;
        const d = su + GAP + ru + row * (2 * hh + GAP);
        const cx = it.x + ux * d;
        const cy = it.y + uy * d;
        const rect: Rect = { x0: cx - hw, y0: cy - hh, x1: cx + hw, y1: cy + hh };
        if (occupied.some((o) => rect.x0 < o.x1 && rect.x1 > o.x0 && rect.y0 < o.y1 && rect.y1 > o.y0)) {
          continue;
        }
        occupied.push(rect);
        this.placeLeader(it, cx, cy, hw, hh);
        it.el.style.transform = `translate(-50%, -50%) translate(${cx.toFixed(1)}px, ${cy.toFixed(1)}px)`;
        it.el.style.visibility = "visible";
        placed = true;
        break;
      }
      if (!placed) it.el.style.visibility = "hidden"; // crowded: lowest priority hides first
    }
    for (const [el, div] of this.leaders) {
      if (!el.isConnected) {
        div.remove();
        this.leaders.delete(el);
      }
    }
  }

  /** Hairline leader tick from the marker's outermost pixel to the label's
   * near edge, along the dot->label direction. Labels on the near rungs sit
   * one GAP off the clear square — still a visible ~10px tick from the ring
   * edge, so every offset label reads as anchored to its own dot. */
  private placeLeader(it: LabelItem, cx: number, cy: number, hw: number, hh: number): void {
    const div = this.leaderFor(it.el);
    const vx = cx - it.x;
    const vy = cy - it.y;
    const len = Math.hypot(vx, vy);
    if (len < 1) {
      div.style.visibility = "hidden";
      return;
    }
    const ux = vx / len;
    const uy = vy / len;
    // dotR arrives as disc radius + 2 (controller); outermost marker pixel =
    // MARKER_EXTENT × disc radius (status ring / leader ring / failed cross).
    const markerR = (it.dotR - 2) * MARKER_EXTENT;
    const t0 = markerR / Math.max(Math.abs(ux), Math.abs(uy)) + 1;
    const t1 = len - (Math.abs(ux) * hw + Math.abs(uy) * hh) - 1;
    const gap = t1 - t0;
    if (gap < LEADER_MIN) {
      div.style.visibility = "hidden";
      return;
    }
    div.style.width = `${gap.toFixed(1)}px`;
    const deg = ((Math.atan2(vy, vx) * 180) / Math.PI).toFixed(2);
    div.style.transform = `translate(${(it.x + ux * t0).toFixed(1)}px, ${(it.y + uy * t0).toFixed(1)}px) rotate(${deg}deg)`;
    div.style.visibility = "visible";
  }

  private leaderFor(el: HTMLElement): HTMLDivElement {
    let div = this.leaders.get(el);
    if (div === undefined) {
      div = document.createElement("div");
      div.style.position = "absolute";
      div.style.left = "0";
      div.style.top = "0";
      div.style.height = "1px";
      div.style.background = "var(--border-strong)"; // matches the label box border
      div.style.transformOrigin = "0 50%";
      this.root.insertBefore(div, el); // paint under its label
      this.leaders.set(el, div);
    }
    return div;
  }

  private measure(el: HTMLElement): { w: number; h: number } | null {
    // Weight is part of the key: syncSatellite toggles 400/600 on selection.
    const key = `${el.dataset.labelKey ?? ""}|${el.style.fontWeight}`;
    const cached = this.measured.get(el);
    if (cached !== undefined && cached.key === key && cached.w > 0) return cached;
    if (!el.isConnected) return null;
    const w = el.offsetWidth;
    const h = el.offsetHeight;
    if (w === 0 || h === 0) return null; // not laid out yet; retry next frame
    const size = { key, w, h };
    this.measured.set(el, size);
    return size;
  }

  dispose(): void {
    for (const div of this.leaders.values()) div.remove();
    this.leaders.clear();
    this.root.remove();
  }
}
