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
