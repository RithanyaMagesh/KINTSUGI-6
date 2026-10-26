// Stylized environment — Earth at the RING CENTRE + faint starfield + the
// chief-orbit ring (2026-10-04 staging, user verdicts: "satellites should be
// ORBITING Earth", then bug 3: "didn't even make Earth the middle"). LVLH +x
// is radial AWAY from Earth (repo invariant 4) and lvlhToScene maps LVLH x ->
// scene y (up), so nadir (-x LVLH) is scene -y: Earth hangs BELOW the
// formation's frame origin from every camera azimuth, and the chief orbit is
// a dashed circle CENTRED ON EARTH through that origin, in the orbital plane
// (scene x-y = along-track x radial; the chief's cross-track is 0). The
// camera treats the ring centre (= Earth centre, exposed via frame()) as the
// orbited body it frames — Earth-centred fit in sceneCamera.ts; the ring's
// dashes drift along-track as the slow motion cue.
// The texture is seeded multi-octave value noise, bilinear-interpolated and
// wrapping cleanly in longitude: smooth blended landmasses, no square blocks. Sizes
// are stylized multiples of the measured swarm extent (caption: "not to
// scale"). No external textures, no new deps. All colors via sceneColors.ts.
import * as THREE from "three";
import { SCENE_TOKENS, tokenColor } from "./sceneColors";

// Visual constants (multiples of the measured swarm extent).
const EARTH_RADIUS_FACTOR = 2.6; // planet radius; ring = a few extents out, so the
// pulled-back Earth-centred frame still reads (caption: "not to scale")
const LIMB_GAP_FACTOR = 0.9; // formation origin -> limb clearance
const RING_DASH_FACTOR = 0.45; // orbit-ring dash length (world)
const RING_GAP_FACTOR = 0.3;
const RING_OPACITY = 0.4; // thin, low-alpha chrome
const ORBIT_DRIFT_RATE = 0.05; // rad/s ring dash drift — a slow crawl
const EARTH_SPIN_RATE = 0.02; // rad/s surface roll, prograde
const STAR_RADIUS_FACTOR = 45;
const STAR_COUNT = 700;

/** Deterministic LCG: the starfield and texture noise must be identical on
 * every load (repo invariant 2 spirit: no unseeded RNG). Never Math.random. */
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

/** sRGB bytes of a token color (getStyle/getHexString round-trips the CSS
 * value, so canvas pixels match the chrome palette exactly). */
function rgbOf(color: THREE.Color): [number, number, number] {
  const hex = color.getHexString();
  return [
    Number.parseInt(hex.slice(0, 2), 16),
    Number.parseInt(hex.slice(2, 4), 16),
    Number.parseInt(hex.slice(4, 6), 16),
  ];
}

/** One noise octave: p cells around the equator (periodic in u), p/2
 * pole-to-pole. Bilinear + smoothstep sampling — smooth blobs, no blocks. */
interface Octave {
  p: number;
  lv: number;
  vals: Float32Array;
  weight: number;
}

function buildOctaves(rnd: () => number): Octave[] {
  const periods = [12, 24, 48, 96];
  const weights = [0.42, 0.27, 0.18, 0.13];
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
  const x0 = Math.floor(fx) % o.p; // periodic in u — seamless equirect wrap
  const x1 = (x0 + 1) % o.p;
  const y0 = Math.min(Math.max(Math.floor(fy), 0), o.lv - 1); // clamped in v
  const y1 = Math.min(y0 + 1, o.lv - 1);
  const a = o.vals[y0 * o.p + x0];
  const b = o.vals[y0 * o.p + x1];
  const c = o.vals[y1 * o.p + x0];
  const d = o.vals[y1 * o.p + x1];
  const top = a + (b - a) * tx;
  const bot = c + (d - c) * tx;
  return top + (bot - top) * ty;
}

/** Canvas texture 2048x1024: a 1024x512 per-pixel value-noise field (ocean ->
 * land with a soft coast band, subtle relief shading, land faded toward the
 * poles so equirect pinching never shows) bilinear-upscaled 2x, plus a faint
 * graticule. One-time cost (~50 ms). */
