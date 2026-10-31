// Formation pair lines — §7.2 formation lines + §7.3 failure coloring.
// Buffers sized for up to 50 satellites (backend cap is 32)
// so large swarms never silently truncate formation links.
import * as THREE from "three";
import type { Satellite } from "../../types/satellite";
import { lvlhToScene } from "./sceneSatellites";
import { SCENE_TOKENS, statusToken, tokenColor } from "./sceneColors";

const MAX_SATS = 50; // design ceiling for the live view
const ALL_PAIRS_MAX = 8; // up to here every pair is linked (the classic look)
const LINK_K = 2; // larger swarms: each satellite links to its 2 nearest
const PAIR_CAPACITY = ((MAX_SATS * (MAX_SATS - 1)) / 2) * 2 * 3; // vertices * floats

export class FormationLines {
  readonly healthy: THREE.LineSegments;
  readonly failed: THREE.LineSegments;

  private healthyPositions: Float32Array;
  private failedPositions: Float32Array;
  private failureActive = false;
  private linesOn = true;

  constructor() {
    const build = (color: THREE.Color, opacity: number) => {
      const pos = new Float32Array(PAIR_CAPACITY);
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      const seg = new THREE.LineSegments(
        geo,
        new THREE.LineBasicMaterial({ color, transparent: true, opacity, depthWrite: false }),
      );
      seg.frustumCulled = false;
      return { seg, pos };
    };
    const healthy = build(tokenColor(SCENE_TOKENS.borderStrong), 0.26);
    this.healthy = healthy.seg;
    this.healthyPositions = healthy.pos;
    const failed = build(tokenColor(statusToken("failed")), 0.44);
    this.failed = failed.seg;
    this.failedPositions = failed.pos;
  }

  /** Formation links. Small swarms (<= ALL_PAIRS_MAX) link every pair; larger
   * ones link each satellite to its LINK_K nearest neighbours only — a 50-sat
   * all-pairs mesh is 1,225 lines and reads as noise. Links touching a failed
   * satellite go to the failure buffer (shown only during a failure). */
  update(sats: Satellite[], failureActive: boolean): void {
    this.failureActive = failureActive;
    let hv = 0;
    let fv = 0;
    const n = sats.length;
    const pairs: Array<[number, number]> = [];
    if (n <= ALL_PAIRS_MAX) {
      for (let a = 0; a < n; a++) for (let b = a + 1; b < n; b++) pairs.push([a, b]);
    } else {
      const seen = new Set<number>();
      for (let a = 0; a < n; a++) {
        const near: Array<[number, number]> = [];
        for (let b = 0; b < n; b++) {
          if (b === a) continue;
          const ra = sats[a].r;
          const rb = sats[b].r;
          near.push([Math.hypot(ra[0] - rb[0], ra[1] - rb[1], ra[2] - rb[2]), b]);
        }
        near.sort((x, y) => x[0] - y[0] || x[1] - y[1]);
        for (const [, b] of near.slice(0, LINK_K)) {
          const key = Math.min(a, b) * 1000 + Math.max(a, b);
          if (seen.has(key)) continue;
          seen.add(key);
          pairs.push([Math.min(a, b), Math.max(a, b)]);
        }
      }
    }
    for (const [a, b] of pairs) {
      const touchesFailed = sats[a].status === "failed" || sats[b].status === "failed";
      const target = touchesFailed ? this.failedPositions : this.healthyPositions;
      const v = touchesFailed ? fv : hv;
      if (v + 6 > target.length) continue;
      target.set(lvlhToScene(sats[a].r), v);
      target.set(lvlhToScene(sats[b].r), v + 3);
      if (touchesFailed) fv += 6;
      else hv += 6;
    }
    for (const [seg, count] of [
      [this.healthy, hv],
      [this.failed, fv],
    ] as const) {
      (seg.geometry.getAttribute("position") as THREE.BufferAttribute).needsUpdate = true;
      seg.geometry.setDrawRange(0, count / 3);
    }
    this.applyVisibility();
  }

  setVisibility(linesOn: boolean): void {
    this.linesOn = linesOn;
    this.applyVisibility();
  }

  refreshTheme(): void {
    (this.healthy.material as THREE.LineBasicMaterial).color = tokenColor(
      SCENE_TOKENS.borderStrong,
    );
    (this.failed.material as THREE.LineBasicMaterial).color = tokenColor(statusToken("failed"));
  }

  private applyVisibility(): void {
    this.healthy.visible = this.linesOn;
    this.failed.visible = this.linesOn && this.failureActive;
  }

  dispose(): void {
    this.healthy.geometry.dispose();
    (this.healthy.material as THREE.Material).dispose();
    this.failed.geometry.dispose();
    (this.failed.material as THREE.Material).dispose();
  }
}
