// Stylized environment — the user-requested Earth globe + faint starfield.
// Procedural only: SphereGeometry with a canvas-generated texture (dark
// blue-green landmass noise + faint graticule) and a backside fresnel-style
// atmosphere shell. No external textures, no new deps. Earth sits on the
// nadir axis so the formation visibly flies ABOVE it: LVLH x is radial
// (repo invariant 4), the scene maps LVLH x -> scene z (sceneSatellites
// lvlhToScene), so nadir (-x LVLH) is scene -z. Size/distance are visual
// choices scaled to the measured swarm extent — the formation stays the
// focus, Earth is a large background body. All colors via sceneColors.ts.
import * as THREE from "three";
import { SCENE_TOKENS, tokenColor } from "./sceneColors";

// Visual constants (multiples of the measured swarm extent).
const EARTH_RADIUS_FACTOR = 1.6;
const EARTH_DISTANCE_FACTOR = 5.0;
const STAR_RADIUS_FACTOR = 45;
const STAR_COUNT = 700;

/** Deterministic LCG — the starfield and texture noise must be identical on
 * every load (repo invariant 2 spirit: no unseeded RNG). Never Math.random. */
function lcg(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

/** Canvas texture: ocean base, soft landmass blobs (drawn at u, u±width for a
 * seamless equirect wrap), sparse speckles, faint graticule. One-time cost. */
function buildEarthTexture(): THREE.CanvasTexture {
  const w = 1024;
  const h = 512;
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (ctx === null) throw new Error("2D canvas context unavailable");
  const rnd = lcg(19700101);
  const ocean = tokenColor(SCENE_TOKENS.earthOcean).getStyle();
  const land = tokenColor(SCENE_TOKENS.earthLand).getStyle();
  const grat = tokenColor(SCENE_TOKENS.earthGraticule).getStyle();

  ctx.fillStyle = ocean;
  ctx.fillRect(0, 0, w, h);

  // Soft landmass noise — overlapping semi-transparent blobs.
  ctx.save();
  ctx.filter = "blur(7px)";
  for (let i = 0; i < 130; i++) {
    const u = rnd() * w;
    const v = h * (0.12 + 0.76 * rnd()); // keep off the poles
    const rx = 14 + rnd() * 70;
    const ry = rx * (0.5 + rnd() * 0.5);
    const rot = rnd() * Math.PI;
    ctx.globalAlpha = 0.1 + rnd() * 0.16;
    ctx.fillStyle = land;
    for (const du of [-w, 0, w]) {
      ctx.beginPath();
      ctx.ellipse(u + du, v, rx, ry, rot, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  for (let i = 0; i < 90; i++) {
    // Fine speckle so the surface is not flat blur. Radius hoisted out of the
    // wrap loop so all three copies are identical (seamless equirect seam).
    const u = rnd() * w;
    const v = h * (0.1 + 0.8 * rnd());
    const r = 1.5 + rnd() * 4.5;
    ctx.globalAlpha = 0.08 + rnd() * 0.12;
    ctx.fillStyle = land;
    for (const du of [-w, 0, w]) {
      ctx.beginPath();
      ctx.arc(u + du, v, r, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  ctx.restore();

  // Faint graticule: meridians every 15 deg, parallels every 15 deg, brighter
  // equator. 1 px, low alpha — texture detail, never a UI element.
  ctx.lineWidth = 1;
  ctx.strokeStyle = grat;
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
  tex.anisotropy = 4;
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
  return new THREE.Mesh(new THREE.SphereGeometry(1.15, 48, 32), mat);
}

export interface Environment {
  group: THREE.Group;
  /** Re-fit the faint reference grid + body scales when the measured swarm
   * extent leaves the current scale band; returns the tracked extent. */
  trackExtent(maxR: number): number;
  update(dt: number, reducedMotion: boolean): void;
  dispose(): void;
}

export function createEnvironment(): Environment {
  const group = new THREE.Group();

  // Lights affect only the lit Earth material; every marker is MeshBasicMaterial.
  const white = tokenColor(SCENE_TOKENS.ink).getHex();
  const dir = new THREE.DirectionalLight(white, 2.4);
  dir.position.set(3, 1.2, 2); // direction only — magnitude is irrelevant
  const amb = new THREE.AmbientLight(white, 0.32);
  group.add(dir, amb);

  const earth = new THREE.Mesh(
    new THREE.SphereGeometry(1, 48, 32),
    new THREE.MeshLambertMaterial({ map: buildEarthTexture() }),
  );
  const atmo = buildAtmosphere();
  const earthGroup = new THREE.Group();
  earthGroup.add(earth, atmo);
  group.add(earthGroup);

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
      const e = Math.max(maxR, 1000);
      earthGroup.scale.setScalar(e * EARTH_RADIUS_FACTOR);
      earthGroup.position.set(0, 0, -e * EARTH_DISTANCE_FACTOR);
      starGroup.scale.setScalar(e * STAR_RADIUS_FACTOR);
      return maxR;
    },
    update(dt: number, reducedMotion: boolean): void {
      // Very slow spin (the 3D scene is the product; still honoured for
      // prefers-reduced-motion). elapsed accumulates only while running.
      if (!reducedMotion) {
        earthSpin += dt * 0.02;
        earth.rotation.y = earthSpin;
      }
    },
    dispose(): void {
      if (grid !== null) grid.dispose();
      earth.geometry.dispose();
      (earth.material as THREE.MeshLambertMaterial).map?.dispose();
      (earth.material as THREE.Material).dispose();
      atmo.geometry.dispose();
      (atmo.material as THREE.Material).dispose();
      starGeo.dispose();
      (stars.material as THREE.Material).dispose();
      dir.dispose();
      amb.dispose();
    },
  };
}
