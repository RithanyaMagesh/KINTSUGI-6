// Camera auto-fit + gesture ownership — extracted from swarmScene.ts to keep
// files ~300 lines. 2026-10-04 bug 3 ("didn't even make Earth the middle"):
// the managed view is EARTH-CENTRED — the target is the orbit-ring centre
// (= Earth's centre, from sceneEarth frame()) and the fit subject is the
// WHOLE ring plus the formation riding it, so Earth sits centred in view as
// the orbited body, the ring circles it, and the satellites are dots on the
// ring. The formation (flying satellites) only enlarges that fit — coasting
// dead bodies never do. Any user drag/zoom hands framing back permanently;
// camera presets re-enable the managed view: "reset"/"top" share the
// Earth-centred frame, "formation" keeps the old formation-tight fit, and
// "focus" tracks the failed satellite (follow-cam) — a formation-centred
// refit would undo the focus at once.
import * as THREE from "three";
import type { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { Satellite } from "../../types/satellite";
import { boundingSphere, fitDistance } from "../../utils/geometry";
import { lvlhToScene } from "./sceneSatellites";
import type { EnvFrame } from "./sceneEarth";

export const FIT_FILL = 0.9; // the orbit ring meets the window edge: Earth fills the screen // managed fit: the full-screen live view fills the window
const FIT_RESPONSE = 1.8; // 1/s ease rate — gentle re-fit, never snappy
// Formation-tight/focus modes only: the fit target sits this x formation-radius
// BELOW the formation centre (scene +y = zenith) so the swarm rides above
// screen centre. Earth-centred mode has no lift — Earth IS the centre.
const FRAME_LIFT = 0; // the camera view offset already lifts the picture

/** Fit radius for the Earth-centred frame: the whole orbit ring plus the
 * flying formation riding it (measured satellite distance from the ring
 * centre). Coasting dead satellites never enlarge the frame. */
export function earthFitRadius(f: EnvFrame, sats: Satellite[]): number {
  const flying = sats.filter((s) => s.status !== "failed");
  const pts = flying.length > 0 ? flying : sats;
  let r = f.ringRadius;
  for (const s of pts) {
    const [x, y, z] = lvlhToScene(s.r);
    r = Math.max(r, Math.hypot(x - f.center[0], y - f.center[1], z - f.center[2]));
  }
  return r;
}

export class AutoFitController {
  private enabled = true;
  private center: "earth" | "formation" | "failed" = "earth";
  private interacting = false;
  private gestureDist = 0;
  private dir = new THREE.Vector3();
  private target = new THREE.Vector3();
  private cam: THREE.PerspectiveCamera | null = null;
  private controlsRef: OrbitControls | null = null;

  attach(controls: OrbitControls): void {
    controls.addEventListener("start", this.onStart);
    controls.addEventListener("end", this.onEnd);
    controls.addEventListener("change", this.onChange);
  }

  detach(controls: OrbitControls): void {
    controls.removeEventListener("start", this.onStart);
    controls.removeEventListener("end", this.onEnd);
    controls.removeEventListener("change", this.onChange);
  }

  /** A camera preset button was pressed — the managed view is back on.
   * reset/top re-arm the Earth-centred frame; formation stays formation-tight;
   * focus keeps the failed-satellite follow-cam. */
  onPreset(preset: string): void {
    this.enabled = true;
    this.center = preset === "focus" ? "failed" : preset === "formation" ? "formation" : "earth";
  }

  onDrag(): void {
    this.enabled = false; // orbit drag — the user owns the framing now
  }

  onWheel(): void {
    this.enabled = false; // zoom — the user owns the framing now
  }

  private onStart = (): void => {
    this.interacting = true;
    this.gestureDist =
      this.cam !== null && this.controlsRef !== null
        ? this.cam.position.distanceTo(this.controlsRef.target)
        : 0;
  };

  private onEnd = (): void => {
    this.interacting = false;
  };

  private onChange = (): void => {
    // Dolly/pinch during a gesture (no pointer travel): camera-distance drift
    // gives it away. Rotation-only drags are caught via onDrag().
    if (!this.interacting || this.cam === null || this.controlsRef === null) return;
    const d = this.cam.position.distanceTo(this.controlsRef.target);
    if (this.gestureDist <= 0) {
      this.gestureDist = d;
      return;
    }
    if (Math.abs(d - this.gestureDist) > this.gestureDist * 1e-4) this.enabled = false;
  };

  /** One ease step toward the fit. `sats` are the measured wire positions;
   * `env` is the staged Earth/ring placement. */
  update(
    camera: THREE.PerspectiveCamera,
    controls: OrbitControls,
    dt: number,
    sats: Satellite[],
    env: EnvFrame,
  ): void {
    this.cam = camera;
    this.controlsRef = controls;
    if (!this.enabled || this.interacting) return;
    // The FORMATION is the fallback focus: flying satellites only.
    const flying = sats.filter((s) => s.status !== "failed");
    const pts = (flying.length > 0 ? flying : sats).map((s) => s.r);
    const sphere = pts.length > 0 ? boundingSphere(pts) : null;
    let center: [number, number, number];
    let fitR: number;
    let lift = 0;
    if (this.center === "earth") {
      // Earth-centred: the ring centre IS the target; the fit subject
      // is the whole ring plus the formation riding it.
      center = env.center;
      fitR = earthFitRadius(env, sats);
    } else if (sphere !== null && sphere.radius > 0) {
      center =
        this.center === "failed"
          ? lvlhToScene(sats.find((s) => s.status === "failed")?.r ?? [sphere.cx, sphere.cy, sphere.cz])
          : ([sphere.cy, sphere.cx, sphere.cz] as [number, number, number]); // LVLH centroid -> scene
      fitR = sphere.radius;
      lift = sphere.radius * FRAME_LIFT;
    } else {
      center = env.center;
      fitR = env.ringRadius;
    }
    const dTarget = fitDistance(fitR, (camera.fov * Math.PI) / 180, camera.aspect, FIT_FILL);
    const k = 1 - Math.exp(-FIT_RESPONSE * 2.2 * dt);
    this.dir.copy(camera.position).sub(controls.target);
    const dist = this.dir.length();
    if (dist < 1e-6) return;
    this.dir.divideScalar(dist);
    this.target.set(center[0], center[1] - lift, center[2]);
    controls.target.lerp(this.target, k);
    camera.position.copy(controls.target).addScaledVector(this.dir, dist + (dTarget - dist) * k);
    controls.update();
  }
}
