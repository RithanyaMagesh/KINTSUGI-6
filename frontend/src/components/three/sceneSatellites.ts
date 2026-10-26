// Per-satellite scene records — FRONTEND_SPEC §7.2 status colors + §22 labels
// + §8.4 trails + Dual-View Coordinate Mapping:
// - "global" (Earth orbit view): maps LVLH formation phase around the inclined
//   chief orbital ring encircling Earth at [0, 0, 0], advancing with orbital
//   angular velocity so satellites visibly orbit around Earth.
// - "local" (Formation array view): maps raw LVLH coordinates [y, x, z] onto
//   the close-up 2:1 Clohessy-Wiltshire relative formation grid.
// All colors derive strictly from tokens.css via sceneColors.ts (§13.1).
import * as THREE from "three";
import type { Satellite } from "../../types/satellite";
import type { OrbitViewMode } from "../../stores/uiStore";
import { ORBIT_INCLINATION_RAD, ORBIT_RADIUS_FACTOR } from "./sceneEarth";
import { SCENE_TOKENS, statusToken, tokenColor } from "./sceneColors";
import type { LabelLayer } from "./sceneLabels";
import styles from "./SwarmScene.module.css";

export const TRAIL_MAX = 220;
export const TRAIL_INTERVAL_MS = 150;

export const MARKER_TARGET_PX = 8.5;
export const MARKER_MIN_PX = 4.0;
export const MARKER_MAX_PX = 16;
export const MARKER_WORLD_MAX = 0.11;

export const MARKER_EXTENT = 2.5;
export const MARKER_CLEAR = 2.6;

interface CoordTransformState {
  mode: OrbitViewMode;
  extent: number;
  amplitude: number;
  orbitPhase: number;
}

const coordState: CoordTransformState = {
  mode: "global",
  extent: 1000,
  amplitude: 700,
  orbitPhase: 0,
};

export function setSceneCoordinateTransform(next: Partial<CoordTransformState>): void {
  if (next.mode !== undefined) coordState.mode = next.mode;
  if (next.extent !== undefined && next.extent > 0) coordState.extent = next.extent;
  if (next.amplitude !== undefined && next.amplitude > 0) coordState.amplitude = next.amplitude;
  if (next.orbitPhase !== undefined) coordState.orbitPhase = next.orbitPhase;
}

export function getSceneCoordinateMode(): OrbitViewMode {
  return coordState.mode;
}

const COS_I = Math.cos(ORBIT_INCLINATION_RAD);
const SIN_I = Math.sin(ORBIT_INCLINATION_RAD);

/** Maps an LVLH vector [x_radial, y_along_track, z_cross_track] into scene
 * coordinates for the active view mode ("global" Earth orbit vs "local" LVLH array). */
export function lvlhToScene(r: Satellite["r"]): [number, number, number] {
  const [x, y, z] = r;
  if (coordState.mode === "local") {
    return [y, x, z];
  }
  const E = Math.max(coordState.extent, 1000);
  const A = coordState.amplitude > 0 ? coordState.amplitude : E * 0.55;
  const psi = x === 0 && y === 0 ? 0 : Math.atan2(-y / 2, x);
  const theta = psi + coordState.orbitPhase;
  const rho = Math.hypot(x, y / 2);
  const radialOffset = Math.min(Math.max((rho - A) * 0.35, -E * 0.45), E * 0.85);
  const R = E * ORBIT_RADIUS_FACTOR + radialOffset;
  const yFlat = Math.min(Math.max((z - x) * 0.3, -E * 0.45), E * 0.45);
  const xOrb = R * Math.cos(theta);
  const zFlat = R * Math.sin(theta);
  const yOrb = yFlat * COS_I - zFlat * SIN_I;
  const zOrb = yFlat * SIN_I + zFlat * COS_I;
  return [xOrb, yOrb, zOrb];
}

export interface SatRecord {
  id: string;
  status: Satellite["status"];
  role: string;
  group: THREE.Group;
  marker: THREE.Group;
  disc: THREE.Mesh;
  ring: THREE.Mesh;
  leaderRing: THREE.Mesh;
  cross: THREE.LineSegments;
  driftVector: THREE.Line;
  labelEl: HTMLButtonElement;
  trail: THREE.Line;
  trailPositions: Float32Array;
  trailColors: Float32Array;
  trailCount: number;
  lastTrailAt: number;
  screenR: number;
  lastLabelText: string;
}

export function markerWorldRadius(
  dist: number,
  viewportH: number,
  fovYRad: number,
  targetPx: number,
  extent: number,
): { world: number; screenPx: number } {
  const worldPerPx = (2 * Math.tan(fovYRad / 2) * Math.max(dist, 1e-6)) / Math.max(viewportH, 1);
  const px = Math.min(Math.max(targetPx, MARKER_MIN_PX), MARKER_MAX_PX);
  let world = px * worldPerPx;
  const worldMax = Math.max(extent, 1e-6) * MARKER_WORLD_MAX;
  if (world > worldMax) world = worldMax;
  return { world, screenPx: world / worldPerPx };
}

