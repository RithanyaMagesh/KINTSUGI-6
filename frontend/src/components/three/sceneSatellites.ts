// Per-satellite scene records — FRONTEND_SPEC §7.2 status colors + §22
// labels + §8.4 trails. Rebuilt after the 2026-09-30 user verdict: satellites
// became giant flat blobs when zoomed, so markers are now UNIT-sized
// billboarded disc+ring shapes rescaled EVERY FRAME to a constant apparent
// size (px target, clamped) — a zoomed-in satellite is a crisp disc with a
// ring, never a blob. Dead satellites render dim red with a cross marker and
// keep coasting (position comes straight from the wire). All colors come
// from tokens.css through sceneColors.ts (§13.1).
import * as THREE from "three";
import type { Satellite } from "../../types/satellite";
import { SCENE_TOKENS, statusToken, tokenColor } from "./sceneColors";
import type { LabelLayer } from "./sceneLabels";
import styles from "./SwarmScene.module.css";

export const TRAIL_MAX = 250; // §8.4: 150-250 points
export const TRAIL_INTERVAL_MS = 150; // ~6.7 Hz, inside the 5-10 Hz window

/** Constant apparent-size targets (screen px) and world-size clamp (fraction
 * of the swarm extent — binds only at extreme zoom-out, anti-speck). */
export const MARKER_TARGET_PX = 7.5;
export const MARKER_MIN_PX = 3.5;
export const MARKER_MAX_PX = 16;
export const MARKER_WORLD_MAX = 0.08;

export interface SatRecord {
  id: string;
  status: Satellite["status"]; // last synced (per-frame pulse + label priority)
  role: string;
  group: THREE.Group; // world position holder (never scaled)
  marker: THREE.Group; // billboarded; scaled to constant apparent size
  disc: THREE.Mesh; // pick target
  ring: THREE.Mesh; // also a pick target
  leaderRing: THREE.Mesh;
  cross: THREE.LineSegments;
  labelEl: HTMLButtonElement;
  trail: THREE.Line;
  trailPositions: Float32Array;
  trailColors: Float32Array;
  trailCount: number;
  lastTrailAt: number;
  screenR: number; // current dot radius on screen (px) — for label layout
  lastLabelText: string;
}

/** LVLH -> scene mapping used everywhere: scene x = along-track, y (up) =
 * radial (nadir = scene -y, so Earth hangs BELOW the formation from every
 * camera azimuth — 2026-10-04 staging rework), z = cross-track (repo
 * invariant 4). */
export function lvlhToScene(r: Satellite["r"]): [number, number, number] {
  return [r[1], r[0], r[2]];
}

