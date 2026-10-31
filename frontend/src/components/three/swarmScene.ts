// SwarmScene controller — FRONTEND_SPEC §7.2 / §14, plain Three.js.
// Supports two 3D view modes:
// - "global" (Earth orbit view): Earth centered at [0, 0, 0] with satellites
//   orbiting all the way around the planet along an inclined orbital ring.
// - "local" (Formation array view): Close-up 2:1 Clohessy-Wiltshire relative
//   formation grid around [0, 0, 0] with Earth hidden.
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { MissionState, Satellite } from "../../types/satellite";
import type { OrbitViewMode } from "../../stores/uiStore";
import { fitDistance, fitFormation } from "../../utils/geometry";
import {
  clearSatelliteTrail,
  createSatelliteRecord,
  disposeSatelliteRecord,
  lvlhToScene,
  pushTrail,
  setSceneCoordinateTransform,
  setSwarmCount,
  syncSatellite,
  updateMarkerView,
  type SatRecord,
} from "./sceneSatellites";
import { SlotLayer } from "./sceneSlots";
import { LabelLayer, labelPriority, type LabelItem } from "./sceneLabels";
import { AutoFitController, earthFitRadius, FIT_FILL } from "./sceneCamera";
import { FormationLines } from "./sceneLines";
import { createEnvironment, EARTH_RADIUS_FACTOR, type Environment } from "./sceneEarth";
import { SCENE_TOKENS, tokenColor } from "./sceneColors";
import { SUN_DIR } from "./sceneGlobe";

/** Visual orbit phase per simulated second (2x real LEO mean motion, kept
 * from the original scene), and the Earth's spin as a fraction of it: a
 * 500 km orbit (~95 min) laps the planet ~15.2x per sidereal day. */
const ORBIT_PHASE_PER_SIM_S = 0.0022;
const EARTH_SPIN_RATIO = 15.2;

/** Up to this many satellites every name is shown; above it, names appear
 * only for the satellites that matter (see labelWanted). */
