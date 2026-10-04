// REST client for the G5 backend (cubesat/api.py). Error semantics:
// non-2xx -> thrown Error with the backend detail; network failure -> thrown
// Error telling the operator what to do next (§13.6 voice).

async function post(path: string, body?: unknown): Promise<Record<string, unknown>> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error("Backend unreachable — start it with: uv run uvicorn cubesat.api:app --port 8000");
  }
  if (!res.ok) {
    const detail = await res
      .json()
      .then((j) => (j && typeof j.detail === "string" ? j.detail : null))
      .catch(() => null);
    throw new Error(detail ?? `POST ${path} failed (HTTP ${res.status})`);
  }
  return (await res.json()) as Record<string, unknown>;
}

async function get<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path);
  } catch {
    throw new Error("Backend unreachable — start it with: uv run uvicorn cubesat.api:app --port 8000");
  }
  if (!res.ok) throw new Error(`GET ${path} failed (HTTP ${res.status})`);
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
 * guessed (repo invariant 1). Shared so every replay-load path (ReplayControls
 * "Load replay", the mission brief, PresentationView's openReplay) measures the
 * same way. */
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
      continue; // skip unparsable tail lines, keep scanning backwards
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

export const backend = {
  health: () => get<HealthResponse>("/health"),
  scenarios: () => get<{ scenarios: string[] }>("/scenarios"),
  replayFiles: () => get<{ files: string[] }>("/replay/files"),

  simulationStart: (scenario: string | null, seed: number | null) =>
    post("/simulation/start", { scenario, seed }),
  simulationPause: () => post("/simulation/pause"),
  simulationResume: () => post("/simulation/resume"),
  simulationReset: () => post("/simulation/reset"),
  failureInject: (satId: string, mode: "DEAD" | "THRUSTER_OUT") =>
    post("/failure/inject", { sat_id: satId, mode }),

  replayLoad: (filename: string, speed = 100) =>
    post("/replay/load", { filename, speed }),
  replayPause: () => post("/replay/pause"),
  replayResume: () => post("/replay/resume"),
  replaySeek: (t: number) => post("/replay/seek", { t }),
  replaySpeed: (speed: number) => post("/replay/speed", { speed }),
  replayStop: () => post("/replay/stop"),
};
