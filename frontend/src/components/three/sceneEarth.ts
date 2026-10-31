// Orbital Environment — Natural shaded Earth globe at [0, 0, 0] + inclined LEO
// chief-orbit ring + deterministic starfield + local LVLH reference grid.
// Supports two view modes:
// - "global" (Earth orbit view): Earth centered at [0, 0, 0] with satellites
//   orbiting all the way around the planet along an inclined orbital ring.
// - "local" (Formation array view): Earth hidden, showing the close-up 2:1
//   Clohessy-Wiltshire relative formation grid around [0, 0, 0].
// All colors derive strictly from tokens.css via sceneColors.ts (§13.1).
import * as THREE from "three";
import { SCENE_TOKENS, tokenColor } from "./sceneColors";
import type { OrbitViewMode } from "../../stores/uiStore";
import { buildGlobe } from "./sceneGlobe";

export const EARTH_RADIUS_FACTOR = 1.8; // big globe: the swarm skims just above the air, like real LEO
export const ORBIT_RADIUS_FACTOR = 2.35;
export const ORBIT_INCLINATION_RAD = (22 * Math.PI) / 180;
const EARTH_SPIN_RATE = 0.025;
const STAR_RADIUS_FACTOR = 45;
const STAR_COUNT = 2400;
const BRIGHT_STARS = 260; // the first N stars render larger and brighter

/** Deterministic LCG: identical starfield and continent texture on every load
 * (repo invariant 2: no unseeded RNG). */
