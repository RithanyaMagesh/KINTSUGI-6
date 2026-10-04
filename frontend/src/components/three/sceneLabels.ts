// Screen-space label layout — the decluttering layer (§22 + the 2026-09-30
// user verdict: labels piled into an unreadable stack). DOM labels are placed
// by JS (not CSS2DRenderer) so the controller owns collision resolution:
// priority failed > selected > leader > reconfiguring > recovered > others,
// lowest priority hidden first when crowded, and a label NEVER overlaps the
// dot it names. Deterministic: stable sort by (priority, id), fixed offset
// ladder — no Math.random, no dict iteration order.
import styles from "./SwarmScene.module.css";

export interface LabelItem {
  el: HTMLElement;
  /** Anchor = centre of the dot the label names, CSS px in viewport space. */
  x: number;
  y: number;
  /** Screen radius of that dot (px) — kept clear of the label. */
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

const GAP = 6; // px clearance between dot edge and label edge
const PAD = 2; // px inflation of every rect for collision tests
/** Placement ladder: preferred above the dot, then below / right / left,
 * diagonals, then far above/below. Fixed order = deterministic. */
const DIRS: ReadonlyArray<readonly [number, number]> = [
  [0, -1],
  [0, 1],
  [1, 0],
  [-1, 0],
  [0.85, -0.85],
  [-0.85, -0.85],
  [0.85, 0.85],
  [-0.85, 0.85],
  [0, -2.4],
  [0, 2.4],
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
  /** element -> cached size + the text key it was measured for. Weak so
   * disposed records vanish without bookkeeping. */
  private measured = new WeakMap<HTMLElement, { key: string; w: number; h: number }>();

  constructor() {
    this.root = document.createElement("div");
    this.root.className = styles.labelLayer;
  }

  /** One layout pass over ALL label candidates (shown or not — hidden
   * candidates still contribute their dot to the occupied set). */
  layout(items: LabelItem[]): void {
    for (const child of Array.from(this.root.children)) {
      (child as HTMLElement).style.visibility = "hidden";
    }
    const occupied: Rect[] = [];
    for (const it of items) {
      occupied.push({
        x0: it.x - it.dotR - PAD,
        y0: it.y - it.dotR - PAD,
        x1: it.x + it.dotR + PAD,
        y1: it.y + it.dotR + PAD,
      });
    }
    const shown = items.filter((it) => it.show).sort((a, b) =>
      a.priority !== b.priority ? a.priority - b.priority : a.tie < b.tie ? -1 : a.tie > b.tie ? 1 : 0,
    );
    for (const it of shown) {
      const size = this.measure(it.el);
      if (size === null) continue;
      const half = { w: size.w / 2 + PAD, h: size.h / 2 + PAD };
      let placed = false;
      for (const [dx, dy] of DIRS) {
        const cx = it.x + dx * (it.dotR + GAP + (dx !== 0 ? half.w : 0));
        const cy = it.y + dy * (it.dotR + GAP + (dy !== 0 ? half.h : 0));
        const rect: Rect = { x0: cx - half.w, y0: cy - half.h, x1: cx + half.w, y1: cy + half.h };
        if (occupied.some((o) => rect.x0 < o.x1 && rect.x1 > o.x0 && rect.y0 < o.y1 && rect.y1 > o.y0)) {
          continue;
        }
        occupied.push(rect);
        it.el.style.transform = `translate(-50%, -50%) translate(${cx.toFixed(1)}px, ${cy.toFixed(1)}px)`;
        it.el.style.visibility = "visible";
        placed = true;
        break;
      }
      if (!placed) it.el.style.visibility = "hidden"; // crowded: lowest priority hides first
    }
  }

  private measure(el: HTMLElement): { w: number; h: number } | null {
    const key = el.dataset.labelKey ?? "";
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
    this.root.remove();
  }
}
