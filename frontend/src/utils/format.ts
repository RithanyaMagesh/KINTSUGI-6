// Shared formatting helpers. Every displayed number traces to the live stream
// or a committed log (repo invariant 1) — null renders as "unmeasured".

export const UNMEASURED = "unmeasured";

export function unmeasuredOr<T>(value: T | null | undefined, format: (v: T) => string): string {
  return value === null || value === undefined ? UNMEASURED : format(value);
}

/** Sim time in seconds, mono-friendly: "t + 123.4 s". */
export function formatSimTime(t: number | null): string {
  return unmeasuredOr(t, (v) => `t + ${v.toFixed(1)} s`);
}

export function formatSeconds(v: number): string {
  return `${v.toFixed(2)} s`;
}

export function formatMeters(v: number): string {
  return `${v.toFixed(1)} m`;
}

export function formatMsPerS(v: number): string {
  return `${v.toFixed(2)} m/s`;
}

export function formatMs(v: number): string {
  return `${v.toFixed(0)} ms`;
}

export function formatPercent(v: number): string {
  return `${(v * 100).toFixed(1)} %`;
}
