// POST /simulation/start for the live sandbox. Same error semantics as
// api/scenarios.ts — that file and api/backend.ts sit outside this task's
// file ownership, so the one call this page needs that they do not already
// export (start with speed + policy) lives here instead: network failure ->
// actionable Error; non-2xx -> Error with the backend detail verbatim and
// .status attached so the caller can run the policy-422 fallback.

const BACKEND_UNREACHABLE =
  "Backend unreachable — start it with: uv run uvicorn cubesat.api:app --port 8000";

export interface StartError extends Error {
  status?: number;
}

export interface StartBody {
  /** Saved scenario file name (uploadScenario's result.filename). */
  scenario: string;
  seed: number;
  speed: number;
  /** Recovery policy id — sent only while the backend accepts it; a 422
   * makes the caller retry without it (cubesat/wire.py StartRequest grows
   * the field separately). */
  policy?: string;
  /** Display-only sats[].risk overlay for this run (cubesat/wire.py:51,
   * StartRequest.predictor default false). Absent = the backend default. */
  predictor?: boolean;
}

/** FastAPI renders 422 two ways: an HTTPException detail is a string, a
 * request-body validation error is an array of {loc, msg}. Format both to a
 * single line so the server's validation detail can be shown verbatim
 * (mirrors api/scenarios.ts formatDetail). */
function formatDetail(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts: string[] = [];
    for (const item of detail) {
      if (item && typeof item === "object") {
        const rec = item as { loc?: unknown; msg?: unknown };
        const loc = Array.isArray(rec.loc) ? rec.loc.join(".") : "";
        const msg = typeof rec.msg === "string" ? rec.msg : "";
        parts.push(loc !== "" ? `${loc}: ${msg}` : msg);
      }
    }
    if (parts.length > 0) return parts.join("; ");
  }
  return null;
}

export async function postStart(body: StartBody): Promise<void> {
  let res: Response;
  try {
    res = await fetch("/simulation/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error(BACKEND_UNREACHABLE);
  }
  if (res.ok) return;
  const json = (await res.json().catch(() => null)) as unknown;
  const detail =
    json !== null && typeof json === "object"
      ? formatDetail((json as { detail?: unknown }).detail)
      : null;
  const err = new Error(
    detail ?? `POST /simulation/start failed (HTTP ${res.status})`,
  ) as StartError;
  err.status = res.status;
  throw err;
}
