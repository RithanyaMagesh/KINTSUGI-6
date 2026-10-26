// SwarmScene controller — FRONTEND_SPEC §7.2 / §14, plain Three.js (locked
// stack §5: no React Three Fiber). One imperative class driven imperatively by
// the React wrapper (SwarmScene.tsx) via store subscriptions — React never
// re-renders per frame (§19 performance rules). All colors come from
// tokens.css through sceneColors.ts (§13.1). Satellites live in
// sceneSatellites.ts, ghost slots in sceneSlots.ts, screen-space labels in
// sceneLabels.ts, Earth + starfield in sceneEarth.ts.
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { MissionState, Satellite } from "../../types/satellite";
import { fitDistance, fitFormation } from "../../utils/geometry";
import {
  createSatelliteRecord,
  disposeSatelliteRecord,
  lvlhToScene,
  pushTrail,
  syncSatellite,
  updateMarkerView,
  type SatRecord,
} from "./sceneSatellites";
import { SlotLayer } from "./sceneSlots";
import { LabelLayer, labelPriority, type LabelItem } from "./sceneLabels";
import { AutoFitController, earthFitRadius, FIT_FILL } from "./sceneCamera";
import { FormationLines } from "./sceneLines";
import { createEnvironment, type Environment } from "./sceneEarth";
import { SCENE_TOKENS, tokenColor } from "./sceneColors";

export type CameraPreset = "reset" | "top" | "formation" | "focus";

const FAILURE_STATES: ReadonlySet<string> = new Set([
  "FAILURE_DETECTED",
  "REPLANNING",
  "RECONFIGURING",
]);

export interface SceneUpdate {
  satellites: Satellite[];
  selectedId: string | null;
  missionState: MissionState | null;
}

export class SwarmSceneController {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(50, 1, 1, 1e7);
  private controls: OrbitControls;
  private raf = 0;
  private running = true;
  private ro: ResizeObserver;
  private container: HTMLElement;
  private onPick: (id: string | null) => void;

  private records = new Map<string, SatRecord>();
  private extent = 0;
  private slots: SlotLayer;
  private labels = new LabelLayer();
  private fit = new AutoFitController();
  private environment: Environment;
  // Healthy pairs (faint chrome) vs failed-touching pairs (thin red, gated to
  // the failure mission states — §7.3 without lines shooting across the view).
  private lines = new FormationLines();
  private bg = tokenColor(SCENE_TOKENS.bg).clone(); // trail fade target

  private toggles = { labels: true, trails: true, lines: true, slots: true };
  private reducedMotion: boolean;
  private clock = new THREE.Clock();
  private raycaster = new THREE.Raycaster();
  private pointerDownAt: { x: number; y: number } | null = null;
  private lastSats: Satellite[] = [];
  private selectedId: string | null = null;
  private missionState: MissionState | null = null;
  private viewW = 1;
  private viewH = 1;
  private scratch = new THREE.Vector3();

  constructor(container: HTMLElement, onPick: (id: string | null) => void) {
    this.container = container;
    this.onPick = onPick;
    this.reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    this.scene.background = tokenColor(SCENE_TOKENS.bg).clone();

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.domElement.style.display = "block";
    container.appendChild(this.renderer.domElement);
    container.appendChild(this.labels.root); // above the canvas, below overlay chrome

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;

    this.slots = new SlotLayer(this.labels);
    this.scene.add(this.slots.group);

    this.environment = createEnvironment();
    this.scene.add(this.environment.group);
    this.environment.trackExtent(0); // no grid/earth scale until real data arrives

    this.scene.add(this.lines.healthy, this.lines.failed);

    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(container);
    this.resize();
    this.frameEarth(2, 1.5, 2); // Earth-centred pre-data staging (§20 notice covers the canvas)

    this.renderer.domElement.addEventListener("pointerdown", this.handlePointerDown);
    this.renderer.domElement.addEventListener("pointerup", this.handlePointerUp);
    this.renderer.domElement.addEventListener("wheel", this.handleWheel, { passive: true });
    this.fit.attach(this.controls);
    document.addEventListener("visibilitychange", this.handleVisibility);
    this.animate();
  }

  // ---- public API (called by the React wrapper) ---------------------------

