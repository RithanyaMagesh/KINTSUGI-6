// Live WebSocket driver — FRONTEND_SPEC §6.1 + §16.5.
// - auto-reconnect (1 s, 2 s, 4 s … capped at 10 s)
// - mandatory 30 s client ping {"type":"ping"} (Render free-tier keepalive)
// - every message goes through ONE funnel: simStore.applyMessage (console
//   state), recoveryStore.ingest (recovery story) and roleHistoryStore.ingest
//   (role history + suspects) all receive the SAME parsed message; each store
//   parses it through the ONE shared deserializer (src/api/deserializer.ts).
// - connection state mirrors the socket so TopStatusBar can render it
import { useEffect } from "react";
import { useSimStore } from "../stores/simStore";
import { useRecoveryStore } from "../stores/recoveryStore";
import { useRoleHistoryStore } from "../stores/roleHistoryStore";
import { stateSocketUrl } from "../api/websocket";

const PING_INTERVAL_MS = 30_000;
const RECONNECT_MAX_MS = 10_000;

export function useWebSocket(): void {
  const applyMessage = useSimStore((s) => s.applyMessage);
  const setConnection = useSimStore((s) => s.setConnection);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let pingTimer: number | null = null;
    let reconnectTimer: number | null = null;
    let attempt = 0;
    let closedByUs = false;

    function startPing(ws: WebSocket): void {
      if (pingTimer !== null) window.clearInterval(pingTimer);
      pingTimer = window.setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "ping" }));
        }
      }, PING_INTERVAL_MS);
    }

    function connect(): void {
      setConnection("reconnecting"); // "connected" only once onopen fires
      try {
        socket = new WebSocket(stateSocketUrl());
      } catch {
        // A synchronous construction failure (bad URL, queue limits) must
        // retry with the same backoff instead of dead-ending (§6.1).
        socket = null;
        attempt += 1;
        setConnection("reconnecting");
        reconnectTimer = window.setTimeout(
          connect,
          Math.min(1000 * 2 ** (attempt - 1), RECONNECT_MAX_MS),
        );
        return;
      }

      socket.onopen = () => {
        attempt = 0;
        setConnection("connected");
        startPing(socket as WebSocket);
      };
      socket.onmessage = (ev) => {
        try {
          // One parse, three consumers — the shared deserializer inside each
          // store re-validates the same object (no second JSON.parse).
          const parsed: unknown = JSON.parse(ev.data as string);
          applyMessage(parsed);
          useRecoveryStore.getState().ingest(parsed);
          useRoleHistoryStore.getState().ingest(parsed);
        } catch {
          // A malformed frame is dropped, never crashes the console (§6.1).
        }
      };
      socket.onclose = () => {
        if (pingTimer !== null) window.clearInterval(pingTimer);
        if (closedByUs) return;
        setConnection("reconnecting");
        attempt += 1;
        const delay = Math.min(1000 * 2 ** (attempt - 1), RECONNECT_MAX_MS);
        reconnectTimer = window.setTimeout(connect, delay);
      };
      socket.onerror = () => {
        socket?.close();
      };
    }

    connect();

    return () => {
      closedByUs = true;
      if (pingTimer !== null) window.clearInterval(pingTimer);
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [applyMessage, setConnection]);
}
