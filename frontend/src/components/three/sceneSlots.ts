// Target formation slots + Continuous 2:1 Clohessy-Wiltshire (HCW) Formation
// Ellipse Track — FRONTEND_SPEC §8.3.
// Shows the Problem Statement directly in 3D:
// 1. Renders the closed, drift-free 2:1 relative orbit ellipse (x = A cos p,
//    y = -2A sin p, z = A cos p) around the chief LVLH origin [0,0,0] so the
//    viewer sees the exact orbital highway the swarm maintains.
// 2. Renders candidate slot reticles around the ellipse; slots targeted by
//    reconfiguring survivors light up in tactical amber (--status-caution) and
//    draw a dashed transfer chord from the maneuvering satellite to its new slot.
// Seat positions and ellipse amplitude come strictly from fitFormation()
// (utils/geometry.ts) — nothing is invented.
import * as THREE from "three";
import type { Satellite } from "../../types/satellite";
import { seatIndexOf, type FormationFit } from "../../utils/geometry";
import { SCENE_TOKENS, statusToken, tokenColor } from "./sceneColors";
import { lvlhToScene, markerWorldRadius } from "./sceneSatellites";
import type { LabelLayer } from "./sceneLabels";
import styles from "./SwarmScene.module.css";

const SLOT_TARGET_PX = 6;
const ELLIPSE_SEGMENTS = 128;

export interface SlotLabel {
  el: HTMLDivElement;
  pos: THREE.Vector3;
  screenR: number;
  text: string;
  show: boolean;
}

interface SlotMarker {
  ring: THREE.Mesh;
  connector: THREE.Line;
  el: HTMLDivElement;
  pos: THREE.Vector3;
  screenR: number;
  text: string;
  show: boolean;
}

export class SlotLayer {
  readonly group = new THREE.Group();

  private markers = new Map<number, SlotMarker>();
  private labels: LabelLayer;
  private cwEllipseLine: THREE.LineLoop;
  private cwEllipsePositions: Float32Array;

