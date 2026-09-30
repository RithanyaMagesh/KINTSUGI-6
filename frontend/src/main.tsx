import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles/tokens.css";
import "./styles/globals.css";
import App from "./App";
import { useSimStore } from "./stores/simStore";
import { MOCK_EVENTS, MOCK_FRAMES, mockEnabled } from "./dev/mockFrame";

// Dev-only mock injection (§13.6): never runs in a production build and never
// without an explicit ?mock=1 query parameter. See src/dev/mockFrame.ts.
if (mockEnabled()) {
  const sim = useSimStore.getState();
  sim.setMode("live");
  for (const frame of MOCK_FRAMES) sim.applyMessage(frame);
  for (const event of MOCK_EVENTS) sim.applyMessage(event);
}

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