function buildEarthTexture(): THREE.CanvasTexture {
  const W = 1024;
  const H = 512;
  const w = W * 2;
  const h = H * 2;
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (ctx === null) throw new Error("2D canvas context unavailable");
  const rnd = lcg(19700101);
  const [ocR, ocG, ocB] = rgbOf(tokenColor(SCENE_TOKENS.earthOcean));
  const [laR, laG, laB] = rgbOf(tokenColor(SCENE_TOKENS.earthLand));
  const octaves = buildOctaves(rnd);

  const field = document.createElement("canvas");
  field.width = W;
  field.height = H;
  const fctx = field.getContext("2d");
  if (fctx === null) throw new Error("2D canvas context unavailable");
  const img = fctx.createImageData(W, H);
  const px = img.data;
  for (let y = 0; y < H; y++) {
    const v01 = (y + 0.5) / H;
    const polar = smoothstep(0.06, 0.14, Math.min(v01, 1 - v01));
    for (let x = 0; x < W; x++) {
      const u01 = (x + 0.5) / W;
      let n = 0;
      for (const o of octaves) n += o.weight * sampleOctave(o, u01, v01);
      const t = smoothstep(0.52, 0.6, n) * polar;
      const shade = 0.82 + 0.36 * n; // subtle relief in both media
      const i = (y * W + x) * 4;
      px[i] = Math.min(255, (ocR + (laR - ocR) * t) * shade);
      px[i + 1] = Math.min(255, (ocG + (laG - ocG) * t) * shade);
      px[i + 2] = Math.min(255, (ocB + (laB - ocB) * t) * shade);
      px[i + 3] = 255;
    }
  }
  fctx.putImageData(img, 0, 0);
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(field, 0, 0, W, H, 0, 0, w, h);

  // Faint graticule: meridians + parallels every 15 deg, brighter equator.
  // 1 px at 2048 — texture detail, never a UI element.
  ctx.lineWidth = 1;
  ctx.strokeStyle = tokenColor(SCENE_TOKENS.earthGraticule).getStyle();
  ctx.globalAlpha = 0.16;
  for (let i = 0; i <= 24; i++) {
    const x = (i * w) / 24;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();
  }
  for (let j = 1; j < 12; j++) {
    const y = (j * h) / 12;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();
  }
  ctx.globalAlpha = 0.28;
  ctx.beginPath();
  ctx.moveTo(0, h / 2);
  ctx.lineTo(w, h / 2);
  ctx.stroke();

  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  return tex;
}

/** Backside fresnel-style rim: the planet mesh writes depth, so only the
 * annulus outside the silhouette shows the shell — a thin glowing limb. */
function buildAtmosphere(): THREE.Mesh {
  const mat = new THREE.ShaderMaterial({
    uniforms: { uColor: { value: tokenColor(SCENE_TOKENS.atmo) } },
    vertexShader: /* glsl */ `
      varying vec3 vNormal;
      void main() {
        vNormal = normalize(normalMatrix * normal);
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }
    `,
    fragmentShader: /* glsl */ `
      uniform vec3 uColor;
      varying vec3 vNormal;
      void main() {
        float rim = pow(clamp(0.72 - dot(vNormal, vec3(0.0, 0.0, 1.0)), 0.0, 2.0), 3.5);
        gl_FragColor = vec4(uColor * rim * 0.55, 1.0);
      }
    `,
    side: THREE.BackSide,
    blending: THREE.AdditiveBlending,
    transparent: true,
    depthWrite: false,
  });
  return new THREE.Mesh(new THREE.SphereGeometry(1.15, 72, 48), mat);
}

/** Chief-orbit ring: unit circle in the local x-y plane (the orbital plane:
 * along-track x radial), dashed, scaled+positioned so the circle passes
 * through the formation's frame origin. Dashes drift along-track in
 * update() — the "moving along the orbit" cue. */
function buildOrbitRing(): THREE.Line {
  const N = 256;
  const pts: THREE.Vector3[] = [];
  for (let i = 0; i <= N; i++) {
    const t = (i / N) * Math.PI * 2;
    pts.push(new THREE.Vector3(Math.cos(t), Math.sin(t), 0));
  }
  const line = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints(pts),
    new THREE.LineDashedMaterial({
      color: tokenColor(SCENE_TOKENS.orbit),
      transparent: true,
      opacity: RING_OPACITY,
      dashSize: 0.12, // unit-circle arc units — rescaled to extent in place()
      gapSize: 0.08,
      depthWrite: false,
    }),
  );
  line.computeLineDistances();
  return line;
}

/** The placement the camera frames: the chief-orbit ring centre (= Earth's
 * centre) and the ring radius — the circle the formation rides. */
export interface EnvFrame {
  center: [number, number, number];
  ringRadius: number;
}

export interface Environment {
  group: THREE.Group;
  /** Re-fit the faint reference grid + body scales when the measured swarm
   * extent leaves the current scale band; returns the tracked extent. */
  trackExtent(maxR: number): number;
  /** The staging in effect: ring centre (= Earth) + ring radius — the fit
   * subject of the Earth-centred camera (sceneCamera.ts). */
  frame(): EnvFrame;
  update(dt: number, reducedMotion: boolean): void;
  dispose(): void;
}

