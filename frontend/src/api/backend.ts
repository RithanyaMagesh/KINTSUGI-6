// Single REST client for the G5 backend (cubesat/api.py).
// Consolidates all HTTP calls and FastAPI 422/409 error formatting in one
// module (§3.2 #6, #7). Error semantics: non-2xx -> thrown ApiError (.status
// attached) with the backend detail verbatim; network failure -> actionable
// Error telling the operator what to do next (§13.6 voice).

const BACKEND_UNREACHABLE =
  "Backend unreachable — start it with: uv run uvicorn cubesat.api:app --port 8000";

export interface ApiError extends Error {
  status?: number;
}

/** FastAPI renders 422 two ways: an HTTPException detail is a string, a
 * request-body validation error is an array of {loc, msg}. Format both to a
 * single line so the server's validation detail can be shown verbatim. */
export function formatErrorDetail(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts: string[] = [];
    for (const item of detail) {
      if (item !== null && typeof item === "object") {
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

async function post(path: string, body?: unknown): Promise<Record<string, unknown>> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error(BACKEND_UNREACHABLE);
  }
  const json = (await res.json().catch(() => null)) as unknown;
  if (!res.ok) {
    const detail =
      json !== null && typeof json === "object"
        ? formatErrorDetail((json as { detail?: unknown }).detail)
        : null;
    const err = new Error(detail ?? `POST ${path} failed (HTTP ${res.status})`) as ApiError;
    err.status = res.status;
    throw err;
  }
  return json !== null && typeof json === "object" ? (json as Record<string, unknown>) : {};
}

async function get<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path);
  } catch {
    throw new Error(BACKEND_UNREACHABLE);
  }
  if (!res.ok) {
    const json = (await res.json().catch(() => null)) as unknown;
    const detail =
      json !== null && typeof json === "object"
        ? formatErrorDetail((json as { detail?: unknown }).detail)
        : null;
    const err = new Error(detail ?? `GET ${path} failed (HTTP ${res.status})`) as ApiError;
    err.status = res.status;
    throw err;
  }
  return (await res.json()) as T;
}

/** GET a replay log as text (FileResponse JSONL). Used once per load to read
 * the log's end time for the seek slider — parsing mirrors cubesat/replay.py's
 * defensive per-line read; any failure returns null and the slider is hidden,
 * never guessed. */
export async function replayFileText(filename: string): Promise<string | null> {
  let res: Response;
  try {
    res = await fetch(`/replay/file/${encodeURIComponent(filename)}`);
  } catch {
    return null;
  }
  if (!res.ok) return null;
  try {
    return await res.text();
  } catch {
    return null;
  }
}

/** End time of a replay log [s]: the t of its last parseable line. Null when
 * the file cannot be read — the seek slider is hidden rather than the duration
 * guessed (repo invariant 1). */
export async function replayLogDuration(filename: string): Promise<number | null> {
  const text = await replayFileText(filename);
  if (text === null) return null;
  const lines = text.split("\n");
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i].trim();
    if (line === "") continue;
    try {
      const t = (JSON.parse(line) as { t?: unknown }).t;
      if (typeof t === "number" && Number.isFinite(t)) return t;
    } catch {
      continue;
    }
  }
  return null;
}

export interface HealthResponse {
  status: string;
  mode: string;
  sim_time: number | null;
  scenario: string | null;
  paused: boolean;
}

export interface StartOptions {
  scenario: string | null;
  seed?: number | null;
  speed?: number;
  policy?: string;
  predictor?: boolean;
}

export interface StartResponse {
  status: string;
  mode: string;
  scenario: string | null;
  seed: number | null;
  speed: number;
  policy: string | null;
  predictor: boolean;
}

export interface ScenarioUploadResult {
  filename: string | null;
  scenarios: string[] | null;
}

/** POST /scenarios/upload {name, scenario} (cubesat/api.py UploadRequest). */
export async function uploadScenario(
  name: string | null,
  scenario: object,
): Promise<ScenarioUploadResult> {
  let saved: Record<string, unknown>;
  try {
    saved = await post("/scenarios/upload", { name, scenario });
  } catch (err) {
    const status = (err as ApiError).status;
    if (status === 404 || status === 405) {
      throw new Error("Custom scenario upload is not available on this backend");
    }
    throw err;
  }
  const filename = typeof saved.filename === "string" ? saved.filename : null;
  let scenarios: string[] | null = null;
  if (Array.isArray(saved.scenarios)) {
    scenarios = saved.scenarios.filter((s): s is string => typeof s === "string");
  } else {
    try {
      const listing = await get<{ scenarios: string[] }>("/scenarios");
      scenarios = Array.isArray(listing.scenarios) ? listing.scenarios : null;
    } catch {
      scenarios = null;
    }
  }
  return { filename, scenarios };
}

/** POST /simulation/speed {speed} — live-run speed (cubesat/wire.py SpeedRequest). */
export async function simulationSpeed(speed: number): Promise<void> {
  await post("/simulation/speed", { speed });
}

/** Unified POST /simulation/start carrying {scenario, seed, speed, policy, predictor}. */
export async function startSimulation(opts: StartOptions): Promise<StartResponse> {
  const payload: Record<string, unknown> = {
    scenario: opts.scenario,
  };
  if (opts.seed !== undefined) payload.seed = opts.seed;
  if (opts.speed !== undefined) payload.speed = opts.speed;
  if (opts.policy !== undefined) payload.policy = opts.policy;
  if (opts.predictor !== undefined) payload.predictor = opts.predictor;
  const raw = await post("/simulation/start", payload);
  return {
    status: typeof raw.status === "string" ? raw.status : "started",
    mode: typeof raw.mode === "string" ? raw.mode : "live",
    scenario: typeof raw.scenario === "string" ? raw.scenario : opts.scenario,
    seed: typeof raw.seed === "number" ? raw.seed : (opts.seed ?? null),
    speed: typeof raw.speed === "number" ? raw.speed : (opts.speed ?? 100),
    policy:
      typeof raw.policy === "string"
        ? raw.policy
        : opts.policy !== undefined
          ? opts.policy
          : null,
    predictor: typeof raw.predictor === "boolean" ? raw.predictor : Boolean(opts.predictor),
  };
}

export const backend = {
  health: () => get<HealthResponse>("/health"),
  scenarios: () => get<{ scenarios: string[] }>("/scenarios"),
  replayFiles: () => get<{ files: string[] }>("/replay/files"),
  uploadScenario,
  simulationSpeed,
  startSimulation,

  simulationStart: (
    scenario: string | null,
    seed: number | null = null,
    extra?: { speed?: number; policy?: string; predictor?: boolean },
  ) =>
    startSimulation({
      scenario,
      seed,
      speed: extra?.speed,
      policy: extra?.policy,
      predictor: extra?.predictor,
    }),
  simulationPause: () => post("/simulation/pause"),
  simulationResume: () => post("/simulation/resume"),
  simulationReset: () => post("/simulation/reset"),
  failureInject: (satId: string, mode: string, degrade_s: number = 0.0) =>
    post("/failure/inject", { sat_id: satId, mode, degrade_s }),

  replayLoad: (filename: string, speed = 100) =>
    post("/replay/load", { filename, speed }),
  replayPause: () => post("/replay/pause"),
  replayResume: () => post("/replay/resume"),
  replaySeek: (t: number) => post("/replay/seek", { t }),
  replaySpeed: (speed: number) => post("/replay/speed", { speed }),
  replayStop: () => post("/replay/stop"),
};
