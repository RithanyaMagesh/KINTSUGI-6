// Re-exports unified simulation start from api/backend.ts so ScenarioBuilder
// and any callers share one implementation of POST /simulation/start.
import {
  startSimulation,
  type ApiError,
  type StartOptions,
  type StartResponse,
} from "../../api/backend";

export type StartError = ApiError;
export type StartBody = StartOptions;
export type { StartResponse };

export async function postStart(body: StartBody): Promise<StartResponse> {
  return startSimulation(body);
}
