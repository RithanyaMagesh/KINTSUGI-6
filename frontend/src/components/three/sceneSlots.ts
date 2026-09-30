// Target formation ghost slots — FRONTEND_SPEC §8.3: transparent markers
// where satellites should move; active targets brighter, unassigned seats
// faded; slot labels show role names; dashed connectors link reconfiguring
// satellites to their target seats. Seat positions come from the measured
// formation fit (utils/geometry.ts) — nothing is invented.
import * as THREE from "three";
import { CSS2DObject } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import type { Satellite } from "../../types/satellite";
import { seatIndexOf, type FormationFit } from "../../utils/geometry";
import { SCENE_TOKENS, statusToken, tokenColor } from "./sceneColors";
import { lvlhToScene } from "./sceneSatellites";
import styles from "./SwarmScene.module.css";

interface SlotMarker {
  marker: THREE.Mesh;
  label: CSS2DObject;
  el: HTMLDivElement;
  connector: THREE.Line;
}

export class SlotLayer {
  readonly group = new THREE.Group(); // ghost markers (+ their labels)

  private markers = new Map<number, SlotMarker>();

  get visible(): boolean {
    return this.group.visible;
  }

  set visible(v: boolean) {
    this.group.visible = v;
  }

  update(sats: Satellite[], fit: FormationFit, extent: number): void {
    if (!fit.ok) {
      this.group.visible = false;
      return;
    }
    this.group.visible = true;

    // Seat -> assigned satellite (labels show role names, §8.3).
    const assigned = new Map<number, Satellite>();
    for (const sat of sats) assigned.set(seatIndexOf(sat), sat);

    const radius = Math.max(15, extent * 0.015 || 15);
    for (const [j, seat] of fit.seats) {
      let slot = this.markers.get(j);
      if (slot === undefined) {
        slot = this.createMarker(radius);
        this.markers.set(j, slot);
      }
      const sat = assigned.get(j);
      const active = sat !== undefined && sat.status === "reconfiguring";
      const [x, y, z] = lvlhToScene(seat);
      slot.marker.position.set(x, y, z);
      const mat = slot.marker.material as THREE.MeshBasicMaterial;
      mat.opacity = active ? 0.85 : 0.3; // §8.3: new slots brighter, old faded
      mat.color = tokenColor(active ? statusToken("reconfiguring") : SCENE_TOKENS.inkFaint);
      slot.el.textContent = `slot_${j}${sat !== undefined ? ` · ${sat.role}` : ""}`;
      slot.label.visible = active;

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

  private createMarker(radius: number): SlotMarker {
    const marker = new THREE.Mesh(
      new THREE.OctahedronGeometry(radius),
      new THREE.MeshBasicMaterial({
        color: tokenColor(SCENE_TOKENS.inkFaint),
        wireframe: true,
        transparent: true,
        opacity: 0.3,
      }),
    );
    const el = document.createElement("div");
    el.className = styles.slotLabel;
    const label = new CSS2DObject(el);
    label.visible = false;
    marker.add(label);
    this.group.add(marker);

    const connector = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]),
      new THREE.LineDashedMaterial({
        color: tokenColor(statusToken("reconfiguring")),
        transparent: true,
        opacity: 0.7,
      }),
    );
    connector.visible = false;
    this.group.add(connector);

    return { marker, label, el, connector };
  }

  dispose(): void {
    for (const slot of this.markers.values()) {
      slot.marker.geometry.dispose();
      (slot.marker.material as THREE.Material).dispose();
      slot.el.remove();
      this.group.remove(slot.marker, slot.connector, slot.label);
      slot.connector.geometry.dispose();
      (slot.connector.material as THREE.Material).dispose();
    }
    this.markers.clear();
  }
}
