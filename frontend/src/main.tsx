import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles/tokens.css";
import "./styles/globals.css";
import App from "./App";
import { useSimStore } from "./stores/simStore";
import { useRecoveryStore } from "./stores/recoveryStore";
import { useRoleHistoryStore } from "./stores/roleHistoryStore";
import { MOCK_EVENTS, MOCK_FRAMES, mockEnabled } from "./dev/mockFrame";

// Dev-only mock injection (§13.6): never runs in a production build and never
// without an explicit ?mock=1 query parameter. See src/dev/mockFrame.ts.
if (mockEnabled()) {
  // Same funnel as the live socket (useWebSocket.onmessage): each store runs
  // the shared deserializer, so mock mode shows role history + SUSPECT too.
  const sim = useSimStore.getState();
  const recovery = useRecoveryStore.getState();
  const roleHistory = useRoleHistoryStore.getState();
  sim.setMode("live");
  for (const frame of MOCK_FRAMES) {
    sim.applyMessage(frame);
    recovery.ingest(frame);
    roleHistory.ingest(frame);
  }
  for (const event of MOCK_EVENTS) {
    sim.applyMessage(event);
    recovery.ingest(event);
    roleHistory.ingest(event);
  }
}

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
