// Target formation ghost slots — FRONTEND_SPEC §8.3: transparent markers
// where satellites should move; new targets brighter, old faded; slot labels
// show role names; dashed connectors link reconfiguring satellites to their
// target seats. Rebuilt after the 2026-09-30 user verdict: the old wireframe
// octahedra dominated everything — slots are now thin low-opacity billboard
// rings, constant apparent size like the satellites; the selected satellite's
// target slot is slightly brighter. Seat positions come from the measured
// formation fit (utils/geometry.ts) — nothing is invented.
import * as THREE from "three";
import type { Satellite } from "../../types/satellite";
import { seatIndexOf, type FormationFit } from "../../utils/geometry";
import { SCENE_TOKENS, statusToken, tokenColor } from "./sceneColors";
import { lvlhToScene, markerWorldRadius } from "./sceneSatellites";
import type { LabelLayer } from "./sceneLabels";
import styles from "./SwarmScene.module.css";

const SLOT_TARGET_PX = 5; // smaller than satellites — slots are background

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
  readonly group = new THREE.Group(); // ghost rings + connectors

  private markers = new Map<number, SlotMarker>();
  private labels: LabelLayer;

  constructor(labels: LabelLayer) {
    this.labels = labels;
  }

  get visible(): boolean {
    return this.group.visible;
  }

  set visible(v: boolean) {
    this.group.visible = v;
  }

  update(sats: Satellite[], fit: FormationFit, extent: number, selectedId: string | null): void {
    if (!fit.ok) {
      this.group.visible = false;
      return;
    }
    this.group.visible = true;

    // Seat -> assigned satellite (labels show role names, §8.3).
    const assigned = new Map<number, Satellite>();
    for (const sat of sats) assigned.set(seatIndexOf(sat), sat);

    for (const [j, seat] of fit.seats) {
      let slot = this.markers.get(j);
      if (slot === undefined) {
        slot = this.createMarker();
        this.markers.set(j, slot);
      }
      const sat = assigned.get(j);
      const active = sat !== undefined && sat.status === "reconfiguring";
      const selectedTarget = sat !== undefined && sat.id === selectedId;
      const [x, y, z] = lvlhToScene(seat);
      slot.pos.set(x, y, z);
      const mat = slot.ring.material as THREE.MeshBasicMaterial;
      mat.opacity = active ? 0.7 : selectedTarget ? 0.55 : 0.22;
      mat.color = tokenColor(
        active ? statusToken("reconfiguring") : selectedTarget ? SCENE_TOKENS.focus : SCENE_TOKENS.inkFaint,
      );
      slot.text = `slot_${j}${sat !== undefined ? ` · ${sat.role}` : ""}`;
      slot.show = active || selectedTarget;

      // Dashed connector while the assigned satellite is flying to the seat.
      if (active && sat !== undefined) {
        const pos = slot.connector.geometry.getAttribute("position") as THREE.BufferAttribute;
        const [sx, sy, sz] = lvlhToScene(sat.r);
        pos.setXYZ(0, sx, sy, sz);
        pos.setXYZ(1, x, y, z);
        pos.needsUpdate = true;
        (slot.connector.material as THREE.LineDashedMaterial).dashSize = extent * 0.02;
        (slot.connector.material as THREE.LineDashedMaterial).gapSize = extent * 0.01;
        slot.connector.computeLineDistances();
        slot.connector.visible = true;
      } else {
        slot.connector.visible = false;
      }
    }
  }

  /** Per rendered frame: billboard + constant apparent size (same rule as
   * the satellites, smaller target). */
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

  /** Label candidates for the controller's layout pass (projection happens
   * there, so dot/label collision shares one coordinate space). */
  labelItems(): SlotLabel[] {
    const out: SlotLabel[] = [];
    for (const slot of this.markers.values()) {
      out.push({ el: slot.el, pos: slot.pos, screenR: slot.screenR, text: slot.text, show: slot.show });
    }
    return out;
  }

  private createMarker(): SlotMarker {
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(1, 1.18, 36),
      new THREE.MeshBasicMaterial({
        color: tokenColor(SCENE_TOKENS.inkFaint),
        transparent: true,
        opacity: 0.22,
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
        opacity: 0.5,
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
