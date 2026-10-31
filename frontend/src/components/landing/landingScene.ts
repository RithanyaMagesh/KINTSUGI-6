// KINTSUGI-6 landing — animated 3D stage (plain Three.js + its bundled
// post-processing addons; no new dependencies).
//
// Hero: a 3D "KINTSUGI-6" wordmark (with a gold kintsugi seam) sits at the
// centre; six procedural 3U CubeSats orbit it on a tilted ring, passing in
// FRONT of and BEHIND the letters (the wordmark writes depth), while floating
// telemetry cards drift on an outer ring. Scroll progress p in [0, 1] then
// plays the story:
//   p ~ 0.33  break:  SAT-3 cracks red, throws debris, tumbles off its orbit
//   p ~ 0.66  repair: the five survivors re-space and gold seams draw between
//             them one by one (bloom) — the swarm "repaired with gold"
//   p ~ 1.00  proof:  the repaired formation turns slowly beside the stats
// The animation is an ILLUSTRATION of the recovery story; it carries no
// numbers. Colours come only from tokens.css (§13.1) via cssVar/col.
import * as THREE from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import { LineSegments2 } from "three/examples/jsm/lines/LineSegments2.js";
import { LineSegmentsGeometry } from "three/examples/jsm/lines/LineSegmentsGeometry.js";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";
import {
  buildCubeSat,
  makeGeoms,
  makeMaterials,
  panelTexture,
  type SatMaterials,
} from "../three/cubeSatModel";

export interface LandingSceneHandle {
  setProgress(p: number): void;
  setPointer(x: number, y: number): void;
  dispose(): void;
}

export interface TelemetryCard {
  label: string;
  value: string;
  tone: "ink" | "gold" | "green";
}

const N_SATS = 6;
const BROKEN = 2; // SAT-3
const TAU = Math.PI * 2;
const SUN_DEPTH = 40; // view-space depth of the sun sprite

function cssVar(name: string): string {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return raw !== "" ? raw : "gray";
}

function col(name: string): THREE.Color {
  return new THREE.Color(cssVar(name));
}