export function createSatelliteRecord(
  sat: Satellite,
  onPick: (id: string) => void,
  labels: LabelLayer,
): SatRecord {
  const group = new THREE.Group();
  const marker = new THREE.Group();

  const disc = new THREE.Mesh(
    new THREE.CircleGeometry(1, 28),
    new THREE.MeshBasicMaterial({
      color: tokenColor(statusToken(sat.status)),
      transparent: true,
      side: THREE.DoubleSide,
      depthWrite: false,
    }),
  );
  const ring = new THREE.Mesh(
    new THREE.RingGeometry(1.55, 1.82, 40),
    new THREE.MeshBasicMaterial({
      color: tokenColor(statusToken(sat.status)),
      transparent: true,
      opacity: 0.65,
      side: THREE.DoubleSide,
      depthWrite: false,
    }),
  );
  const leaderRing = new THREE.Mesh(
    new THREE.RingGeometry(2.1, 2.38, 44),
    new THREE.MeshBasicMaterial({
      color: tokenColor(SCENE_TOKENS.leader),
      transparent: true,
      opacity: 0.92,
      side: THREE.DoubleSide,
      depthWrite: false,
    }),
  );
  leaderRing.visible = false;

  const crossGeo = new THREE.BufferGeometry();
  crossGeo.setAttribute(
    "position",
    new THREE.BufferAttribute(
      new Float32Array([
        -1.9, -1.9, 0, 1.9, 1.9, 0,
        -1.9, 1.9, 0, 1.9, -1.9, 0,
      ]),
      3,
    ),
  );
  const cross = new THREE.LineSegments(
    crossGeo,
    new THREE.LineBasicMaterial({
      color: tokenColor(statusToken("failed")),
      transparent: true,
      opacity: 0.95,
      depthWrite: false,
    }),
  );
  cross.visible = false;
  marker.add(disc, ring, leaderRing, cross);
  group.add(marker);

  // Ballistic drift velocity vector for failed satellites in local view
  const driftGeo = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(0, 0, 0),
    new THREE.Vector3(0, 0, 0),
  ]);
  const driftVector = new THREE.Line(
    driftGeo,
    new THREE.LineBasicMaterial({
      color: tokenColor(statusToken("failed")),
      transparent: true,
      opacity: 0.82,
      depthWrite: false,
    }),
  );
  driftVector.visible = false;
  group.add(driftVector);

  const labelEl = document.createElement("button");
  labelEl.type = "button";
  labelEl.className = styles.satLabel;
  labelEl.style.pointerEvents = "auto";
  labelEl.style.padding = "0 4px";
  labelEl.style.lineHeight = "1.3";
  labels.root.appendChild(labelEl);
  const text = labelText(sat);
  labelEl.textContent = text;
  labelEl.dataset.labelKey = text;
  labelEl.addEventListener("click", () => onPick(sat.id));

  const trailPositions = new Float32Array(TRAIL_MAX * 3);
  const trailColors = new Float32Array(TRAIL_MAX * 3);
  const trailGeo = new THREE.BufferGeometry();
  trailGeo.setAttribute("position", new THREE.BufferAttribute(trailPositions, 3));
  trailGeo.setAttribute("color", new THREE.BufferAttribute(trailColors, 3));
  trailGeo.setDrawRange(0, 0);
  const trail = new THREE.Line(
    trailGeo,
    new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.65,
      depthWrite: false,
    }),
  );

  return {
    id: sat.id,
    status: sat.status,
    role: sat.role,
    group,
    marker,
    disc,
    ring,
    leaderRing,
    cross,
    driftVector,
    labelEl,
    trail,
    trailPositions,
    trailColors,
    trailCount: 0,
    lastTrailAt: 0,
    screenR: MARKER_TARGET_PX,
    lastLabelText: text,
  };
}

function labelText(sat: Satellite): string {
  const roleShort = sat.role === "leader" ? "leader" : sat.role === "downlink" ? "downlink" : "imager";
  if (sat.status === "failed") return `${sat.id} · DEAD`;
  return `${sat.id} · ${roleShort}`;
}

export function clearSatelliteTrail(rec: SatRecord): void {
  rec.trailCount = 0;
  rec.trail.geometry.setDrawRange(0, 0);
}

export function disposeSatelliteRecord(rec: SatRecord, scene: THREE.Scene): void {
  scene.remove(rec.group, rec.trail);
  rec.disc.geometry.dispose();
  (rec.disc.material as THREE.Material).dispose();
  rec.ring.geometry.dispose();
  (rec.ring.material as THREE.Material).dispose();
  rec.leaderRing.geometry.dispose();
  (rec.leaderRing.material as THREE.Material).dispose();
  rec.cross.geometry.dispose();
  (rec.cross.material as THREE.Material).dispose();
  rec.driftVector.geometry.dispose();
  (rec.driftVector.material as THREE.Material).dispose();
  rec.trail.geometry.dispose();
  (rec.trail.material as THREE.Material).dispose();
  rec.labelEl.remove();
}