  update({ satellites, selectedId, missionState }: SceneUpdate): void {
    this.lastSats = satellites.slice();
    this.selectedId = selectedId;
    this.missionState = missionState;

    this.updateExtent(satellites);
    for (const sat of satellites) {
      let rec = this.records.get(sat.id);
      if (rec === undefined) {
        rec = createSatelliteRecord(sat, (id) => this.onPick(id), this.labels);
        this.scene.add(rec.group, rec.trail);
        this.records.set(sat.id, rec);
      }
      syncSatellite(rec, sat, { selectedId, showTrails: this.toggles.trails });
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
        if (rec !== undefined) pushTrail(rec, sat, now, this.bg);
      }
    }
    this.lines.update(satellites, this.failureActive());
    if (this.toggles.slots) {
      const nSeats = Math.max(satellites.length, 1);
      this.slots.update(satellites, fitFormation(satellites, nSeats), this.extent || 1000, selectedId);
    } else {
      this.slots.visible = false;
    }
  }

  setToggles(t: typeof this.toggles): void {
    this.toggles = { ...t };
    this.slots.visible = t.slots;
    this.lines.setVisibility(t.lines);
  }

  applyPreset(preset: CameraPreset, focusSat: Satellite | null): void {
    const e = this.extent || 1000;
    if (preset === "reset") {
      this.frameEarth(2, 1.5, 2); // default frame: Earth centred, ring around it
    } else if (preset === "top") {
      this.frameEarth(0.001, 1, 0); // plan view over Earth's centre (hair offset
      // keeps OrbitControls off the pole singularity)
    } else {
      const target = new THREE.Vector3(0, 0, 0);
      if (preset === "focus" && focusSat !== null) {
        target.set(...lvlhToScene(focusSat.r));
      }
      this.controls.target.copy(target);
      // Formation stays formation-tight; focus is the failed-sat follow-cam.
      if (preset === "formation") {
        this.camera.position.set(target.x + e * 1.6, e * 1.0, target.z + e * 1.2);
      } else {
        this.camera.position.set(target.x + e * 0.8, e * 0.7, target.z + e * 0.8);
      }
    }
    // Every preset re-enables the managed view. "Focus failed" keeps auto-fit
    // ON but tracks the failed satellite (follow-cam) — otherwise an
    // Earth-centred refit would undo the focus a second later.
    this.fit.onPreset(preset);
    this.controls.update();
  }

  /** Jump to an Earth-centred frame (2026-10-04 bug 3): target = ring centre
   * (= Earth's centre), distance = the managed fit for the whole ring plus
   * the formation riding it. `dir` is the view offset direction from the
   * centre — oblique for the default, ~straight up for the top view. */
  private frameEarth(dirX: number, dirY: number, dirZ: number): void {
    const f = this.environment.frame();
    const d = fitDistance(
      earthFitRadius(f, this.lastSats),
      (this.camera.fov * Math.PI) / 180,
      this.camera.aspect,
      FIT_FILL,
    );
    this.controls.target.set(...f.center);
    const len = Math.hypot(dirX, dirY, dirZ);
    this.camera.position.set(
      f.center[0] + (dirX / len) * d,
      f.center[1] + (dirY / len) * d,
      f.center[2] + (dirZ / len) * d,
    );
  }

  dispose(): void {
    this.running = false;
    cancelAnimationFrame(this.raf);
    this.ro.disconnect();
    this.fit.detach(this.controls);
    this.controls.dispose();
    this.renderer.domElement.removeEventListener("pointerdown", this.handlePointerDown);
    this.renderer.domElement.removeEventListener("pointerup", this.handlePointerUp);
    this.renderer.domElement.removeEventListener("wheel", this.handleWheel);
    document.removeEventListener("visibilitychange", this.handleVisibility);
    for (const rec of this.records.values()) disposeSatelliteRecord(rec, this.scene);
    this.records.clear();
    this.slots.dispose();
    this.scene.remove(this.slots.group);
    this.lines.dispose();
    this.scene.remove(this.lines.healthy, this.lines.failed);
    this.scene.remove(this.environment.group);
    this.environment.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
    this.labels.dispose();
  }

  // ---- internals -----------------------------------------------------------

  private failureActive(): boolean {
    return this.missionState !== null && FAILURE_STATES.has(this.missionState);
  }

  /** Track the measured swarm extent (grid + environment scale + marker
   * clamps); the environment re-fits only when the swarm leaves the band. */
  private updateExtent(sats: Satellite[]): void {
    let maxR = 0;
    for (const sat of sats) maxR = Math.max(maxR, Math.hypot(sat.r[0], sat.r[1], sat.r[2]));
    this.extent = this.environment.trackExtent(maxR);
  }

  private updateMarkers(elapsed: number): void {
    const extent = this.extent || 1000;
    for (const rec of this.records.values()) {
      updateMarkerView(rec, this.camera, this.viewH, extent, elapsed, this.reducedMotion, rec.status);
    }
    this.slots.updateView(this.camera, this.viewH, extent);
  }

  /** Screen-space label pass: project, then let the layer resolve collisions
   * (priority failed > selected > leader > others). */
  private updateLabels(): void {
    const items: LabelItem[] = [];
    const project = (pos: THREE.Vector3): { x: number; y: number } | null => {
      this.scratch.copy(pos).applyMatrix4(this.camera.matrixWorldInverse);
      if (this.scratch.z >= -0.5) return null; // behind / at the camera
      this.scratch.copy(pos).project(this.camera);
      const x = (this.scratch.x * 0.5 + 0.5) * this.viewW;
      const y = (-this.scratch.y * 0.5 + 0.5) * this.viewH;
      if (x < -60 || x > this.viewW + 60 || y < -60 || y > this.viewH + 60) return null;
      return { x, y };
    };
    for (const rec of this.records.values()) {
      const p = project(rec.group.position);
      if (p === null) continue;
      items.push({
        el: rec.labelEl,
        x: p.x,
        y: p.y,
        dotR: rec.screenR + 2,
        priority: labelPriority(rec.status, rec.role, this.selectedId, rec.id),
        tie: rec.id,
        show: this.toggles.labels,
      });
    }
    if (this.toggles.slots) {
      for (const slot of this.slots.labelItems()) {
        if (!slot.show) continue;
        const p = project(slot.pos);
        if (p === null) continue;
        items.push({
          el: slot.el,
          x: p.x,
          y: p.y,
          dotR: slot.screenR + 2,
          priority: 10, // slot captions always lose to satellite labels
          tie: slot.text,
          show: true,
        });
      }
    }
    this.labels.layout(items);
  }

  private resize(): void {
    const w = this.container.clientWidth;
    const h = this.container.clientHeight;
    if (w === 0 || h === 0) return;
    this.viewW = w;
    this.viewH = h;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
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

  /** Drag (not click) disables auto-fit; a plain click still raycasts the
   * satellite discs/rings; empty space deselects. Keyboard users select via
   * the satellite list / labels. */
  private handlePointerUp = (ev: PointerEvent): void => {
    const down = this.pointerDownAt;
    this.pointerDownAt = null;
    if (down === null) return;
    if (Math.hypot(ev.clientX - down.x, ev.clientY - down.y) > 5) {
      this.fit.onDrag(); // orbit drag — the user owns the framing now
      return;
    }
    const rect = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(
      ((ev.clientX - rect.left) / rect.width) * 2 - 1,
      -((ev.clientY - rect.top) / rect.height) * 2 + 1,
    );
    this.raycaster.setFromCamera(ndc, this.camera);
    const targets: THREE.Mesh[] = [];
    for (const rec of this.records.values()) targets.push(rec.disc, rec.ring);
    const hit = this.raycaster.intersectObjects(targets, false)[0];
    if (hit !== undefined) {
      for (const rec of this.records.values()) {
        if (rec.disc === hit.object || rec.ring === hit.object) {
          this.onPick(rec.id);
          return;
        }
      }
    }
    this.onPick(null);
  };

  private handleWheel = (): void => {
    this.fit.onWheel(); // zoom — the user owns the framing now
  };

  private animate = (): void => {
    if (!this.running) return;
    this.raf = requestAnimationFrame(this.animate);
    const dt = this.clock.getDelta();
    const elapsed = this.clock.elapsedTime;
    this.controls.update();
    this.camera.updateMatrixWorld(); // keep matrixWorldInverse fresh for projection
    this.fit.update(this.camera, this.controls, dt, this.lastSats, this.environment.frame());
    this.environment.update(dt, this.reducedMotion);
    this.updateMarkers(elapsed);
    this.updateLabels();
    this.renderer.render(this.scene, this.camera);
  };
}
