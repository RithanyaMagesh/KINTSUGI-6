// WebSocket URL builder for /ws/state. In dev the Vite proxy forwards /ws to
// the FastAPI service (vite.config.ts); in production the app is served BY
// that service, so same-origin always works — no configurable host, no CDN.

export function stateSocketUrl(): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/ws/state`;
}