function lcg(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

function smooth01(t: number): number {
  const c = Math.min(Math.max(t, 0), 1);
  return c * c * (3 - 2 * c);
}

function smoothstep(a: number, b: number, x: number): number {
  return smooth01((x - a) / (b - a));
}

interface Octave {
  p: number;
  lv: number;
  vals: Float32Array;
  weight: number;
}

function buildOctaves(rnd: () => number): Octave[] {
  const periods = [10, 20, 40, 80];
  const weights = [0.44, 0.28, 0.17, 0.11];
  return periods.map((p, i) => {
    const lv = p / 2;
    const vals = new Float32Array(p * lv);
    for (let k = 0; k < vals.length; k++) vals[k] = rnd();
    return { p, lv, vals, weight: weights[i] };
  });
}

function sampleOctave(o: Octave, u01: number, v01: number): number {
  const fx = u01 * o.p;
  const fy = v01 * o.lv;
  const tx = smooth01(fx - Math.floor(fx));
  const ty = smooth01(fy - Math.floor(fy));
  const x0 = Math.floor(fx) % o.p;
  const x1 = (x0 + 1) % o.p;
  const y0 = Math.min(Math.max(Math.floor(fy), 0), o.lv - 1);
  const y1 = Math.min(y0 + 1, o.lv - 1);
  const a = o.vals[y0 * o.p + x0];
  const b = o.vals[y0 * o.p + x1];
  const c = o.vals[y1 * o.p + x0];
  const d = o.vals[y1 * o.p + x1];
  const top = a + (b - a) * tx;
  const bot = c + (d - c) * tx;
  return top + (bot - top) * ty;
}

/** Build a smooth procedural equirectangular Earth texture using ocean blue,
 * continental green, and subtle lat/lon graticule lines from tokens.css. */
function buildEarthTexture(): THREE.CanvasTexture {
  const W = 512;
  const H = 256;
  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d");
  if (ctx === null) {
    return new THREE.CanvasTexture(canvas);
  }

  const ocean = tokenColor(SCENE_TOKENS.earthOcean);
  const land = tokenColor(SCENE_TOKENS.earthLand);
  const grat = tokenColor(SCENE_TOKENS.earthGraticule);
  const img = ctx.createImageData(W, H);
  const data = img.data;

  const rnd = lcg(19700101);
  const octaves = buildOctaves(rnd);

  for (let y = 0; y < H; y++) {
    const v01 = y / (H - 1);
    const polar = smoothstep(0.06, 0.16, Math.min(v01, 1 - v01));
    for (let x = 0; x < W; x++) {
      const u01 = x / W;
      let n = 0;
      for (const o of octaves) n += o.weight * sampleOctave(o, u01, v01);
      const landMask = smoothstep(0.48, 0.54, n * polar);

      // Subtle directional shading across the globe texture
      const shade = 0.78 + 0.22 * Math.sin(v01 * Math.PI);
      let r = (ocean.r * (1 - landMask) + land.r * landMask) * shade;
      let g = (ocean.g * (1 - landMask) + land.g * landMask) * shade;
      let b = (ocean.b * (1 - landMask) + land.b * landMask) * shade;

      // Subtle 30-deg lat/lon graticule lines
      const latDeg = v01 * 180;
      const lonDeg = u01 * 360;
      const onLat = Math.min(latDeg % 30, 30 - (latDeg % 30)) < 0.65;
      const onLon = Math.min(lonDeg % 30, 30 - (lonDeg % 30)) < 0.65;
      if (onLat || onLon) {
        r = r * 0.72 + grat.r * 0.28;
        g = g * 0.72 + grat.g * 0.28;
        b = b * 0.72 + grat.b * 0.28;
      }

      const idx = (y * W + x) * 4;
      data[idx] = Math.round(Math.min(1, Math.max(0, r)) * 255);
      data[idx + 1] = Math.round(Math.min(1, Math.max(0, g)) * 255);
      data[idx + 2] = Math.round(Math.min(1, Math.max(0, b)) * 255);
      data[idx + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.ClampToEdgeWrapping;
  tex.needsUpdate = true;
  return tex;
}

/** Inclined Chief-Orbit Ring encircling Earth at [0, 0, 0]. */
function buildOrbitRing(): THREE.Line {
  const N = 256;
  const pts: THREE.Vector3[] = [];
  const cosI = Math.cos(ORBIT_INCLINATION_RAD);
  const sinI = Math.sin(ORBIT_INCLINATION_RAD);
  for (let i = 0; i <= N; i++) {
    const t = (i / N) * Math.PI * 2;
    const x = Math.cos(t);
    const zFlat = Math.sin(t);
    const y = -zFlat * sinI;
    const z = zFlat * cosI;
    pts.push(new THREE.Vector3(x, y, z));
  }
  const line = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints(pts),
    new THREE.LineDashedMaterial({
      color: tokenColor(SCENE_TOKENS.orbit),
      transparent: true,
      opacity: 0.22,
      dashSize: 0.08,
      gapSize: 0.05,
      depthWrite: false,
    }),
  );
  line.computeLineDistances();
  return line;
}

export interface EnvFrame {
  center: [number, number, number];
  ringRadius: number;
}

export interface Environment {
  group: THREE.Group;
  trackExtent(maxR: number): number;
  setMode(mode: OrbitViewMode): void;
  refreshTheme(): void;
  frame(): EnvFrame;
  update(dt: number, reducedMotion: boolean): void;
  dispose(): void;
}

export function createEnvironment(): Environment {
  const group = new THREE.Group();

  let fallbackTex = buildEarthTexture();
  const globe = buildGlobe(fallbackTex, tokenColor(SCENE_TOKENS.atmo));
  const earthGroup = new THREE.Group();
  earthGroup.add(globe.group);
  group.add(earthGroup);

  const ring = buildOrbitRing();
  group.add(ring);

  // Starfield: deterministic points on a far sphere.
  const rnd = lcg(42);
  const starPos = new Float32Array(STAR_COUNT * 3);
  for (let i = 0; i < STAR_COUNT; i++) {
    const z = 2 * rnd() - 1;
    const t = 2 * Math.PI * rnd();
    const s = Math.sqrt(Math.max(0, 1 - z * z));
    starPos[i * 3] = s * Math.cos(t);
    starPos[i * 3 + 1] = s * Math.sin(t);
    starPos[i * 3 + 2] = z;
  }
  const starGeo = new THREE.BufferGeometry();
  starGeo.setAttribute("position", new THREE.BufferAttribute(starPos, 3));
  const starMat = new THREE.PointsMaterial({
    color: tokenColor(SCENE_TOKENS.star),
    size: 1.5,
    sizeAttenuation: false,
    transparent: true,
    opacity: 0.4,
    depthWrite: false,
  });
  starMat.size = 1.1;
  starMat.opacity = 0.55;
  const stars = new THREE.Points(starGeo, starMat);
  const brightGeo = new THREE.BufferGeometry();
  brightGeo.setAttribute("position", new THREE.BufferAttribute(starPos.slice(0, BRIGHT_STARS * 3), 3));
  const brightMat = starMat.clone();
  brightMat.size = 2.2;
  brightMat.opacity = 0.9;
  const brightStars = new THREE.Points(brightGeo, brightMat);
  const starGroup = new THREE.Group();
  starGroup.add(stars, brightStars);
  group.add(starGroup);

  let currentMode: OrbitViewMode = "global";
  let extent = 1000;
  let envFrame: EnvFrame = { center: [0, 0, 0], ringRadius: 1000 * ORBIT_RADIUS_FACTOR };
  let grid: THREE.GridHelper | null = null;

  function place(e: number): void {
    const earthR = e * EARTH_RADIUS_FACTOR;
    const orbitR = e * ORBIT_RADIUS_FACTOR;
    // Earth is ALWAYS centered at [0, 0, 0]; satellites orbit around [0, 0, 0]
    envFrame = {
      center: [0, 0, 0],
      ringRadius: currentMode === "global" ? orbitR : e * 1.35,
    };
    earthGroup.position.set(0, 0, 0);
    earthGroup.scale.setScalar(earthR);
    ring.position.set(0, 0, 0);
    ring.scale.setScalar(orbitR);
    starGroup.scale.setScalar(e * STAR_RADIUS_FACTOR);

    earthGroup.visible = currentMode === "global";
    ring.visible = currentMode === "global";
    if (grid !== null) {
      grid.visible = currentMode === "local";
    }
  }

  function rebuildGrid(maxR: number): void {
    if (grid !== null) {
      group.remove(grid);
      grid.dispose();
    }
    const border = tokenColor(SCENE_TOKENS.borderStrong);
    grid = new THREE.GridHelper(3.2 * maxR, 12, border, border);
    const mat = grid.material as THREE.Material;
    mat.transparent = true;
    mat.opacity = 0.32;
    grid.visible = currentMode === "local";
    group.add(grid);
  }

  rebuildGrid(1000);
  place(1000);

  let earthSpin = 0;
  return {
    group,
    trackExtent(maxR: number): number {
      if (maxR <= 0) return Math.max(extent, 1000);
      if (grid !== null && maxR <= extent * 1.5 && maxR >= extent * 0.4) return extent;
      extent = Math.max(maxR, 1000);
      rebuildGrid(extent);
      place(extent);
      return extent;
    },
    setMode(mode: OrbitViewMode): void {
      currentMode = mode;
      place(Math.max(extent, 1000));
    },
    refreshTheme(): void {
      fallbackTex.dispose();
      fallbackTex = buildEarthTexture();
      globe.setFallbackMap(fallbackTex);
      globe.setAtmoColor(tokenColor(SCENE_TOKENS.atmo));
      (ring.material as THREE.LineDashedMaterial).color = tokenColor(SCENE_TOKENS.orbit);
      starMat.color = tokenColor(SCENE_TOKENS.star);
      brightMat.color = tokenColor(SCENE_TOKENS.star);
      rebuildGrid(Math.max(extent, 1000));
    },
    frame(): EnvFrame {
      return envFrame;
    },
    update(dt: number, reducedMotion: boolean): void {
      if (!reducedMotion && currentMode === "global") {
        earthSpin += dt * EARTH_SPIN_RATE;
        globe.surface.rotation.y = earthSpin;
      }
      globe.update(dt, reducedMotion || currentMode !== "global");
    },
    dispose(): void {
      if (grid !== null) grid.dispose();
      globe.dispose();
      fallbackTex.dispose();
      ring.geometry.dispose();
      (ring.material as THREE.Material).dispose();
      starGeo.dispose();
      starMat.dispose();
      brightGeo.dispose();
      brightMat.dispose();
    },
  };
}
