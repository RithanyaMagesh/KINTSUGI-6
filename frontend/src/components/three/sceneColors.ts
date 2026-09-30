// Token bridge for the 3D scene — §13.1: raw hex lives ONLY in tokens.css.
// Three.js materials cannot consume var() strings, so the scene reads the CSS
// custom properties off :root at runtime; every material colour therefore
// derives from the same token source as the chrome. The numeric grey fallback
// is NOT a palette colour — it only covers a token failing to resolve, which
// never happens with the committed tokens.css.
import * as THREE from "three";

const cache = new Map<string, THREE.Color>();

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
    case "failed":
      return "--status-failed";
    case "reconfiguring":
      return "--status-caution";
    case "recovered":
      return "--status-info";
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
} as const;
