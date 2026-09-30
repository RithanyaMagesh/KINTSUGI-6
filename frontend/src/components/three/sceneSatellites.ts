// Per-satellite scene records — FRONTEND_SPEC §7.2 status colors + §22
// labels + §8.4 trails. Extracted from swarmScene.ts to keep files ~300
// lines. All colors come from tokens.css through sceneColors.ts (§13.1).
import * as THREE from "three";
import { CSS2DObject } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import type { Satellite } from "../../types/satellite";
import { SCENE_TOKENS, statusToken, tokenColor } from "./sceneColors";
import styles from "./SwarmScene.module.css";

export const TRAIL_MAX = 250; // §8.4: 150-250 points
export const TRAIL_INTERVAL_MS = 150; // ~6.7 Hz, inside the 5-10 Hz window

export interface SatRecord {
  id: string;
  group: THREE.Group;
  mesh: THREE.Mesh;
  leaderRing: THREE.Mesh;
  label: CSS2DObject;
  labelEl: HTMLButtonElement;
  trail: THREE.Line;
  trailPositions: Float32Array;
  trailCount: number;
  lastTrailAt: number;
  radius: number; // body radius in scene units (m)
}

export function createSatelliteRecord(
  sat: Satellite,
  extent: number,
  onPick: (id: string) => void,
): SatRecord {
  const radius = Math.max(20, extent * 0.02 || 20);
  const group = new THREE.Group();
  const mesh = new THREE.Mesh(
    new THREE.SphereGeometry(radius, 20, 14),
    new THREE.MeshBasicMaterial({ color: tokenColor(statusToken(sat.status)) }),
  );
  // Leader marker: gold OUTLINE + the role label (§7.2 leader row, §22).
  const leaderRing = new THREE.Mesh(
    new THREE.SphereGeometry(radius * 1.5, 12, 8),
    new THREE.MeshBasicMaterial({ color: tokenColor(SCENE_TOKENS.leader), wireframe: true }),
  );
  leaderRing.visible = false;
  group.add(mesh, leaderRing);

  const labelEl = document.createElement("button");
  labelEl.type = "button";
  labelEl.className = styles.satLabel;
  labelEl.style.pointerEvents = "auto";
  const label = new CSS2DObject(labelEl);
  labelEl.addEventListener("click", () => onPick(sat.id));

  const trailPositions = new Float32Array(TRAIL_MAX * 3);
  const trailGeo = new THREE.BufferGeometry();
  trailGeo.setAttribute("position", new THREE.BufferAttribute(trailPositions, 3));
  trailGeo.setDrawRange(0, 0);
  const trail = new THREE.Line(
    trailGeo,
    new THREE.LineBasicMaterial({
      color: tokenColor(statusToken(sat.status)),
      transparent: true,
      opacity: 0.35, // §8.4: opacity 0.25-0.45
    }),
  );

  return {
    id: sat.id,
    group,
    mesh,
    leaderRing,
    label,
    labelEl,
    trail,
    trailPositions,
    trailCount: 0,
    lastTrailAt: 0,
    radius,
  };
}

export function disposeSatelliteRecord(rec: SatRecord, scene: THREE.Scene): void {
  scene.remove(rec.group, rec.trail, rec.label);
  rec.mesh.geometry.dispose();
  (rec.mesh.material as THREE.Material).dispose();
  rec.leaderRing.geometry.dispose();
  (rec.leaderRing.material as THREE.Material).dispose();
  rec.trail.geometry.dispose();
  (rec.trail.material as THREE.Material).dispose();
  rec.labelEl.remove();
}

/** Rescale bodies when the auto-fit extent changes. */
export function resizeSatelliteRecord(rec: SatRecord, radius: number): void {
  rec.radius = radius;
  rec.mesh.geometry.dispose();
  rec.mesh.geometry = new THREE.SphereGeometry(radius, 20, 14);
  rec.leaderRing.geometry.dispose();
  rec.leaderRing.geometry = new THREE.SphereGeometry(radius * 1.5, 12, 8);
}

/** LVLH -> scene mapping used everywhere: scene x = along-track, y (up) =
 * cross-track, z = radial (repo invariant 4). */
export function lvlhToScene(r: Satellite["r"]): [number, number, number] {
  return [r[1], r[2], r[0]];
}

/** One satellite's per-frame visual sync. `reducedMotion` swaps the §13.5
 * failed pulse for a static marker; the status TEXT label is always present
 * (§22 colorblind rule: never color alone). */
export function syncSatellite(
  rec: SatRecord,
  sat: Satellite,
  opts: {
    selectedId: string | null;
    reducedMotion: boolean;
    elapsed: number;
    showLabels: boolean;
    showTrails: boolean;
  },
): void {
  rec.group.position.set(...lvlhToScene(sat.r));

  const color = tokenColor(statusToken(sat.status));
  (rec.mesh.material as THREE.MeshBasicMaterial).color = color;
  rec.leaderRing.visible = sat.role === "leader";

  if (sat.status === "failed") {
    const pulse = opts.reducedMotion ? 1 : 1 + 0.3 * Math.sin(opts.elapsed * 6);
    rec.group.scale.setScalar(pulse);
  } else {
    rec.group.scale.setScalar(1);
  }

  rec.labelEl.textContent = `${sat.id} ${sat.status.toUpperCase()}${
    sat.failureType !== undefined ? ` (${sat.failureType})` : ""
  }`;
  rec.labelEl.style.color = `var(${statusToken(sat.status)})`;
  rec.labelEl.style.borderColor = `var(${statusToken(sat.status)})`;
  rec.labelEl.style.fontWeight = sat.id === opts.selectedId ? "600" : "400";
  rec.label.visible = opts.showLabels;
  rec.trail.visible = opts.showTrails;
  // The label lives in the SCENE (not the pulsing group) so the failed pulse
  // never rescales the text.
  rec.label.position
    .copy(rec.group.position)
    .add(new THREE.Vector3(0, rec.radius * 2.2, 0));
}

/** Append one trail sample. `now` is performance.now() — a cadence gate only
 * (§19), never a displayed value. Failed satellites freeze their trail. */
export function pushTrail(rec: SatRecord, sat: Satellite, now: number): void {
  if (sat.status === "failed") return;
  if (now - rec.lastTrailAt < TRAIL_INTERVAL_MS) return;
  rec.lastTrailAt = now;
  let i: number;
  if (rec.trailCount < TRAIL_MAX) {
    i = rec.trailCount * 3;
    rec.trailCount += 1;
  } else {
    rec.trailPositions.copyWithin(0, 3); // drop-oldest: no wrap-around jump
    i = (TRAIL_MAX - 1) * 3;
  }
  const [x, y, z] = lvlhToScene(sat.r);
  rec.trailPositions[i] = x;
  rec.trailPositions[i + 1] = y;
  rec.trailPositions[i + 2] = z;
  (rec.trail.material as THREE.LineBasicMaterial).color = tokenColor(statusToken(sat.status));
  (rec.trail.geometry.getAttribute("position") as THREE.BufferAttribute).needsUpdate = true;
  rec.trail.geometry.setDrawRange(0, rec.trailCount);
}
