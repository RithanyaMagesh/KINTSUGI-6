// Re-exports unified simulation start from api/backend.ts so ScenarioBuilder
// and any callers share one implementation of POST /simulation/start.
import {
  startSimulation,
  type ApiError,
  type StartOptions,
  type StartResponse,
} from "../../api/backend";
import { useSimStore } from "../../stores/simStore";
import type { FormationShape } from "./scenarioDraft";

export type StartError = ApiError;
export type StartBody = StartOptions;
export type { StartResponse };

/** Shape of a ready-made scenario, read from its file name
 * (data/scenarios/formation_<shape>_6sat.json); null = unknown. Any other
 * file may be a cartwheel or not, so it stays unknown. */
export function shapeFromScenarioFile(file: string | null | undefined): FormationShape | null {
  const m = /^formation_(pco|gco|helix|string)_/.exec(file ?? "");
  return m !== null ? (m[1] as FormationShape) : null;
}

/** POST /simulation/start. `shape` is the formation the caller knows it
 * started (the builder, or a demo button); leave it out for a ready-made
 * scenario and the shape is read from the file name. */
export async function postStart(
  body: StartBody,
  shape?: FormationShape | null,
): Promise<StartResponse> {
  const res = await startSimulation(body);
  // shortcut: the live hello carries formation_shape only on connect
  useSimStore.setState({
    formationShape: shape !== undefined ? shape : shapeFromScenarioFile(body.scenario),
  });
  return res;
}