export function syncSatellite(
  rec: SatRecord,
  sat: Satellite,
  opts: { selectedId: string | null; showTrails: boolean; extent?: number },
): void {
  rec.group.position.set(...lvlhToScene(sat.r));

  const statusCol = tokenColor(statusToken(sat.status));
  const failed = sat.status === "failed";
  const selected = sat.id === opts.selectedId;
  const extent = opts.extent ?? 1000;

  (rec.disc.material as THREE.MeshBasicMaterial).color = statusCol;
  (rec.disc.material as THREE.MeshBasicMaterial).opacity = failed ? 0.78 : 1;
  const ringMat = rec.ring.material as THREE.MeshBasicMaterial;
  ringMat.color = selected ? tokenColor(SCENE_TOKENS.focus) : statusCol;
  ringMat.opacity = failed ? 0.65 : selected ? 0.98 : 0.62;
  rec.leaderRing.visible = sat.role === "leader" && !failed;
  rec.cross.visible = failed;
  rec.trail.visible = opts.showTrails;
  rec.status = sat.status;
  rec.role = sat.role;

  // Ballistic drift velocity vector on failed satellites in local formation view
  const vMag = Math.hypot(sat.v[0], sat.v[1], sat.v[2]);
  if (failed && vMag > 1e-5 && coordState.mode === "local") {
    const [vx, vy, vz] = [sat.v[1], sat.v[0], sat.v[2]];
    const scale = (extent * 0.22) / vMag;
    const pos = rec.driftVector.geometry.getAttribute("position") as THREE.BufferAttribute;
    pos.setXYZ(0, 0, 0, 0);
    pos.setXYZ(1, vx * scale, vy * scale, vz * scale);
    pos.needsUpdate = true;
    rec.driftVector.visible = true;
  } else {
    rec.driftVector.visible = false;
  }

  const text = labelText(sat);
  if (text !== rec.lastLabelText) {
    rec.lastLabelText = text;
    rec.labelEl.textContent = text;
    rec.labelEl.dataset.labelKey = text;
  }
  rec.labelEl.style.color = `var(${statusToken(sat.status)})`;
  rec.labelEl.style.borderColor = `var(${statusToken(sat.status)})`;
  rec.labelEl.style.fontWeight = selected ? "600" : "400";
}

export function updateMarkerView(
  rec: SatRecord,
  camera: THREE.PerspectiveCamera,
  viewportH: number,
  extent: number,
  elapsed: number,
  reducedMotion: boolean,
  status: Satellite["status"],
): void {
  rec.marker.quaternion.copy(camera.quaternion);
  const dist = camera.position.distanceTo(rec.group.position);
  const size = markerWorldRadius(
    dist,
    viewportH,
    (camera.fov * Math.PI) / 180,
    MARKER_TARGET_PX,
    extent,
  );
  const pulse = status === "failed" && !reducedMotion ? 1 + 0.22 * Math.sin(elapsed * 5) : 1;
  rec.marker.scale.setScalar(size.world * pulse);
  rec.screenR = size.screenPx;
}

export function pushTrail(
  rec: SatRecord,
  sat: Satellite,
  now: number,
  bg: THREE.Color,
): void {
  if (sat.status === "failed") return;
  if (now - rec.lastTrailAt < TRAIL_INTERVAL_MS) return;
  rec.lastTrailAt = now;
  let i: number;
  if (rec.trailCount < TRAIL_MAX) {
    i = rec.trailCount * 3;
    rec.trailCount += 1;
  } else {
    rec.trailPositions.copyWithin(0, 3);
    rec.trailColors.copyWithin(0, 3);
    i = (TRAIL_MAX - 1) * 3;
  }
  const [x, y, z] = lvlhToScene(sat.r);
  rec.trailPositions[i] = x;
  rec.trailPositions[i + 1] = y;
  rec.trailPositions[i + 2] = z;
  const head = tokenColor(statusToken(sat.status));
  const col = new THREE.Color();
  const n = rec.trailCount;
  for (let k = 0; k < n; k++) {
    const t = n <= 1 ? 1 : k / (n - 1);
    col.copy(bg).lerp(head, t * t);
    rec.trailColors[k * 3] = col.r;
    rec.trailColors[k * 3 + 1] = col.g;
    rec.trailColors[k * 3 + 2] = col.b;
  }
  (rec.trail.geometry.getAttribute("position") as THREE.BufferAttribute).needsUpdate = true;
  (rec.trail.geometry.getAttribute("color") as THREE.BufferAttribute).needsUpdate = true;
  rec.trail.geometry.setDrawRange(0, rec.trailCount);
}