function smooth(e0: number, e1: number, x: number): number {
  const t = Math.min(1, Math.max(0, (x - e0) / (e1 - e0)));
  return t * t * (3 - 2 * t);
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

function angleDiff(a: number, b: number): number {
  let d = (b - a) % TAU;
  if (d > Math.PI) d -= TAU;
  if (d < -Math.PI) d += TAU;
  return d;
}

/** Deterministic LCG (repo invariant 2: no unseeded RNG). */
function makeRand(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

// ---------------------------------------------------------------- textures


/** The wordmark as a texture, with a jagged gold kintsugi seam through it. */
function drawWordmark(canvas: HTMLCanvasElement): void {
  const g = canvas.getContext("2d") as CanvasRenderingContext2D;
  const w = canvas.width;
  const h = canvas.height;
  g.clearRect(0, 0, w, h);
  g.fillStyle = cssVar("--hero-ink");
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.font = `600 ${Math.round(h * 0.62)}px "IBM Plex Sans", "Segoe UI", sans-serif`;
  (g as CanvasRenderingContext2D & { letterSpacing?: string }).letterSpacing = `${Math.round(-h * 0.012)}px`;
  g.fillText("KINTSUGI-6", w / 2, h * 0.53);
  // Kintsugi seam: drawn only where the letters are (source-atop).
  g.globalCompositeOperation = "source-atop";
  g.strokeStyle = cssVar("--hero-gold-bright");
  g.lineWidth = h * 0.05;
  g.lineJoin = "round";
  const rand = makeRand(42);
  g.beginPath();
  let y = h * 0.38;
  g.moveTo(0, y);
  for (let x = 0; x <= w; x += w / 22) {
    y = Math.min(h * 0.7, Math.max(h * 0.34, y + (rand() - 0.5) * h * 0.2));
    g.lineTo(x, y);
  }
  g.stroke();
  g.globalCompositeOperation = "source-over";
}

function cardTexture(card: TelemetryCard): THREE.CanvasTexture {
  const w = 640;
  const h = 176;
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const g = canvas.getContext("2d") as CanvasRenderingContext2D;
  const r = 18;
  g.beginPath();
  g.roundRect(4, 4, w - 8, h - 8, r);
  g.fillStyle = cssVar("--panel");
  g.fill();
  g.lineWidth = 3;
  g.strokeStyle = card.tone === "gold" ? cssVar("--hero-gold") : cssVar("--hero-line-strong");
  g.stroke();
  g.textBaseline = "alphabetic";
  g.fillStyle = cssVar("--hero-ink-faint");
  g.font = `500 30px "IBM Plex Mono", monospace`;
  g.fillText(card.label.toUpperCase(), 32, 64);
  g.fillStyle =
    card.tone === "gold"
      ? cssVar("--hero-gold-bright")
      : card.tone === "green"
        ? cssVar("--status-nominal")
        : cssVar("--hero-ink");
  g.font = `500 48px "IBM Plex Mono", monospace`;
  g.fillText(card.value, 32, 132);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  return tex;
}


// ---------------------------------------------------------------- scene

/** The visible sun: a warm glow, a white-hot core and a fan of soft radial
 * rays (seeded, so identical on every load) that turn very slowly. Additive
 * and above the bloom threshold, so the composer adds a gentle glare. */
function buildSun(): {
  group: THREE.Group;
  update(t: number): void;
  setFade(f: number): void;
  dispose(): void;
} {
  const hex = (name: string, alpha: number) =>
    `#${new THREE.Color(cssVar(name)).getHexString()}${Math.round(alpha * 255).toString(16).padStart(2, "0")}`;
  const radial = (size: number, stops: Array<[number, string, number]>) => {
    const c = document.createElement("canvas");
    c.width = c.height = size;
    const g = c.getContext("2d") as CanvasRenderingContext2D;
    const grad = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    for (const [at, name, alpha] of stops) grad.addColorStop(at, hex(name, alpha));
    g.fillStyle = grad;
    g.fillRect(0, 0, size, size);
    return c;
  };
  const tex = (c: HTMLCanvasElement) => {
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  };

  const coreTex = tex(radial(256, [
    [0, "--hero-sun", 1], [0.22, "--hero-sun", 1], [0.4, "--hero-sun", 0.55], [0.7, "--hero-sun-glow", 0.12], [1, "--hero-sun-glow", 0],
  ]));
  const glowTex = tex(radial(512, [
    [0, "--hero-sun-glow", 0.55], [0.15, "--hero-sun-glow", 0.25], [0.4, "--hero-sun-glow", 0.07], [0.7, "--hero-sun-glow", 0.015], [1, "--hero-sun-glow", 0],
  ]));

  // Rays: thin tapered wedges from the centre, each a gradient that fades out
  // along its length; varied lengths and widths, then softened with a blur.
  const N = 1024;
  const rc = document.createElement("canvas");
  rc.width = rc.height = N;
  const g = rc.getContext("2d") as CanvasRenderingContext2D;
  g.filter = "blur(5px)";
  g.globalCompositeOperation = "lighter";
  const rnd = makeRand(7);
  const RAYS = 44;
  for (let i = 0; i < RAYS; i += 1) {
    const ang = (i / RAYS) * TAU + (rnd() - 0.5) * 0.12;
    const len = (0.22 + rnd() * 0.28) * N;
    const half = 0.006 + rnd() * 0.018;
    const grad = g.createRadialGradient(N / 2, N / 2, 0, N / 2, N / 2, len);
    grad.addColorStop(0, hex("--hero-sun", 0.55));
    grad.addColorStop(0.3, hex("--hero-sun-glow", 0.22));
    grad.addColorStop(1, hex("--hero-sun-glow", 0));
    g.fillStyle = grad;
    g.beginPath();
    g.moveTo(N / 2, N / 2);
    g.lineTo(N / 2 + Math.cos(ang - half) * len, N / 2 + Math.sin(ang - half) * len);
    g.lineTo(N / 2 + Math.cos(ang + half) * len, N / 2 + Math.sin(ang + half) * len);
    g.closePath();
    g.fill();
  }
  const raysTex = tex(rc);

  const sprite = (map: THREE.Texture, scale: number, boost: number) => {
    const m = new THREE.SpriteMaterial({
      map,
      color: new THREE.Color(1, 1, 1).multiplyScalar(boost),
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      depthTest: false,
      fog: false,
      toneMapped: false,
    });
    const sp = new THREE.Sprite(m);
    sp.scale.setScalar(scale);
    sp.renderOrder = -1;
    return sp;
  };
  const group = new THREE.Group();
  const glow = sprite(glowTex, 13, 0.6);
  const rays = sprite(raysTex, 11, 0.42);
  const raysB = sprite(raysTex, 8, 0.25);
  const core = sprite(coreTex, 2.2, 1.7);
  group.add(glow, rays, raysB, core);
  return {
    group,
    setFade(f: number) {
      for (const sp of [glow, rays, raysB, core]) (sp.material as THREE.SpriteMaterial).opacity = f;
      group.visible = f > 0.003;
    },
    update(t: number) {
      (rays.material as THREE.SpriteMaterial).rotation = t * 0.015;
      (raysB.material as THREE.SpriteMaterial).rotation = -t * 0.01 + 0.3;
    },
    dispose() {
      for (const tx of [coreTex, glowTex, raysTex]) tx.dispose();
      for (const sp of [glow, rays, raysB, core]) (sp.material as THREE.Material).dispose();
    },
  };
}

export function createLandingScene(
  canvas: HTMLCanvasElement,
  host: HTMLElement,
  cards: TelemetryCard[],
): LandingSceneHandle {
  const reduceMotion =
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;

  const scene = new THREE.Scene();
  scene.background = col("--hero-bg");
  scene.fog = new THREE.Fog(col("--hero-bg"), 18, 60);
  const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 300);
  camera.position.set(0, 1.4, 14);

  // The sun is pinned to the upper-right of the SCREEN (a child of the
  // camera, placed on resize), and it lights the swarm as a point light that
  // fades with distance: satellites that drift into that corner flare up,
  // the rest of the ring stays in dim shade. No directional light and no
  // environment reflections, so nothing glints on the far side.
  scene.add(camera);
  // Soft sky fill (hemisphere light: diffuse only, no specular) keeps every
  // satellite readable without adding glints away from the sun.
  scene.add(new THREE.HemisphereLight(col("--hero-ink-muted"), col("--hero-bg"), 1.3));
  scene.add(new THREE.AmbientLight(col("--hero-light-rim"), 0.2));
  const sunLight = new THREE.PointLight(col("--hero-sun"), 60, 15, 2);
  camera.add(sunLight);
  const sun = buildSun();
  camera.add(sun.group);
  // Story lighting for the sections below the hero: as the sun fades out on
  // scroll, a soft sky light fades in. Hemisphere light is diffuse only (no
  // specular), so from the second section on nothing reflects or glints;
  // the satellites just read clearly. Reflections belong to the sun alone.
  const storyLight = new THREE.HemisphereLight(col("--hero-light-key"), col("--hero-light-rim"), 0);
  storyLight.position.set(-2, 6, 4);
  scene.add(storyLight);


  const goldLight = new THREE.PointLight(col("--hero-gold"), 0, 14, 1.6);
  scene.add(goldLight);
  const redLight = new THREE.PointLight(col("--hero-red"), 0, 6, 2);
  scene.add(redLight);

  // Stars + drifting dust.
  const rand = makeRand(1337);
  const starPos = new Float32Array(1400 * 3);
  for (let i = 0; i < 1400; i += 1) {
    const u = rand() * 2 - 1;
    const th = rand() * TAU;
    const rad = 45 + rand() * 60;
    const s = Math.sqrt(1 - u * u);
    starPos[i * 3] = rad * s * Math.cos(th);
    starPos[i * 3 + 1] = rad * u;
    starPos[i * 3 + 2] = rad * s * Math.sin(th) - 25;
  }
  const starGeo = new THREE.BufferGeometry();
  starGeo.setAttribute("position", new THREE.BufferAttribute(starPos, 3));
  const starMat = new THREE.PointsMaterial({ color: col("--hero-star"), size: 0.14, transparent: true, opacity: 0.75, fog: false });
  const stars = new THREE.Points(starGeo, starMat);
  scene.add(stars);

  const dustPos = new Float32Array(260 * 3);
  for (let i = 0; i < 260; i += 1) {
    dustPos[i * 3] = (rand() - 0.5) * 22;
    dustPos[i * 3 + 1] = (rand() - 0.5) * 12;
    dustPos[i * 3 + 2] = (rand() - 0.5) * 14;
  }
  const dustGeo = new THREE.BufferGeometry();
  dustGeo.setAttribute("position", new THREE.BufferAttribute(dustPos, 3));
  const dustMat = new THREE.PointsMaterial({ color: col("--hero-ink-faint"), size: 0.035, transparent: true, opacity: 0.5 });
  const dust = new THREE.Points(dustGeo, dustMat);
  scene.add(dust);

  // Wordmark (writes depth through alphaTest so satellites pass behind it).
  const wordCanvas = document.createElement("canvas");
  wordCanvas.width = 2048;
  wordCanvas.height = 420;
  drawWordmark(wordCanvas);
  const wordTex = new THREE.CanvasTexture(wordCanvas);
  wordTex.colorSpace = THREE.SRGBColorSpace;
  wordTex.anisotropy = 8;
  const wordMat = new THREE.MeshBasicMaterial({ map: wordTex, transparent: true, alphaTest: 0.5, toneMapped: false, fog: false });
  wordMat.color.setScalar(0.8); // white letters stay under the bloom threshold; the gold seam glows
  const wordGeo = new THREE.PlaneGeometry(1, 420 / 2048);
  const word = new THREE.Mesh(wordGeo, wordMat);
  word.position.set(0, 0.35, 0);
  scene.add(word);
  if (document.fonts && typeof document.fonts.load === "function") {
    Promise.all([
      document.fonts.load('600 200px "IBM Plex Sans"'),
      document.fonts.load('500 40px "IBM Plex Mono"'),
    ])
      .then(() => {
        drawWordmark(wordCanvas);
        wordTex.needsUpdate = true;
        rebuildCards();
      })
      .catch(() => undefined);
  }

  // Satellites.
  const geoms = makeGeoms();
  const panelMap = panelTexture();
  const ringGeo = new THREE.RingGeometry(0.92, 1.0, 64);
  const sats: Array<{ group: THREE.Group; mats: SatMaterials; halo: THREE.Mesh }> = [];
  for (let j = 0; j < N_SATS; j += 1) {
    const mats = makeMaterials(panelMap);
    // No environment to mirror out here, so very metallic frames render
    // black: tone them down to read as brushed aluminium.
    mats.frame.metalness = 0.45;
    mats.frame.roughness = 0.4;
    mats.cap.metalness = 0.3;
    // Tape antennas: dull gold, so they don't flare into bright lines.
    mats.gold.metalness = 0.2;
    mats.gold.roughness = 0.75;
    mats.gold.color.multiplyScalar(0.55);
    const group = buildCubeSat(geoms, mats);
    scene.add(group);
    const halo = new THREE.Mesh(
      ringGeo,
      new THREE.MeshBasicMaterial({ color: col("--hero-gold-bright"), transparent: true, opacity: 0, depthWrite: false, toneMapped: false }),
    );
    scene.add(halo);
    sats.push({ group, mats, halo });
  }

  // Orbit ring line.
  const ringPts: THREE.Vector3[] = [];
  for (let k = 0; k <= 160; k += 1) {
    const th = (k / 160) * TAU;
    ringPts.push(new THREE.Vector3(Math.cos(th), 0, Math.sin(th)));
  }
  const orbitGeo = new THREE.BufferGeometry().setFromPoints(ringPts);
  const orbitMat = new THREE.LineDashedMaterial({ color: col("--hero-line-strong"), dashSize: 0.03, gapSize: 0.025, transparent: true, opacity: 0.8 });
  const orbit = new THREE.Line(orbitGeo, orbitMat);
  orbit.computeLineDistances();
  scene.add(orbit);

  // Gold seams between survivors (screen-space thick lines + bloom).
  const seamGeo = new LineSegmentsGeometry();
  const seamPos = new Float32Array((N_SATS - 1) * 6);
  seamGeo.setPositions(seamPos);
  const seamMat = new LineMaterial({
    color: col("--hero-gold-bright").multiplyScalar(2.4).getHex(),
    linewidth: 3,
    transparent: true,
    opacity: 0,
    toneMapped: false,
  });
  seamMat.color.copy(col("--hero-gold-bright")).multiplyScalar(2.4);
  const seams = new LineSegments2(seamGeo, seamMat);
  seams.frustumCulled = false;
  scene.add(seams);

  // Debris burst from the broken satellite.
  const DEBRIS = 90;
  const debrisVel: THREE.Vector3[] = [];
  for (let i = 0; i < DEBRIS; i += 1) {
    const u = rand() * 2 - 1;
    const th = rand() * TAU;
    const s = Math.sqrt(1 - u * u);
    debrisVel.push(new THREE.Vector3(s * Math.cos(th), u, s * Math.sin(th)).multiplyScalar(0.6 + rand() * 1.6));
  }
  const debrisPos = new Float32Array(DEBRIS * 3);
  const debrisGeo = new THREE.BufferGeometry();
  debrisGeo.setAttribute("position", new THREE.BufferAttribute(debrisPos, 3));
  const debrisMat = new THREE.PointsMaterial({ color: col("--hero-red").multiplyScalar(1.6), size: 0.13, transparent: true, opacity: 0, toneMapped: false, depthWrite: false });
  const debris = new THREE.Points(debrisGeo, debrisMat);
  debris.frustumCulled = false;
  scene.add(debris);

  // Telemetry cards on an outer ring.
  const cardGeo = new THREE.PlaneGeometry(1, 176 / 640);
  const cardMeshes: Array<THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial>> = [];
  function rebuildCards(): void {
    for (const m of cardMeshes) {
      m.material.map?.dispose();
      m.material.dispose();
      scene.remove(m);
    }
    cardMeshes.length = 0;
    for (const c of cards) {
      const mat = new THREE.MeshBasicMaterial({ map: cardTexture(c), transparent: true, opacity: 0, depthWrite: false, toneMapped: false });
      mat.color.setScalar(0.78); // under the 0.82 bloom threshold: crisp text, no glow
      const mesh = new THREE.Mesh(cardGeo, mat);
      scene.add(mesh);
      cardMeshes.push(mesh);
    }
  }
  rebuildCards();

  // Post-processing: bloom makes the gold seams and debris glow.
  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.7, 0.5, 0.82);
  composer.addPass(bloom);
  composer.addPass(new OutputPass());

  const C = {
    white: new THREE.Color(1, 1, 1),
    black: new THREE.Color(0, 0, 0),
    red: col("--hero-red"),
    gold: col("--hero-gold"),
  };

  let target = 0;
  let progress = 0;
  const pointer = { x: 0, y: 0, sx: 0, sy: 0 };
  let aspect = 1;

  const resize = () => {
    const r = host.getBoundingClientRect();
    const w = Math.max(1, Math.floor(r.width));
    const h = Math.max(1, Math.floor(r.height));
    renderer.setSize(w, h, false);
    composer.setSize(w, h);
    bloom.setSize(w, h);
    seamMat.resolution.set(w, h);
    camera.aspect = w / h;
    aspect = camera.aspect;
    camera.updateProjectionMatrix();
    // Pin the sun to the upper-right of the view at depth SUN_DEPTH; the
    // light sits on the same sight line but inside the ring's corner, so the
    // satellites passing there are the ones it lights.
    const halfH = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    const dir = new THREE.Vector3(0.74 * halfH * camera.aspect, 0.66 * halfH, -1);
    sun.group.position.copy(dir).multiplyScalar(SUN_DEPTH);
    sunLight.position.copy(dir).multiplyScalar(13);
  };
  resize();
  const ro = new ResizeObserver(resize);
  ro.observe(host);

  const tilt = new THREE.Euler(0.36, 0, 0.16);
  const tiltM = new THREE.Matrix4();
  const center = new THREE.Vector3();
  const tmp = new THREE.Vector3();
  const tmp2 = new THREE.Vector3();
  const finalPos: THREE.Vector3[] = Array.from({ length: N_SATS - 1 }, () => new THREE.Vector3());
  const start = performance.now();
  let raf = 0;
  let running = true;

  function ringPoint(theta: number, radius: number, out: THREE.Vector3): THREE.Vector3 {
    return out.set(radius * Math.cos(theta), 0, radius * Math.sin(theta)).applyMatrix4(tiltM).add(center);
  }

  function frame(now: number): void {
    if (!running) return;
    raf = requestAnimationFrame(frame);
    const t = (now - start) / 1000;
    progress += (target - progress) * 0.07;
    pointer.sx += (pointer.x - pointer.sx) * 0.05;
    pointer.sy += (pointer.y - pointer.sy) * 0.05;
    const p = progress;

    const a = smooth(0.06, 0.26, p); // hero -> story layout
    const f = smooth(0.2, 0.34, p); // break
    const r = smooth(0.44, 0.58, p); // re-space survivors
    const seamT = smooth(0.54, 0.7, p); // gold seams draw in
    const outro = smooth(0.86, 1.0, p);

    const wide = aspect > 1.1;
    const visH = 2 * camera.position.z * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    const visW = visH * aspect;

    // Layout: hero centred around the wordmark; story shifts the swarm right.
    const radius = lerp(wide ? 5.7 : Math.min(5.7, visW * 0.48), wide ? 3.2 : 2.6, a) * lerp(1, 0.92, outro);
    center.set(wide ? lerp(0, lerp(4.1, 4.3, outro), a) : 0, wide ? lerp(0.1, 0, a) : lerp(0.1, 1.8, a), 0);
    tilt.set(lerp(0.36, 0.62, a), 0, lerp(0.16, 0.1, a));
    tiltM.makeRotationFromEuler(tilt);

    orbit.position.copy(center);
    orbit.rotation.copy(tilt);
    orbit.scale.setScalar(radius);
    orbitMat.opacity = 0.8 * (1 - 0.5 * seamT);

    // Wordmark: big in the hero, gone in the story sections.
    const wordW = Math.min(9.6, visW * 0.84);
    word.scale.set(wordW, wordW, 1);
    wordMat.opacity = 1 - a;
    word.visible = a < 0.995;
    word.position.y = 0.35 + a * 1.5;

    const omega = reduceMotion ? 0 : 0.11;
    const satScale = lerp(wide ? 0.42 : 0.3, wide ? 0.3 : 0.22, a);
    let s = 0;
    for (let j = 0; j < N_SATS; j += 1) {
      const { group, mats, halo } = sats[j];
      const base = (TAU * j) / N_SATS;
      if (j === BROKEN) {
        // Coasts outward and falls off the ring, tumbling.
        const theta = base + omega * t - 0.5 * f;
        ringPoint(theta, radius * (1 + 0.45 * f), tmp);
        tmp.y -= 1.2 * f;
        tmp.z += 1.0 * f;
        group.position.copy(tmp);
        const gone = smooth(0.44, 0.54, p);
        group.scale.setScalar(Math.max(0.0001, satScale * (1 - 0.35 * f) * (1 - gone)));
        const spin = reduceMotion ? 0.6 : t * 0.3 + j;
        group.rotation.set(0.25 + f * (reduceMotion ? 1.2 : t * 1.7), spin, f * (reduceMotion ? 0.8 : t * 1.1));
        mats.panel.color.copy(C.white).lerp(C.red, f * 0.9);
        mats.frame.emissive.copy(C.black).lerp(C.red, f * 1.2);
        mats.panel.emissive.copy(C.black).lerp(C.red, f * 0.5);
        group.visible = gone < 0.999;
        // Debris + red flash at the break point.
        const burst = smooth(0.18, 0.5, p);
        const life = Math.sin(Math.PI * Math.min(1, burst));
        debrisMat.opacity = 0.95 * life;
        redLight.position.copy(tmp);
        redLight.intensity = 6 * life;
        for (let i = 0; i < DEBRIS; i += 1) {
          tmp2.copy(debrisVel[i]).multiplyScalar(burst * 2.2).add(tmp);
          debrisPos[i * 3] = tmp2.x;
          debrisPos[i * 3 + 1] = tmp2.y;
          debrisPos[i * 3 + 2] = tmp2.z;
        }
        (debrisGeo.attributes.position as THREE.BufferAttribute).needsUpdate = true;
        const redHalo = halo.material as THREE.MeshBasicMaterial;
        redHalo.color.copy(C.red).multiplyScalar(1.8);
        halo.visible = life > 0.01 && group.visible;
        halo.position.copy(tmp);
        halo.quaternion.copy(camera.quaternion);
        halo.scale.setScalar(satScale * (2.2 + 2.5 * burst));
        redHalo.opacity = 0.9 * life;
        continue;
      }
      const targetTheta = (TAU * s) / (N_SATS - 1) + 0.35;
      const theta = base + r * angleDiff(base, targetTheta) + omega * t;
      ringPoint(theta, radius, tmp);
      group.position.copy(tmp);
      group.scale.setScalar(satScale);
      const spin = reduceMotion ? 0.6 + j : t * 0.3 + j;
      group.rotation.set(0.25, spin, 0.12);
      mats.frame.emissive.copy(C.black).lerp(C.gold, 0.18 * seamT);
      finalPos[s].copy(tmp);
      // Gold halo once the seams are in (the "repaired" mark).
      const haloMat = halo.material as THREE.MeshBasicMaterial;
      halo.visible = seamT > 0.01;
      halo.position.copy(tmp);
      halo.quaternion.copy(camera.quaternion);
      const pulse = reduceMotion ? 1 : 0.85 + 0.15 * Math.sin(t * 2.2 + j);
      halo.scale.setScalar(satScale * 2.4 * pulse);
      haloMat.opacity = 0.7 * smooth(0.8, 1, seamT + 0.2 * (s / (N_SATS - 1)));
      s += 1;
    }

    // Gold seams: drawn in one after another around the pentagon.
    const segs = N_SATS - 1;
    for (let k = 0; k < segs; k += 1) {
      const from = finalPos[k];
      const to = finalPos[(k + 1) % segs];
      const d = Math.min(1, Math.max(0, seamT * segs - k));
      tmp2.copy(from).lerp(to, d);
      seamPos.set([from.x, from.y, from.z, tmp2.x, tmp2.y, tmp2.z], k * 6);
    }
    seamGeo.setPositions(seamPos);
    seamMat.opacity = seamT > 0.001 ? 1 : 0;
    goldLight.position.copy(center);
    goldLight.intensity = 9 * seamT;

    // Telemetry cards orbit outside the swarm in the hero, then fade.
    const cardR = radius * 1.32;
    for (let i = 0; i < cardMeshes.length; i += 1) {
      const m = cardMeshes[i];
      const theta = (TAU * i) / cardMeshes.length + 0.6 + omega * 0.55 * t;
      ringPoint(theta, cardR, tmp);
      tmp.y += 1.5 + 0.35 * Math.sin(i * 1.7);
      m.position.copy(tmp);
      m.quaternion.copy(camera.quaternion);
      const cw = wide ? 1.9 : 1.5;
      m.scale.set(cw, cw, 1);
      const depth = THREE.MathUtils.clamp((tmp.z + cardR) / (2 * cardR), 0, 1);
      const cardFade = 1 - smooth(0.03, 0.14, p);
      m.material.opacity = (0.35 + 0.65 * depth) * cardFade;
      m.visible = cardFade > 0.005;
    }

    if (!reduceMotion) {
      stars.rotation.y = t * 0.004;
      dust.rotation.y = t * 0.012;
      dust.position.y = Math.sin(t * 0.2) * 0.2;
    }
    const sway = reduceMotion ? 0 : Math.sin(t * 0.15) * 0.5;
    camera.position.set(
      pointer.sx * 0.9 + sway,
      1.4 - pointer.sy * 0.6 + a * 0.6,
      lerp(14, 12.6, a) + 0.6 * f * (1 - r),
    );
    camera.lookAt(center.x * 0.45, center.y * 0.5, 0);
    if (!reduceMotion) sun.update(t);
    // The sun belongs to the hero: it fades out as you scroll to the next
    // section (and back in on the way up), its light with it.
    const sunFade = (1 - smooth(0.02, 0.16, p)) * smooth(0.2, 1.8, t); // eases in on load
    sun.setFade(sunFade);
    sunLight.intensity = 60 * sunFade;
    storyLight.intensity = 2.6 * (1 - sunFade);
    composer.render();
  }
  raf = requestAnimationFrame(frame);

  const onVisibility = () => {
    if (document.hidden) {
      running = false;
      cancelAnimationFrame(raf);
    } else if (!running) {
      running = true;
      raf = requestAnimationFrame(frame);
    }
  };
  document.addEventListener("visibilitychange", onVisibility);

  return {
    setProgress(p: number) {
      target = Math.min(1, Math.max(0, p));
    },
    setPointer(x: number, y: number) {
      pointer.x = Math.max(-1, Math.min(1, x));
      pointer.y = Math.max(-1, Math.min(1, y));
    },
    dispose() {
      running = false;
      cancelAnimationFrame(raf);
      sun.dispose();
      ro.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      for (const sat of sats) {
        for (const m of Object.values(sat.mats)) m.dispose();
        (sat.halo.material as THREE.Material).dispose();
      }
      for (const geo of Object.values(geoms)) geo.dispose();
      for (const m of cardMeshes) {
        m.material.map?.dispose();
        m.material.dispose();
      }
      cardGeo.dispose();
      ringGeo.dispose();
      panelMap.dispose();
      wordTex.dispose();
      wordGeo.dispose();
      wordMat.dispose();
      starGeo.dispose();
      starMat.dispose();
      dustGeo.dispose();
      dustMat.dispose();
      orbitGeo.dispose();
      orbitMat.dispose();
      seamGeo.dispose();
      seamMat.dispose();
      debrisGeo.dispose();
      debrisMat.dispose();
      composer.dispose();
      renderer.dispose();
    },
  };
}
