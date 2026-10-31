// Procedural 3U CubeSat model — shared by the landing stage and the live 3D
// view so both show the same spacecraft. Colours come only from tokens.css
// (§13.1) via computed CSS custom properties.
import * as THREE from "three";

function cssVar(name: string): string {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return raw !== "" ? raw : "gray";
}

function col(name: string): THREE.Color {
  return new THREE.Color(cssVar(name));
}

export function panelTexture(): THREE.CanvasTexture {
  const w = 128;
  const h = 384;
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const g = canvas.getContext("2d") as CanvasRenderingContext2D;
  g.fillStyle = cssVar("--cubesat-panel-gap");
  g.fillRect(0, 0, w, h);
  const pad = 5;
  const cw = (w - pad * 3) / 2;
  const ch = (h - pad * 7) / 6;
  for (let r = 0; r < 6; r += 1) {
    for (let c = 0; c < 2; c += 1) {
      const x = pad + c * (cw + pad);
      const y = pad + r * (ch + pad);
      g.fillStyle = cssVar("--cubesat-panel");
      g.fillRect(x, y, cw, ch);
      g.strokeStyle = cssVar("--cubesat-panel-line");
      g.lineWidth = 1;
      for (let k = 1; k < 4; k += 1) {
        g.beginPath();
        g.moveTo(x, y + (ch * k) / 4);
        g.lineTo(x + cw, y + (ch * k) / 4);
        g.stroke();
      }
    }
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  return tex;
}

// ---------------------------------------------------------------- CubeSat

export interface SatMaterials {
  frame: THREE.MeshStandardMaterial;
  cap: THREE.MeshStandardMaterial;
  panel: THREE.MeshStandardMaterial;
  gold: THREE.MeshStandardMaterial;
}

export interface Geoms {
  rail: THREE.BoxGeometry;
  ringX: THREE.BoxGeometry;
  ringZ: THREE.BoxGeometry;
  cap: THREE.BoxGeometry;
  face: THREE.PlaneGeometry;
  antenna: THREE.BoxGeometry;
  lens: THREE.CylinderGeometry;
}

export function makeGeoms(): Geoms {
  return {
    rail: new THREE.BoxGeometry(0.08, 3.04, 0.08),
    ringX: new THREE.BoxGeometry(1.06, 0.05, 0.05),
    ringZ: new THREE.BoxGeometry(0.05, 0.05, 1.06),
    cap: new THREE.BoxGeometry(0.9, 0.04, 0.9),
    face: new THREE.PlaneGeometry(0.86, 2.9),
    antenna: new THREE.BoxGeometry(0.018, 0.018, 3.4),
    lens: new THREE.CylinderGeometry(0.16, 0.16, 0.1, 24),
  };
}

export function makeMaterials(panelMap: THREE.Texture): SatMaterials {
  return {
    frame: new THREE.MeshStandardMaterial({ color: col("--cubesat-frame"), metalness: 0.85, roughness: 0.32 }),
    cap: new THREE.MeshStandardMaterial({ color: col("--cubesat-cap"), metalness: 0.6, roughness: 0.5 }),
    panel: new THREE.MeshStandardMaterial({ map: panelMap, metalness: 0.2, roughness: 0.55, side: THREE.DoubleSide }),
    gold: new THREE.MeshStandardMaterial({ color: col("--cubesat-gold"), metalness: 0.9, roughness: 0.3 }),
  };
}

/** A 3U CubeSat, 1 x 3 x 1 units, centred, long axis = +y, deployed wings. */
export function buildCubeSat(g: Geoms, m: SatMaterials): THREE.Group {
  const sat = new THREE.Group();
  const add = (geo: THREE.BufferGeometry, mat: THREE.Material, x: number, y: number, z: number) => {
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(x, y, z);
    sat.add(mesh);
    return mesh;
  };
  for (const sx of [-0.5, 0.5]) {
    for (const sz of [-0.5, 0.5]) add(g.rail, m.frame, sx, 0, sz);
  }
  for (const y of [-1.5, -0.5, 0.5, 1.5]) {
    add(g.ringX, m.frame, 0, y, 0.5);
    add(g.ringX, m.frame, 0, y, -0.5);
    add(g.ringZ, m.frame, 0.5, y, 0);
    add(g.ringZ, m.frame, -0.5, y, 0);
  }
  add(g.cap, m.cap, 0, 1.5, 0);
  add(g.cap, m.cap, 0, -1.5, 0);
  add(g.lens, m.cap, 0, -1.56, 0);
  const faces: Array<[number, number, number]> = [
    [0, 0, 0.505],
    [Math.PI, 0, -0.505],
    [Math.PI / 2, 0.505, 0],
    [-Math.PI / 2, -0.505, 0],
  ];
  for (const [ry, x, z] of faces) add(g.face, m.panel, x, 0, z).rotation.y = ry;
  for (const s of [-1, 1]) add(g.face, m.panel, s * 0.98, 0, 0.5);
  for (const s of [-1, 1]) {
    const a = new THREE.Mesh(g.antenna, m.gold);
    a.position.set(s * 0.9, 1.5, -0.9);
    a.rotation.set(0, s * 0.78, 0);
    a.rotateX(-0.12);
    sat.add(a);
  }
  return sat;
}
