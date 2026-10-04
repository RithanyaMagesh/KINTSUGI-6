// G5 console endpoints that are NOT in api/backend.ts — backend.ts sits
// outside this task's file ownership, so its new call functions live here
// instead (same error semantics: non-2xx -> thrown Error with the backend
// detail; network failure -> thrown Error telling the operator what to do).

const BACKEND_UNREACHABLE =
  "Backend unreachable — start it with: uv run uvicorn cubesat.api:app --port 8000";

/** FastAPI renders 422 two ways: an HTTPException detail is a string, a
 * request-body validation error is an array of {loc, msg}. Format both to a
 * single line so the server's validation detail can be shown verbatim. */
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

interface PostResult {
  status: number;
  json: Record<string, unknown> | null;
}

async function postJson(path: string, body: unknown): Promise<PostResult> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error(BACKEND_UNREACHABLE);
  }
  const json = (await res.json().catch(() => null)) as unknown;
  if (res.ok) {
    return {
      status: res.status,
      json: json !== null && typeof json === "object" ? (json as Record<string, unknown>) : {},
    };
  }
  const detail =
    json !== null && typeof json === "object"
      ? formatDetail((json as { detail?: unknown }).detail)
      : null;
  const err = new Error(detail ?? `POST ${path} failed (HTTP ${res.status})`) as Error & {
    status?: number;
  };
  err.status = res.status;
  throw err;
}

async function getScenarios(): Promise<string[]> {
  let res: Response;
  try {
    res = await fetch("/scenarios");
  } catch {
    throw new Error(BACKEND_UNREACHABLE);
  }
  if (!res.ok) throw new Error(`GET /scenarios failed (HTTP ${res.status})`);
  const data = (await res.json().catch(() => null)) as { scenarios?: unknown } | null;
  const list = data !== null && Array.isArray(data.scenarios) ? data.scenarios : [];
  return list.filter((name): name is string => typeof name === "string");
}

export interface ScenarioUploadResult {
  /** File name the backend saved (cubesat/api.py returns candidate.name);
   * null when the response did not report one. */
  filename: string | null;
  /** Refreshed scenario listing from the backend response, or from a
   * follow-up GET /scenarios; null when neither could be read. */
  scenarios: string[] | null;
}

/** POST /scenarios/upload {name, scenario} (cubesat/api.py UploadRequest).
 * 404/405 mean the backend predates the upload route and could not be
 * restarted — reported honestly so the UI can say so. 422 surfaces the
 * server's validation detail (name sanitation, scenario schema); 409 the
 * duplicate-name refusal. */
export async function uploadScenario(
  name: string | null,
  scenario: object,
): Promise<ScenarioUploadResult> {
  let saved: PostResult;
  try {
    saved = await postJson("/scenarios/upload", { name, scenario });
  } catch (err) {
    if (err instanceof Error && (err as Error & { status?: number }).status !== undefined) {
      const status = (err as Error & { status?: number }).status;
      if (status === 404 || status === 405) {
        throw new Error("Custom scenario upload is not available on this backend");
      }
    }
    throw err;
  }
  let filename: string | null = null;
  if (saved.json !== null && typeof saved.json.filename === "string") {
    filename = saved.json.filename;
  }
  let scenarios: string[] | null = null;
  if (saved.json !== null && Array.isArray(saved.json.scenarios)) {
    scenarios = saved.json.scenarios.filter((s): s is string => typeof s === "string");
  } else {
    try {
      scenarios = await getScenarios();
    } catch {
      scenarios = null; // listing refresh failed; the saved file still exists
    }
  }
  return { filename, scenarios };
}

/** POST /simulation/speed {speed} — live-run speed (cubesat/wire.py
 * SpeedRequest: float > 0; session.set_speed raises 409 otherwise). */
export async function simulationSpeed(speed: number): Promise<void> {
  await postJson("/simulation/speed", { speed });
}