const LABEL_ALL_MAX = 10;

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
  simTime?: number;
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
  private extent = 1000;
  private orbitMode: OrbitViewMode = "global";
  private orbitPhase = 0;
  private lastSimTime = 0;
  // One clock for the orbit animation: the sim-time phase from the stream,
  // extrapolated between frames at the measured rate and eased toward, so the
  // swarm glides instead of snapping back on every frame.
  private phaseTarget = 0;
  private phaseRate = 0; // rad per wall-clock second, measured from the stream
  private phaseStampMs = 0;
  private slots: SlotLayer;
  private labels = new LabelLayer();
  private fit = new AutoFitController();
  private environment: Environment;
  private lines = new FormationLines();
  private bg = tokenColor(SCENE_TOKENS.void).clone();

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
  private followId: string | null = null;
  private hoverId: string | null = null;
  private lastHoverAt = 0;
  private followFly = 0; // seconds left in the fly-in
  private lastFollowPos = new THREE.Vector3();

  constructor(container: HTMLElement, onPick: (id: string | null) => void) {
    this.container = container;
    this.onPick = onPick;
    this.reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // Space stays dark in both themes: the stage is the void, not a panel.
    this.scene.background = tokenColor(SCENE_TOKENS.void).clone();
    const sun = new THREE.DirectionalLight(tokenColor("--hero-light-key"), 2.4);
    sun.position.copy(SUN_DIR).multiplyScalar(10);
    this.scene.add(sun, new THREE.HemisphereLight(tokenColor("--hero-light-rim"), tokenColor("--space-void"), 0.22));

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.domElement.style.display = "block";
    container.appendChild(this.renderer.domElement);
    container.appendChild(this.labels.root);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    // Eyes-on-the-Earth feel: weighty drag with momentum, zoom toward the
    // cursor, and room to dive close to the surface or a spacecraft.
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.06;
    this.controls.rotateSpeed = 0.55;
    this.controls.zoomSpeed = 0.9;
    this.controls.zoomToCursor = true;

    this.slots = new SlotLayer(this.labels);
    this.scene.add(this.slots.group);

    this.environment = createEnvironment();
    this.scene.add(this.environment.group);
    this.environment.trackExtent(0);

    this.scene.add(this.lines.healthy, this.lines.failed);

    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(container);
    this.resize();
    this.frameEarth(2.2, 1.35, 2.2);

    this.renderer.domElement.addEventListener("pointerdown", this.handlePointerDown);
    this.renderer.domElement.addEventListener("pointerup", this.handlePointerUp);
    this.renderer.domElement.addEventListener("pointermove", this.handlePointerMove);
    this.renderer.domElement.addEventListener("wheel", this.handleWheel, { passive: true });
    this.fit.attach(this.controls);
    document.addEventListener("visibilitychange", this.handleVisibility);
    this.animate();
  }

  // ---- public API (called by the React wrapper) ---------------------------

  update({ satellites, selectedId, missionState, simTime }: SceneUpdate): void {
    this.lastSats = satellites.slice();
    setSwarmCount(satellites.length);
    this.selectedId = selectedId;
    this.missionState = missionState;
    if (simTime !== undefined && simTime !== this.lastSimTime) {
      this.lastSimTime = simTime;
      const now = performance.now();
      const target = simTime * ORBIT_PHASE_PER_SIM_S;
      const dtw = (now - this.phaseStampMs) / 1000;
      const step = target - this.phaseTarget;
      if (this.phaseStampMs > 0 && dtw > 0 && step > 0 && step < 0.5) {
        this.phaseRate = 0.7 * this.phaseRate + 0.3 * (step / dtw);
      } else if (this.phaseStampMs === 0 || step <= 0 || step >= 0.5) {
        // first frame, replay seek or a new run: jump straight there
        this.orbitPhase = target;
        this.phaseRate = 0;
        for (const rec of this.records.values()) clearSatelliteTrail(rec); // no chord across Earth
      }
      this.phaseTarget = target;
      this.phaseStampMs = now;
    }

    this.updateExtent(satellites);
    const nSeats = Math.max(satellites.length, 1);
    const fit = fitFormation(satellites, nSeats);
    setSceneCoordinateTransform({
      mode: this.orbitMode,
      extent: this.extent || 1000,
      amplitude: fit.ok && fit.amplitude > 0 ? fit.amplitude : (this.extent || 1000) * 0.55,
      orbitPhase: this.orbitPhase % (Math.PI * 2),
    });

    this.syncAllObjects(satellites, fit);
  }

  setOrbitViewMode(mode: OrbitViewMode): void {
    if (this.orbitMode === mode) return;
    this.orbitMode = mode;
    this.environment.setMode(mode);
    setSceneCoordinateTransform({ mode });
    for (const rec of this.records.values()) {
      clearSatelliteTrail(rec);
    }
    const nSeats = Math.max(this.lastSats.length, 1);
    const fit = fitFormation(this.lastSats, nSeats);
    this.orbitPhase = this.phaseTarget; // phase only advances in Earth view: no catch-up spin
    this.syncAllObjects(this.lastSats, fit);
    if (this.followId !== null) {
      this.followFly = this.reducedMotion ? 0.01 : 1.6; // fly back to the followed satellite
      const rec = this.records.get(this.followId);
      if (rec !== undefined) this.lastFollowPos.copy(rec.group.position);
      return;
    }
    // Smoothly animate camera distance and target via AutoFitController
    this.fit.onPreset(mode === "global" ? "reset" : "formation");
  }

  refreshTheme(): void {
    this.bg = tokenColor(SCENE_TOKENS.void).clone();
    this.scene.background = this.bg.clone();
    this.environment.refreshTheme();
    this.slots.refreshTheme();
    this.lines.refreshTheme();
    const nSeats = Math.max(this.lastSats.length, 1);
    const fit = fitFormation(this.lastSats, nSeats);
    this.syncAllObjects(this.lastSats, fit);
  }

  setToggles(t: typeof this.toggles): void {
    if (t.trails && !this.toggles.trails) {
      for (const rec of this.records.values()) clearSatelliteTrail(rec);
    }
    this.toggles = { ...t };
    this.slots.visible = t.slots;
    this.lines.setVisibility(t.lines);
  }

  applyPreset(preset: CameraPreset, focusSat: Satellite | null): void {
    const e = this.extent || 1000;
    if (preset !== "focus") this.followId = null;
    if (preset === "reset") {
      if (this.orbitMode === "local") {
        this.setOrbitViewMode("global");
        return;
      }
      this.frameEarth(2.2, 1.35, 2.2);
    } else if (preset === "top") {
      this.frameEarth(0.001, 1, 0);
    } else if (preset === "formation") {
      if (this.orbitMode === "global") {
        this.setOrbitViewMode("local");
        return;
      }
      const target = new THREE.Vector3(0, 0, 0);
      this.controls.target.copy(target);
      this.camera.position.set(e * 1.6, e * 1.0, e * 1.2);
    } else {
      const target = new THREE.Vector3(0, 0, 0);
      if (focusSat !== null) {
        target.set(...lvlhToScene(focusSat.r));
      }
      this.controls.target.copy(target);
      this.camera.position.set(target.x + e * 0.8, target.y + e * 0.7, target.z + e * 0.8);
    }
    this.fit.onPreset(preset === "formation" ? "formation" : preset === "focus" ? "focus" : "reset");
    this.controls.update();
  }

  /** Dolly toward (factor < 1) or away from (factor > 1) the orbit target —
   * the on-screen zoom buttons. Hands framing to the user like a wheel zoom. */
  zoom(factor: number): void {
    this.fit.onWheel();
    const offset = this.camera.position.clone().sub(this.controls.target);
    const d = Math.min(Math.max(offset.length() * factor, this.controls.minDistance || 1), 1e7 * 0.5);
    this.camera.position.copy(this.controls.target).add(offset.setLength(d));
    this.controls.update();
  }

  /** Fly the camera to a satellite and keep it in frame as it orbits; null
   * flies back out to the whole-Earth view. */
  focusSatellite(id: string | null): void {
    if (id !== null && id === this.followId) return;
    this.followId = id;
    if (id === null) {
      this.applyPreset(this.orbitMode === "global" ? "reset" : "formation", null);
      return;
    }
    const rec = this.records.get(id);
    if (rec === undefined) {
      this.followId = null;
      return;
    }
    this.fit.onWheel(); // the follow-cam owns framing now
    this.followFly = this.reducedMotion ? 0.01 : 1.6;
    this.lastFollowPos.copy(rec.group.position);
  }

  private updateFollow(dt: number): void {
    if (this.followId === null) return;
    const rec = this.records.get(this.followId);
    if (rec === undefined) {
      this.followId = null;
      this.onPick(null); // satellite gone (new run): drop the selection, fly back out
      return;
    }
    const pos = rec.group.position;
    // Carry the camera with the satellite. In the Earth view also turn it
    // with the orbit (rotation about Earth's centre from the last position
    // to this one), so it stays a chase cam and the planet rolls underneath;
    // a pure translation let the satellite drift round to the far side.
    const camOff = this.camera.position.clone().sub(this.lastFollowPos);
    const tgtOff = this.controls.target.clone().sub(this.lastFollowPos);
    if (this.orbitMode === "global" && this.lastFollowPos.lengthSq() > 0 && pos.lengthSq() > 0) {
      const q = new THREE.Quaternion().setFromUnitVectors(
        this.lastFollowPos.clone().normalize(),
        pos.clone().normalize(),
      );
      camOff.applyQuaternion(q);
      tgtOff.applyQuaternion(q);
    }
    this.camera.position.copy(pos).add(camOff);
    this.controls.target.copy(pos).add(tgtOff);
    this.lastFollowPos.copy(pos);
    if (this.followFly > 0) {
      this.followFly -= dt;
      const k = 1 - Math.exp(-4 * dt);
      this.controls.target.lerp(pos, k);
      // Park the camera just outside and above the satellite, looking back
      // down at it with the planet filling the background.
      const close = (this.extent || 1000) * 0.45;
      const out = this.orbitMode === "global" ? pos.clone().normalize() : new THREE.Vector3(1, 0.6, 1).normalize();
      const want = out.multiplyScalar(close).add(new THREE.Vector3(0, close * 0.45, 0)).add(pos);
      this.camera.position.lerp(want, k);
    }
  }

  getToggles(): { labels: boolean; trails: boolean; lines: boolean; slots: boolean } {
    return { ...this.toggles };
  }

  private syncAllObjects(satellites: Satellite[], fit: ReturnType<typeof fitFormation>): void {
    for (const sat of satellites) {
      let rec = this.records.get(sat.id);
      if (rec === undefined) {
        rec = createSatelliteRecord(sat, (id) => this.onPick(id), this.labels);
        this.scene.add(rec.group, rec.trail);
        this.records.set(sat.id, rec);
      }
      syncSatellite(rec, sat, {
        selectedId: this.selectedId,
        showTrails: this.toggles.trails,
        extent: this.extent || 1000,
      });
    }
    for (const [id, rec] of this.records) {
      if (!satellites.some((s) => s.id === id)) {
        disposeSatelliteRecord(rec, this.scene);
        this.records.delete(id);
      }
    }
    const trailOpacity = satellites.length > LABEL_ALL_MAX ? 0.28 : 0.65;
    for (const rec of this.records.values()) {
      (rec.trail.material as THREE.LineBasicMaterial).opacity = trailOpacity;
    }
    if (this.toggles.trails) {
      const now = performance.now();
      for (const sat of satellites) {
        const rec = this.records.get(sat.id);
        if (rec !== undefined) pushTrail(rec, sat, now, this.bg);
      }
    }
    this.lines.update(satellites, this.failureActive());
    if (this.toggles.slots) {
      this.slots.update(satellites, fit, this.extent || 1000, this.selectedId);
    } else {
      this.slots.visible = false;
    }
  }

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
    this.renderer.domElement.removeEventListener("pointermove", this.handlePointerMove);
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

  private updateExtent(sats: Satellite[]): void {
    let maxR = 0;
    for (const sat of sats) maxR = Math.max(maxR, Math.hypot(sat.r[0], sat.r[1], sat.r[2]));
    this.extent = this.environment.trackExtent(maxR);
    this.controls.minDistance = this.extent * 0.05;
    this.controls.maxDistance = this.extent * 30;
  }

  private updateMarkers(elapsed: number): void {
    const extent = this.extent || 1000;
    for (const rec of this.records.values()) {
      updateMarkerView(rec, this.camera, this.viewH, extent, elapsed, this.reducedMotion, rec.status);
    }
    this.slots.updateView(this.camera, this.viewH, extent);
  }

  private updateLabels(): void {
    const items: LabelItem[] = [];
    const project = (pos: THREE.Vector3): { x: number; y: number } | null => {
      this.scratch.copy(pos).applyMatrix4(this.camera.matrixWorldInverse);
      if (this.scratch.z >= -0.5) return null;
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
        show: this.toggles.labels && this.labelWanted(rec),
      });
    }
    if (this.toggles.slots && this.records.size <= LABEL_ALL_MAX) {
      for (const slot of this.slots.labelItems()) {
        if (!slot.show) continue;
        const p = project(slot.pos);
        if (p === null) continue;
        items.push({
          el: slot.el,
          x: p.x,
          y: p.y,
          dotR: slot.screenR + 2,
          priority: 10,
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
    // Lift the picture slightly so the swarm clears the bottom readout bar.
    this.camera.setViewOffset(w, h, 0, Math.round(h * 0.06), w, h);
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
  }

  private handleVisibility = (): void => {
    const visible = document.visibilityState === "visible";
    if (visible && !this.running) {
      this.running = true;
      this.animate();
    } else if (!visible) {
      this.running = false;
      cancelAnimationFrame(this.raf); // else the pending frame revives a 2nd loop on return
    }
  };

  private handlePointerDown = (ev: PointerEvent): void => {
    this.pointerDownAt = { x: ev.clientX, y: ev.clientY };
  };

  private handlePointerUp = (ev: PointerEvent): void => {
    const down = this.pointerDownAt;
    this.pointerDownAt = null;
    if (down === null) return;
    if (Math.hypot(ev.clientX - down.x, ev.clientY - down.y) > 5) {
      this.fit.onDrag();
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

  /** Hover reveals a satellite's name in big swarms (throttled raycast). */
  private handlePointerMove = (ev: PointerEvent): void => {
    if (ev.timeStamp - this.lastHoverAt < 60) return;
    this.lastHoverAt = ev.timeStamp;
    const rect = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(
      ((ev.clientX - rect.left) / rect.width) * 2 - 1,
      -((ev.clientY - rect.top) / rect.height) * 2 + 1,
    );
    this.raycaster.setFromCamera(ndc, this.camera);
    const targets: THREE.Mesh[] = [];
    for (const rec of this.records.values()) targets.push(rec.disc);
    const hit = this.raycaster.intersectObjects(targets, false)[0];
    let id: string | null = null;
    if (hit !== undefined) {
      for (const rec of this.records.values()) if (rec.disc === hit.object) id = rec.id;
    }
    this.hoverId = id;
    this.renderer.domElement.style.cursor = id !== null ? "pointer" : "";
  };

  /** Which names to draw: everything in a small swarm; in a big one only the
   * satellites that matter right now (roles, trouble, selection, hover). */
  private labelWanted(rec: SatRecord): boolean {
    if (this.records.size <= LABEL_ALL_MAX) return true;
    if (rec.id === this.selectedId || rec.id === this.hoverId) return true;
    if (rec.role === "leader" || rec.role === "downlink") return true;
    return rec.status !== "healthy";
  }

  private handleWheel = (): void => {
    this.fit.onWheel();
  };

  private animate = (): void => {
    if (!this.running) return;
    this.raf = requestAnimationFrame(this.animate);
    const dt = this.clock.getDelta();
    const elapsed = this.clock.elapsedTime;
    if (this.orbitMode === "global" && this.lastSats.length > 0) {
      const sinceMs = performance.now() - this.phaseStampMs;
      // Stream stalled (paused / ended): stop extrapolating after 1.5 s.
      // Stalled (paused / ended / recomputing): hold where we are, never ease back.
      const stalled = sinceMs > 1500;
      const lead = Math.min(sinceMs / 1000, 1.5);
      const predicted = stalled ? this.orbitPhase : this.phaseTarget + this.phaseRate * lead;
      this.orbitPhase = this.reducedMotion
        ? this.phaseTarget
        : this.orbitPhase + (predicted - this.orbitPhase) * Math.min(1, dt * 10);
      setSceneCoordinateTransform({ orbitPhase: this.orbitPhase % (Math.PI * 2) });
      // B) Earth turns on the same clock, at the real ratio (~1:15).
      this.environment.setEarthSpin(this.orbitPhase / EARTH_SPIN_RATIO);
      const nSeats = Math.max(this.lastSats.length, 1);
      const fit = fitFormation(this.lastSats, nSeats);
      this.syncAllObjects(this.lastSats, fit);
    } else if (this.lastSats.length === 0) {
      this.environment.setEarthSpin(null);
    }
    this.updateFollow(dt);
    this.controls.update();
    // Never fly through the planet: keep the camera just above the air.
    if (this.orbitMode === "global") {
      const floor = (this.extent || 1000) * EARTH_RADIUS_FACTOR * 1.04;
      const r = this.camera.position.length();
      if (r < floor) this.camera.position.multiplyScalar(floor / Math.max(r, 1e-6));
    }
    this.camera.updateMatrixWorld();
    this.fit.update(this.camera, this.controls, dt, this.lastSats, this.environment.frame());
    this.environment.update(dt, this.reducedMotion);
    this.updateMarkers(elapsed);
    this.updateLabels();
    this.fitClipPlanes();
    this.renderer.render(this.scene, this.camera);
  };

  /** Near/far follow the zoom so depth precision holds at every scale: a
   * coasting dead satellite can grow the scene ~10x, and a fixed near = 1
   * then let the atmosphere shell z-fight through the planet. */
  private fitClipPlanes(): void {
    const d = this.camera.position.distanceTo(this.controls.target);
    const e = this.extent || 1000;
    const near = Math.max(1, d * 0.01);
    const far = this.camera.position.length() + e * 60;
    if (Math.abs(near - this.camera.near) > near * 0.05 || Math.abs(far - this.camera.far) > far * 0.05) {
      this.camera.near = near;
      this.camera.far = far;
      this.camera.updateProjectionMatrix();
    }
  }
}
