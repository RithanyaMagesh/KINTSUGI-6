// SwarmScene controller — FRONTEND_SPEC §7.2 / §14, plain Three.js (locked
// stack §5: no React Three Fiber). One imperative class driven imperatively by
// the React wrapper (SwarmScene.tsx) via store subscriptions — React never
// re-renders per frame (§19 performance rules). All colors come from
// tokens.css through sceneColors.ts (§13.1). Satellite records live in
// sceneSatellites.ts, ghost slots in sceneSlots.ts.
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import type { Satellite } from "../../types/satellite";
import { fitFormation } from "../../utils/geometry";
import {
  createSatelliteRecord,
  disposeSatelliteRecord,
  lvlhToScene,
  pushTrail,
  resizeSatelliteRecord,
  syncSatellite,
  type SatRecord,
} from "./sceneSatellites";
import { SlotLayer } from "./sceneSlots";
import { SCENE_TOKENS, statusToken, tokenColor } from "./sceneColors";

export type CameraPreset = "reset" | "top" | "formation" | "focus";

const MAX_SATS = 8; // scenarios top out at N=8 (cascading_n8)
const PAIR_CAPACITY = ((MAX_SATS * (MAX_SATS - 1)) / 2) * 2 * 3; // vertices * floats

export interface SceneUpdate {
  satellites: Satellite[];
  selectedId: string | null;
}

export class SwarmSceneController {
  private renderer: THREE.WebGLRenderer;
  private labelRenderer: CSS2DRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(50, 1, 1, 1e7);
  private controls: OrbitControls;
  private raf = 0;
  private running = true;
  private ro: ResizeObserver;
  private container: HTMLElement;
  private onPick: (id: string | null) => void;

  private records = new Map<string, SatRecord>();
  private grid: THREE.GridHelper | null = null;
  private extent = 0;
  private slots = new SlotLayer();
  private lineSegments: THREE.LineSegments;
  private linePositions: Float32Array;
  private lineColors: Float32Array;

  private toggles = { labels: true, trails: true, lines: true, slots: true };
  private reducedMotion: boolean;
  private clock = new THREE.Clock();
  private raycaster = new THREE.Raycaster();
  private pointerDownAt: { x: number; y: number } | null = null;