export function createEnvironment(): Environment {
  const group = new THREE.Group();

  // Lights affect only the lit Earth material; every marker is MeshBasicMaterial.
  const white = tokenColor(SCENE_TOKENS.ink).getHex();
  const dir = new THREE.DirectionalLight(white, 2.4);
  dir.position.set(3, 2, 2); // overhead-ish sun: the visible upper hemisphere reads bright
  const amb = new THREE.AmbientLight(white, 0.5); // was 0.32 — Earth is bigger now, keep it readable
  group.add(dir, amb);

  const earth = new THREE.Mesh(
    new THREE.SphereGeometry(1, 96, 64), // smooth silhouette — Earth spans half the frame
    new THREE.MeshLambertMaterial({ map: buildEarthTexture() }),
  );
  const atmo = buildAtmosphere();
  const earthGroup = new THREE.Group();
  earthGroup.add(earth, atmo);
  group.add(earthGroup);

  const ring = buildOrbitRing();
  group.add(ring);

  // Starfield: points on a unit sphere, scaled far out. Seeded, tiny, faint.
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
  const stars = new THREE.Points(
    starGeo,
    new THREE.PointsMaterial({
      color: tokenColor(SCENE_TOKENS.star),
      size: 1.6, // px — sizeAttenuation false
      sizeAttenuation: false,
      transparent: true,
      opacity: 0.45,
      depthWrite: false,
    }),
  );
  const starGroup = new THREE.Group();
  starGroup.add(stars);
  group.add(starGroup);

  /** One staging pass: Earth's top limb sits LIMB_GAP below the formation
   * origin; the ring (radius = Earth-center distance, centred on Earth)
   * passes through it. The placement is exposed via frame() for the camera. */
  let envFrame: EnvFrame = { center: [0, 0, 0], ringRadius: 0 };
  function place(e: number): void {
    const radius = e * EARTH_RADIUS_FACTOR;
    const centerDist = radius + e * LIMB_GAP_FACTOR;
    envFrame = { center: [0, -centerDist, 0], ringRadius: centerDist };
    earthGroup.scale.setScalar(radius);
    earthGroup.position.set(0, -centerDist, 0); // nadir = scene -y (lvlhToScene)
    ring.position.copy(earthGroup.position);
    ring.scale.setScalar(centerDist);
    const rm = ring.material as THREE.LineDashedMaterial;
    rm.dashSize = (e * RING_DASH_FACTOR) / centerDist; // lineDistance attr is unit-arc
    rm.gapSize = (e * RING_GAP_FACTOR) / centerDist;
    starGroup.scale.setScalar(e * STAR_RADIUS_FACTOR);
  }
  place(1000); // pre-data staging (the §20 notice overlay covers the canvas)

  let extent = 0;
  let grid: THREE.GridHelper | null = null;
  let earthSpin = 0;
  return {
    group,
    trackExtent(maxR: number): number {
      if (maxR <= 0) return Math.max(extent, 1000);
      // Scale-band check: re-fit only when the swarm leaves [0.4x, 1.5x].
      if (grid !== null && maxR <= extent * 1.5 && maxR >= extent * 0.4) return extent;
      extent = maxR;
      if (grid !== null) {
        group.remove(grid);
        grid.dispose();
      }
      const border = tokenColor(SCENE_TOKENS.border);
      grid = new THREE.GridHelper(4 * maxR, 8, border, border);
      const mat = grid.material as THREE.Material;
      mat.transparent = true;
      mat.opacity = 0.18; // faint spatial reference (was 0.5 — dominated the view)
      group.add(grid);
      place(Math.max(maxR, 1000));
      return maxR;
    },
    frame(): EnvFrame {
      return envFrame;
    },
    update(dt: number, reducedMotion: boolean): void {
      // Prograde roll + ring dash drift (the 3D scene is the product; both
      // honoured for prefers-reduced-motion). elapsed accumulates only while
      // running. rotation.z = the orbital-plane normal — surface and dashes
      // crawl along-track (+x scene) at the formation.
      if (!reducedMotion) {
        earthSpin -= dt * EARTH_SPIN_RATE;
        earth.rotation.z = earthSpin;
        ring.rotation.z -= dt * ORBIT_DRIFT_RATE;
      }
    },
    dispose(): void {
      if (grid !== null) grid.dispose();
      earth.geometry.dispose();
      (earth.material as THREE.MeshLambertMaterial).map?.dispose();
      (earth.material as THREE.Material).dispose();
      atmo.geometry.dispose();
      (atmo.material as THREE.Material).dispose();
      ring.geometry.dispose();
      (ring.material as THREE.Material).dispose();
      starGeo.dispose();
      (stars.material as THREE.Material).dispose();
      dir.dispose();
      amb.dispose();
    },
  };
}
