// Camera auto-fit + gesture ownership — extracted from swarmScene.ts to keep
// files ~300 lines. Gently keeps the formation centred and filling ~50-65% of
// the viewport (2026-09-30 user verdict: the formation drifted into a corner
// or shrank to a speck). The FORMATION (flying satellites) is the fit subject,
// so coasting dead bodies never shrink the swarm. Any user drag/zoom hands
// framing back permanently; camera presets re-enable the managed view, with
// "focus" tracking the failed satellite (follow-cam) instead of the formation
// centre — otherwise a formation-centred refit would undo the focus at once.
// 2026-10-04: the fit target sits below the formation centre (scene +y =
// zenith) so the swarm rides above screen centre and the nadir Earth fills
// the lower third of the managed view.
import * as THREE from "three";
import type { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { Satellite } from "../../types/satellite";
import { boundingSphere, fitDistance } from "../../utils/geometry";
import { lvlhToScene } from "./sceneSatellites";

const FIT_FILL = 0.575; // auto-fit: formation fills 50-65% of the viewport (midpoint)
const FIT_RESPONSE = 1.8; // 1/s ease rate — gentle re-fit, never snappy
// The fit target sits this x formation-radius BELOW the formation centre
// (scene +y = zenith): looking at a point under the swarm lifts it above
// screen centre, and the nadir Earth fills the lower third (2026-10-04
// staging ask; verified by projection: centroid sy 0.43, limb sy 0.63).
const FRAME_LIFT = 0.3;

export class AutoFitController {
  private enabled = true;
  private center: "formation" | "failed" = "formation";
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

  /** A camera preset button was pressed — the managed view is back on. */
  onPreset(preset: string): void {
    this.enabled = true;
    this.center = preset === "focus" ? "failed" : "formation";
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

  /** One ease step toward the fit. `sats` are the measured wire positions. */
  update(
    camera: THREE.PerspectiveCamera,
    controls: OrbitControls,
    dt: number,
    sats: Satellite[],
  ): void {
    this.cam = camera;
    this.controlsRef = controls;
    if (!this.enabled || this.interacting || sats.length === 0) return;
    // The FORMATION is the focus: flying satellites only.
    const flying = sats.filter((s) => s.status !== "failed");
    const pts = (flying.length > 0 ? flying : sats).map((s) => s.r);
    const sphere = boundingSphere(pts);
    if (sphere === null || sphere.radius <= 0) return;
    const center =
      this.center === "failed"
        ? lvlhToScene(sats.find((s) => s.status === "failed")?.r ?? [sphere.cx, sphere.cy, sphere.cz])
        : ([sphere.cy, sphere.cx, sphere.cz] as [number, number, number]); // LVLH centroid -> scene
    const dTarget = fitDistance(
      sphere.radius,
      (camera.fov * Math.PI) / 180,
      camera.aspect,
      FIT_FILL,
    );
    const k = 1 - Math.exp(-FIT_RESPONSE * dt);
    this.dir.copy(camera.position).sub(controls.target);
    const dist = this.dir.length();
    if (dist < 1e-6) return;
    this.dir.divideScalar(dist);
    this.target.set(center[0], center[1] - sphere.radius * FRAME_LIFT, center[2]);
    controls.target.lerp(this.target, k);
    camera.position.copy(controls.target).addScaledVector(this.dir, dist + (dTarget - dist) * k);
    controls.update();
  }
}