  constructor(container: HTMLElement, onPick: (id: string | null) => void) {
    this.container = container;
    this.onPick = onPick;
    this.reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    this.scene.background = tokenColor(SCENE_TOKENS.bg).clone();
    this.camera.position.set(100, 80, 100);

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.domElement.style.display = "block";
    container.appendChild(this.renderer.domElement);

    this.labelRenderer = new CSS2DRenderer();
    this.labelRenderer.domElement.style.position = "absolute";
    this.labelRenderer.domElement.style.inset = "0";
    this.labelRenderer.domElement.style.pointerEvents = "none";
    container.appendChild(this.labelRenderer.domElement);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;

    this.scene.add(this.slots.group);

    this.linePositions = new Float32Array(PAIR_CAPACITY);
    this.lineColors = new Float32Array(PAIR_CAPACITY);
    const lineGeo = new THREE.BufferGeometry();
    lineGeo.setAttribute("position", new THREE.BufferAttribute(this.linePositions, 3));
    lineGeo.setAttribute("color", new THREE.BufferAttribute(this.lineColors, 3));
    this.lineSegments = new THREE.LineSegments(
      lineGeo,
      new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.7 }),
    );
    this.scene.add(this.lineSegments);

    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(container);
    this.resize();

    this.renderer.domElement.addEventListener("pointerdown", this.handlePointerDown);
    this.renderer.domElement.addEventListener("pointerup", this.handlePointerUp);
    document.addEventListener("visibilitychange", this.handleVisibility);
    this.animate();
  }

  // ---- public API (called by the React wrapper) ---------------------------

  update({ satellites, selectedId }: SceneUpdate): void {
    const nSeats = Math.max(satellites.length, 1);
    const fit = fitFormation(satellites, nSeats);

    this.updateExtent(satellites);
    const elapsed = this.clock.getElapsedTime();
    for (const sat of satellites) {
      let rec = this.records.get(sat.id);
      if (rec === undefined) {
        rec = createSatelliteRecord(sat, this.extent, (id) => this.onPick(id));
        this.scene.add(rec.group, rec.trail, rec.label);
        this.records.set(sat.id, rec);
      }
      syncSatellite(rec, sat, {
        selectedId,
        reducedMotion: this.reducedMotion,
        elapsed,
        showLabels: this.toggles.labels,
        showTrails: this.toggles.trails,
      });
    }
    for (const [id, rec] of this.records) {
      if (!satellites.some((s) => s.id === id)) {
        disposeSatelliteRecord(rec, this.scene);
        this.records.delete(id);
      }
    }
    if (this.toggles.trails) {
      const now = performance.now(); // cadence gate only (§19)
      for (const sat of satellites) {
        const rec = this.records.get(sat.id);
        if (rec !== undefined) pushTrail(rec, sat, now);
      }
    }
    this.updateFormationLines(satellites);
    if (this.toggles.slots) this.slots.update(satellites, fit, this.extent || 1000);
    else this.slots.visible = false;
  }

  setToggles(t: typeof this.toggles): void {
    this.toggles = { ...t };
    this.slots.visible = t.slots;
    this.lineSegments.visible = t.lines;
  }

  applyPreset(preset: CameraPreset, focusSat: Satellite | null): void {
    const e = this.extent || 1000;
    const target = new THREE.Vector3(0, 0, 0);
    if (preset === "focus" && focusSat !== null) {
      target.set(...lvlhToScene(focusSat.r));
    }
    this.controls.target.copy(target);
    if (preset === "top") {
      this.camera.position.set(target.x + e * 0.001, e * 2.5, target.z);
    } else if (preset === "formation") {
      this.camera.position.set(target.x + e * 1.6, e * 0.5, target.z + e * 1.2);
    } else if (preset === "focus") {
      this.camera.position.set(target.x + e * 0.8, e * 0.5, target.z + e * 0.8);
    } else {
      this.camera.position.set(e * 2, e * 1.5, e * 2);
      this.controls.target.set(0, 0, 0);
    }
    this.controls.update();
  }

  dispose(): void {
    this.running = false;
    cancelAnimationFrame(this.raf);
    this.ro.disconnect();
    this.controls.dispose();
    this.renderer.domElement.removeEventListener("pointerdown", this.handlePointerDown);
    this.renderer.domElement.removeEventListener("pointerup", this.handlePointerUp);
    document.removeEventListener("visibilitychange", this.handleVisibility);
    for (const rec of this.records.values()) disposeSatelliteRecord(rec, this.scene);
    this.records.clear();
    this.slots.dispose();
    this.scene.remove(this.slots.group);
    this.lineSegments.geometry.dispose();
    (this.lineSegments.material as THREE.Material).dispose();
    if (this.grid !== null) {
      this.scene.remove(this.grid);
      this.grid.dispose();
    }
    this.renderer.dispose();
    this.renderer.domElement.remove();
    this.labelRenderer.domElement.remove();
  }

  // ---- internals -----------------------------------------------------------

  /** Auto-fit the reference grid + body sizes to the measured swarm extent,
   * re-fitting only when the swarm leaves the current scale band. */
  private updateExtent(sats: Satellite[]): void {
    let maxR = 0;
    for (const sat of sats) maxR = Math.max(maxR, Math.hypot(sat.r[0], sat.r[1], sat.r[2]));
    if (maxR <= 0) return;
    if (this.grid !== null && maxR <= this.extent * 1.5 && maxR >= this.extent * 0.4) return;
    this.extent = maxR;
    if (this.grid !== null) {
      this.scene.remove(this.grid);
      this.grid.dispose();
    }
    const border = tokenColor(SCENE_TOKENS.border);
    this.grid = new THREE.GridHelper(4 * maxR, 8, border, border);
    const mat = this.grid.material as THREE.Material;
    mat.transparent = true;
    mat.opacity = 0.5;
    this.scene.add(this.grid);
    const radius = Math.max(20, maxR * 0.02);
    for (const rec of this.records.values()) resizeSatelliteRecord(rec, radius);
  }

  /** Formation lines: every satellite pair. Lines touching a failed satellite
   * turn red (§7.3); healthy pairs use the chrome border token. */
  private updateFormationLines(sats: Satellite[]): void {
    let v = 0;
    const border = tokenColor(SCENE_TOKENS.borderStrong);
    const failed = tokenColor(statusToken("failed"));
    for (let a = 0; a < sats.length; a++) {
      for (let b = a + 1; b < sats.length; b++) {
        if (v + 6 > this.linePositions.length) return;
        const c = sats[a].status === "failed" || sats[b].status === "failed" ? failed : border;
        const comps = [c.r, c.g, c.b];
        this.linePositions.set(lvlhToScene(sats[a].r), v);
        this.linePositions.set(lvlhToScene(sats[b].r), v + 3);
        for (let k = 0; k < 3; k++) {
          this.lineColors[v + k] = comps[k];
          this.lineColors[v + 3 + k] = comps[k];
        }
        v += 6;
      }
    }
    (this.lineSegments.geometry.getAttribute("position") as THREE.BufferAttribute).needsUpdate = true;
    (this.lineSegments.geometry.getAttribute("color") as THREE.BufferAttribute).needsUpdate = true;
    this.lineSegments.geometry.setDrawRange(0, v / 3);
  }

  private resize(): void {
    const w = this.container.clientWidth;
    const h = this.container.clientHeight;
    if (w === 0 || h === 0) return;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
    this.labelRenderer.setSize(w, h);
  }

  private handleVisibility = (): void => {
    // §19: pause the render loop when the tab is hidden (the 30 s ping in
    // useWebSocket keeps running — it lives outside the scene).
    const visible = document.visibilityState === "visible";
    if (visible && !this.running) {
      this.running = true;
      this.animate();
    } else if (!visible) {
      this.running = false;
    }
  };

  private handlePointerDown = (ev: PointerEvent): void => {
    this.pointerDownAt = { x: ev.clientX, y: ev.clientY };
  };

  /** Click (not orbit drag) raycasts the satellite bodies; empty space
   * deselects. Keyboard users select via the satellite list / labels. */
  private handlePointerUp = (ev: PointerEvent): void => {
    const down = this.pointerDownAt;
    this.pointerDownAt = null;
    if (down === null) return;
    if (Math.hypot(ev.clientX - down.x, ev.clientY - down.y) > 5) return; // orbit drag
    const rect = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(
      ((ev.clientX - rect.left) / rect.width) * 2 - 1,
      -((ev.clientY - rect.top) / rect.height) * 2 + 1,
    );
    this.raycaster.setFromCamera(ndc, this.camera);
    const hit = this.raycaster.intersectObjects(
      [...this.records.values()].map((r) => r.mesh),
      false,
    )[0];
    if (hit === undefined) {
      this.onPick(null);
      return;
    }
    for (const rec of this.records.values()) {
      if (rec.mesh === hit.object) {
        this.onPick(rec.id);
        return;
      }
    }
  };

  private animate = (): void => {
    if (!this.running) return;
    this.raf = requestAnimationFrame(this.animate);
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    this.labelRenderer.render(this.scene, this.camera);
  };
}
