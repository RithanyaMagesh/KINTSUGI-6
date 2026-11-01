// Token bridge for the 3D scene — §13.1: raw hex lives ONLY in tokens.css.
// Three.js materials cannot consume var() strings, so the scene reads the CSS
// custom properties off :root at runtime; every material colour therefore
// derives from the same token source as the chrome.
import * as THREE from "three";

const cache = new Map<string, THREE.Color>();

export function clearColorCache(): void {
  cache.clear();
}

export function tokenColor(varName: string): THREE.Color {
  let color = cache.get(varName);
  if (color === undefined) {
    const raw = getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
    color = raw !== "" ? new THREE.Color(raw) : new THREE.Color(0.5, 0.5, 0.5);
    cache.set(varName, color);
  }
  return color;
}

/** §7.2 satellite status -> token name (mirrors utils/colors.ts, which serves
 * the DOM side; the scene needs token NAMES, not var() strings). */
export function statusToken(status: string): string {
  switch (status) {
    case "healthy":
      return "--status-nominal";
    case "degraded":
      return "--status-caution";
    case "failed":
      return "--status-failed";
    case "reconfiguring":
      return "--status-caution";
    case "recovered":
      return "--status-repaired";
    default:
      return "--ink-faint";
  }
}

export const SCENE_TOKENS = {
  bg: "--bg",
  border: "--border",
  borderStrong: "--border-strong",
  ink: "--ink",
  inkMuted: "--ink-muted",
  inkFaint: "--ink-faint",
  leader: "--status-leader",
  repaired: "--status-repaired",
  void: "--space-void",
  focus: "--focus-ring",
  earthOcean: "--scene-earth-ocean",
  earthLand: "--scene-earth-land",
  earthGraticule: "--scene-earth-graticule",
  atmo: "--scene-atmo",
  orbit: "--scene-orbit",
  cwEllipse: "--scene-cw-ellipse",
  cone: "--scene-cone",
  star: "--scene-star",
} as const;
