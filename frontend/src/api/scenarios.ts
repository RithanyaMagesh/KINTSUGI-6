// Re-exports from the consolidated REST client (api/backend.ts) so existing
// imports keep working with zero duplicate fetch/error-formatting logic.
export {
  uploadScenario,
  simulationSpeed,
  type ScenarioUploadResult,
} from "./backend";
