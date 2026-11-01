// Laser crosslink beams — one segment per live link between the two
// satellites' scene positions. Colour is the link state only: locked beams
// in the nominal token, acquiring beams dimmer in the caution token, down
// links not drawn. Buffers are allocated once (sized for 50 satellites, every
// pair) and reused; positions are refreshed each frame after the satellites
// move, with no per-frame allocation.
import * as THREE from "three";
import type { Link } from "../../types/telemetry";
import { tokenColor } from "./sceneColors";

const MAX_SATS = 50;
const MAX_LINKS = (MAX_SATS * (MAX_SATS - 1)) / 2;
const LOCKED_TOKEN = "--status-nominal";
const ACQUIRING_TOKEN = "--status-caution";

/** Anything with a scene position, keyed by satellite id (the SatRecords). */
export interface Positioned {
  group: THREE.Object3D;
}

class BeamSet {
  readonly seg: THREE.LineSegments;
  readonly positions = new Float32Array(MAX_LINKS * 6);
  readonly ends: string[] = []; // [a0, b0, a1, b1, ...] for the drawn links
  count = 0;

  constructor(token: string, opacity: number) {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(this.positions, 3));
    geo.setDrawRange(0, 0);
    this.seg = new THREE.LineSegments(
      geo,
      new THREE.LineBasicMaterial({
        color: tokenColor(token),
        transparent: true,
        opacity,
        depthWrite: false,
      }),
    );
    this.seg.frustumCulled = false;
    this.seg.renderOrder = 2;
  }
}

export class LinkBeams {
  readonly locked = new BeamSet(LOCKED_TOKEN, 0.7);
  readonly acquiring = new BeamSet(ACQUIRING_TOKEN, 0.35);
  private on = true;

  get objects(): THREE.LineSegments[] {
    return [this.locked.seg, this.acquiring.seg];
  }

  /** New link list from the stream. Only the endpoint ids are kept here;
   * positions are written by updatePositions every frame. */
  setLinks(links: readonly Link[]): void {
    this.locked.ends.length = 0;
    this.acquiring.ends.length = 0;
    for (const l of links) {
      const set = l.state === "LOCKED" ? this.locked : l.state === "ACQUIRING" ? this.acquiring : null;
      if (set === null || set.ends.length / 2 >= MAX_LINKS) continue;
      set.ends.push(l.a, l.b);
    }
  }

  /** Write the current satellite positions into the beam buffers. Links to a
   * satellite that is not in the scene are skipped. */
  updatePositions(records: ReadonlyMap<string, Positioned>): void {
    for (const set of [this.locked, this.acquiring]) {
      let v = 0;
      const p = set.positions;
      for (let i = 0; i < set.ends.length; i += 2) {
        const a = records.get(set.ends[i]);
        const b = records.get(set.ends[i + 1]);
        if (a === undefined || b === undefined) continue;
        const pa = a.group.position;
        const pb = b.group.position;
        p[v] = pa.x;
        p[v + 1] = pa.y;
        p[v + 2] = pa.z;
        p[v + 3] = pb.x;
        p[v + 4] = pb.y;
        p[v + 5] = pb.z;
        v += 6;
      }
      set.count = v / 3;
      (set.seg.geometry.getAttribute("position") as THREE.BufferAttribute).needsUpdate = v > 0;
      set.seg.geometry.setDrawRange(0, set.count);
      set.seg.visible = this.on && set.count > 0;
    }
  }

  setVisibility(on: boolean): void {
    this.on = on;
    this.locked.seg.visible = on && this.locked.count > 0;
    this.acquiring.seg.visible = on && this.acquiring.count > 0;
  }

  refreshTheme(): void {
    (this.locked.seg.material as THREE.LineBasicMaterial).color = tokenColor(LOCKED_TOKEN);
    (this.acquiring.seg.material as THREE.LineBasicMaterial).color = tokenColor(ACQUIRING_TOKEN);
  }

  dispose(): void {
    for (const set of [this.locked, this.acquiring]) {
      set.seg.geometry.dispose();
      (set.seg.material as THREE.Material).dispose();
    }
  }
}