  constructor(labels: LabelLayer) {
    this.labels = labels;

    // Continuous 2:1 CW passive formation ellipse ribbon
    this.cwEllipsePositions = new Float32Array(ELLIPSE_SEGMENTS * 3);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(this.cwEllipsePositions, 3));
    this.cwEllipseLine = new THREE.LineLoop(
      geo,
      new THREE.LineBasicMaterial({
        color: tokenColor(SCENE_TOKENS.cwEllipse),
        transparent: true,
        opacity: 0.36,
        depthWrite: false,
      }),
    );
    this.cwEllipseLine.frustumCulled = false;
    this.group.add(this.cwEllipseLine);
  }

  get visible(): boolean {
    return this.group.visible;
  }

  set visible(v: boolean) {
    this.group.visible = v;
  }

  update(sats: Satellite[], fit: FormationFit, extent: number, selectedId: string | null): void {
    if (!fit.ok || fit.amplitude <= 0) {
      this.group.visible = false;
      return;
    }
    this.group.visible = true;

    // 1. Update continuous 2:1 CW formation ellipse (x = A cos p, y = -2A sin p, z = A cos p)
    const A = fit.amplitude;
    for (let i = 0; i < ELLIPSE_SEGMENTS; i++) {
      const p = (i / ELLIPSE_SEGMENTS) * Math.PI * 2;
      const c = A * Math.cos(p);
      const s = -2 * A * Math.sin(p);
      const [sx, sy, sz] = lvlhToScene([c, s, c]);
      this.cwEllipsePositions[i * 3] = sx;
      this.cwEllipsePositions[i * 3 + 1] = sy;
      this.cwEllipsePositions[i * 3 + 2] = sz;
    }
    (this.cwEllipseLine.geometry.getAttribute("position") as THREE.BufferAttribute).needsUpdate = true;
    this.cwEllipseLine.visible = true;

    // 2. Seat -> assigned satellite (exclude failed satellites so vacated slots
    // show as open or newly reassigned).
    const assigned = new Map<number, Satellite>();
    for (const sat of sats) {
      if (sat.status !== "failed") {
        assigned.set(seatIndexOf(sat), sat);
      }
    }

    // Hide any markers from a larger previous formation
    for (const [j, slot] of this.markers) {
      if (!fit.seats.has(j)) {
        slot.ring.visible = false;
        slot.connector.visible = false;
        slot.show = false;
      }
    }

    for (const [j, seat] of fit.seats) {
      let slot = this.markers.get(j);
      if (slot === undefined) {
        slot = this.createMarker();
        this.markers.set(j, slot);
      }
      slot.ring.visible = true;
      const sat = assigned.get(j);
      const active = sat !== undefined && sat.status === "reconfiguring";
      const selectedTarget = sat !== undefined && sat.id === selectedId;
      const [x, y, z] = lvlhToScene(seat);
      slot.pos.set(x, y, z);
      const mat = slot.ring.material as THREE.MeshBasicMaterial;
      mat.opacity = active ? 0.88 : selectedTarget ? 0.72 : 0.34;
      mat.color = tokenColor(
        active ? statusToken("reconfiguring") : selectedTarget ? SCENE_TOKENS.focus : SCENE_TOKENS.inkMuted,
      );
      slot.text = `slot_${j}${sat !== undefined ? ` · ${sat.role}` : " · VACATED"}`;
      slot.show = active || selectedTarget || sat === undefined;

      // Dashed transfer vector while the assigned survivor maneuvers to the slot.
      if (active && sat !== undefined) {
        const pos = slot.connector.geometry.getAttribute("position") as THREE.BufferAttribute;
        const [sx, sy, sz] = lvlhToScene(sat.r);
        pos.setXYZ(0, sx, sy, sz);
        pos.setXYZ(1, x, y, z);
        pos.needsUpdate = true;
        (slot.connector.material as THREE.LineDashedMaterial).dashSize = extent * 0.024;
        (slot.connector.material as THREE.LineDashedMaterial).gapSize = extent * 0.012;
        slot.connector.computeLineDistances();
        slot.connector.visible = true;
      } else {
        slot.connector.visible = false;
      }
    }
  }

  updateView(camera: THREE.PerspectiveCamera, viewportH: number, extent: number): void {
    const fov = (camera.fov * Math.PI) / 180;
    for (const slot of this.markers.values()) {
      slot.ring.quaternion.copy(camera.quaternion);
      const dist = camera.position.distanceTo(slot.pos);
      const size = markerWorldRadius(dist, viewportH, fov, SLOT_TARGET_PX, extent);
      slot.ring.scale.setScalar(size.world);
      slot.screenR = size.screenPx;
    }
  }

  labelItems(): SlotLabel[] {
    const out: SlotLabel[] = [];
    for (const slot of this.markers.values()) {
      out.push({ el: slot.el, pos: slot.pos, screenR: slot.screenR, text: slot.text, show: slot.show });
    }
    return out;
  }

  private createMarker(): SlotMarker {
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(0.95, 1.25, 4), // diamond / tactical bracket target
      new THREE.MeshBasicMaterial({
        color: tokenColor(SCENE_TOKENS.inkFaint),
        transparent: true,
        opacity: 0.34,
        side: THREE.DoubleSide,
        depthWrite: false,
      }),
    );
    this.group.add(ring);

    const connector = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]),
      new THREE.LineDashedMaterial({
        color: tokenColor(statusToken("reconfiguring")),
        transparent: true,
        opacity: 0.78,
      }),
    );
    connector.visible = false;
    this.group.add(connector);

    const el = document.createElement("div");
    el.className = styles.slotLabel;
    el.style.visibility = "hidden";
    this.labels.root.appendChild(el);

    return {
      ring,
      connector,
      el,
      pos: new THREE.Vector3(),
      screenR: SLOT_TARGET_PX,
      text: "",
      show: false,
    };
  }

  dispose(): void {
    this.cwEllipseLine.geometry.dispose();
    (this.cwEllipseLine.material as THREE.Material).dispose();
    this.group.remove(this.cwEllipseLine);
    for (const slot of this.markers.values()) {
      slot.ring.geometry.dispose();
      (slot.ring.material as THREE.Material).dispose();
      slot.connector.geometry.dispose();
      (slot.connector.material as THREE.Material).dispose();
      slot.el.remove();
      this.group.remove(slot.ring, slot.connector);
    }
    this.markers.clear();
  }
}
