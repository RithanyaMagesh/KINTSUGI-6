import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev proxy keeps the vendored/no-CDN rule honest: the UI talks to the local
// FastAPI service (cubesat.api) exactly as it will in production, where the
// same app is mounted as static files from frontend/dist.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/ws": { target: "ws://localhost:8000", ws: true },
      "/health": "http://localhost:8000",
      "/scenarios": "http://localhost:8000",
      "/simulation": "http://localhost:8000",
      "/failure": "http://localhost:8000",
      "/replay": "http://localhost:8000",
    },
  },
  build: {
    target: "es2022",
  },
});