/** World radius that renders a marker at `targetPx` on screen at `dist`,
 * clamped to a sane px band and a world ceiling (fraction of extent).
 * This is the "constant apparent size" rule — scale is recomputed per frame
 * from the camera distance. */
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
    new THREE.RingGeometry(1.55, 1.8, 40),
    new THREE.MeshBasicMaterial({
      color: tokenColor(statusToken(sat.status)),
      transparent: true,
      opacity: 0.55,
      side: THREE.DoubleSide,
      depthWrite: false,
    }),
  );
  // Leader marker: gold OUTLINE ring (§7.2 "gold outline or badge") — replaces
  // the old wireframe sphere that dominated the view.
  const leaderRing = new THREE.Mesh(
    new THREE.RingGeometry(2.05, 2.25, 44),
    new THREE.MeshBasicMaterial({
      color: tokenColor(SCENE_TOKENS.leader),
      transparent: true,
      opacity: 0.9,
      side: THREE.DoubleSide,
      depthWrite: false,
    }),
  );
  leaderRing.visible = false;
  // Dead-satellite cross: a small X over the dimmed disc.
  const crossGeo = new THREE.BufferGeometry();
  crossGeo.setAttribute(
    "position",
    new THREE.BufferAttribute(
      new Float32Array([-2.3, -2.3, 0, 2.3, 2.3, 0, -2.3, 2.3, 0, 2.3, -2.3, 0]),
      3,
    ),
  );
  const cross = new THREE.LineSegments(
    crossGeo,
    new THREE.LineBasicMaterial({
      color: tokenColor(statusToken("failed")),
      transparent: true,
      opacity: 1,
      depthWrite: false,
    }),
  );
  cross.visible = false;
  marker.add(disc, ring, leaderRing, cross);
  group.add(marker);

  const labelEl = document.createElement("button");
  labelEl.type = "button";
  labelEl.className = styles.satLabel;
  labelEl.style.pointerEvents = "auto";
  labels.root.appendChild(labelEl);
  const text = labelText(sat);
  labelEl.textContent = text;
  labelEl.dataset.labelKey = text; // cache key for the label-layer size cache
  labelEl.addEventListener("click", () => onPick(sat.id));

  const trailPositions = new Float32Array(TRAIL_MAX * 3);
  const trailColors = new Float32Array(TRAIL_MAX * 3);
  const trailGeo = new THREE.BufferGeometry();
  trailGeo.setAttribute("position", new THREE.BufferAttribute(trailPositions, 3));
  trailGeo.setAttribute("color", new THREE.BufferAttribute(trailColors, 3));
  trailGeo.setDrawRange(0, 0);
  // 1 px line, vertex colors fade head -> background (reads as fading alpha
  // on the opaque scene background) — clearly subordinate to the markers.
  const trail = new THREE.Line(
    trailGeo,
    new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.55,
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

/** Compact labels: dead satellites read "SAT-2 FAILED" (user verdict); live
 * satellites keep id + status (+ failure type while it still flies). */
function labelText(sat: Satellite): string {
  if (sat.status === "failed") return `${sat.id} FAILED`;
  return `${sat.id} ${sat.status.toUpperCase()}${sat.failureType !== undefined ? ` (${sat.failureType})` : ""}`;
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
  rec.trail.geometry.dispose();
  (rec.trail.material as THREE.Material).dispose();
  rec.labelEl.remove(); // detaches from labels.root if still attached
}

/** One satellite's data sync (per WS frame — NOT per rendered frame). Visual
 * scale/billboard work happens in updateMarkerView each rendered frame. */
export function syncSatellite(
  rec: SatRecord,
  sat: Satellite,
  opts: { selectedId: string | null; showTrails: boolean },
): void {
  rec.group.position.set(...lvlhToScene(sat.r));

  const statusCol = tokenColor(statusToken(sat.status));
  const failed = sat.status === "failed";
  const selected = sat.id === opts.selectedId;
  // 2026-10-04 legibility ask: failed markers read clearly — brighter disc and
  // a halo at the same weight as healthy (was 0.5 disc / 0.25 halo), the X at
  // full alpha. Color + X + pulse still carry the state (colorblind rule).
  (rec.disc.material as THREE.MeshBasicMaterial).color = statusCol;
  (rec.disc.material as THREE.MeshBasicMaterial).opacity = failed ? 0.7 : 1;
  const ringMat = rec.ring.material as THREE.MeshBasicMaterial;
  ringMat.color = selected ? tokenColor(SCENE_TOKENS.focus) : statusCol;
  ringMat.opacity = failed ? 0.55 : selected ? 0.95 : 0.55;
  rec.leaderRing.visible = sat.role === "leader";
  rec.cross.visible = failed;
  rec.trail.visible = opts.showTrails;
  rec.status = sat.status;
  rec.role = sat.role;

  const text = labelText(sat);
  if (text !== rec.lastLabelText) {
    rec.lastLabelText = text;
    rec.labelEl.textContent = text;
    rec.labelEl.dataset.labelKey = text; // invalidate the size cache
  }
  rec.labelEl.style.color = `var(${statusToken(sat.status)})`;
  rec.labelEl.style.borderColor = `var(${statusToken(sat.status)})`;
  rec.labelEl.style.fontWeight = selected ? "600" : "400";
}

/** Per rendered frame: billboard toward the camera + constant apparent size +
 * failed pulse (§13.5 reduced-motion swaps the pulse for a static marker). */
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
  const pulse = status === "failed" && !reducedMotion ? 1 + 0.25 * Math.sin(elapsed * 5) : 1;
  rec.marker.scale.setScalar(size.world * pulse);
  rec.screenR = size.screenPx;
}

/** Append one trail sample with head->tail fade. `now` is performance.now() —
 * a cadence gate only (§19), never a displayed value. Failed satellites
 * freeze their trail (§8.4). */
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
    rec.trailPositions.copyWithin(0, 3); // drop-oldest: no wrap-around jump
    rec.trailColors.copyWithin(0, 3);
    i = (TRAIL_MAX - 1) * 3;
  }
  const [x, y, z] = lvlhToScene(sat.r);
  rec.trailPositions[i] = x;
  rec.trailPositions[i + 1] = y;
  rec.trailPositions[i + 2] = z;
  // Rewrite the fade: newest point = status color, oldest = background.
  const head = tokenColor(statusToken(sat.status));
  const col = new THREE.Color();
  const n = rec.trailCount;
  for (let k = 0; k < n; k++) {
    const t = n <= 1 ? 1 : k / (n - 1);
    col.copy(bg).lerp(head, t * t); // quadratic: bright head, long dim tail
    rec.trailColors[k * 3] = col.r;
    rec.trailColors[k * 3 + 1] = col.g;
    rec.trailColors[k * 3 + 2] = col.b;
  }
  (rec.trail.geometry.getAttribute("position") as THREE.BufferAttribute).needsUpdate = true;
  (rec.trail.geometry.getAttribute("color") as THREE.BufferAttribute).needsUpdate = true;
  rec.trail.geometry.setDrawRange(0, rec.trailCount);
}
