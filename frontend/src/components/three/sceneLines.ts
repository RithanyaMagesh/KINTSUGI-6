// Formation pair lines — §7.2 formation lines + §7.3 failure coloring.
// Supports up to MAX_SATS = 50 (the backend schema ceiling in cubesat/scenario.py)
// so large swarms never silently truncate formation links.
import * as THREE from "three";
import type { Satellite } from "../../types/satellite";
import { lvlhToScene } from "./sceneSatellites";
import { SCENE_TOKENS, statusToken, tokenColor } from "./sceneColors";

const MAX_SATS = 50; // matches backend scenario schema max N=50
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

  /** Split every satellite pair into the healthy or failed-touching buffer. */
  update(sats: Satellite[], failureActive: boolean): void {
    this.failureActive = failureActive;
    let hv = 0;
    let fv = 0;
    for (let a = 0; a < sats.length; a++) {
      for (let b = a + 1; b < sats.length; b++) {
        const touchesFailed = sats[a].status === "failed" || sats[b].status === "failed";
        const target = touchesFailed ? this.failedPositions : this.healthyPositions;
        const v = touchesFailed ? fv : hv;
        if (v + 6 > target.length) continue;
        target.set(lvlhToScene(sats[a].r), v);
        target.set(lvlhToScene(sats[b].r), v + 3);
        if (touchesFailed) fv += 6;
        else hv += 6;
      }
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
