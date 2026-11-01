// Auction board — makes a reassignment burst visible on the main live screen.
// Decentral laser runs: the latest FUNCTION_HANDOFF burst (same sim tick), as
// "Consensus auction" with the round count. Central runs: the latest leader /
// downlink handoff, as "Role reassignment". The wire carries only the winners
// and the round count, so no bids or scores are shown. The card stays about
// 8 s (wall clock) after the last burst, then fades; it can be closed.
import { useEffect, useMemo, useRef, useState } from "react";
import { useSimStore } from "../../stores/simStore";
import type { SimEvent } from "../../types/events";
import { functionLabel, roleLabel } from "../live/hudFormat";
import styles from "./AuctionBoard.module.css";

const HOLD_MS = 8000;
const FADE_MS = 600;

type Tone = "ok" | "split" | "vacant";
interface BoardRow {
  key: string;
  text: string;
  tone: Tone;
}
interface Burst {
  id: string;
  title: string;
  rows: BoardRow[];
  decentral: boolean;
}

const list = (ids: string[]) =>
  ids.length <= 1 ? ids.join("") : `${ids.slice(0, -1).join(", ")} and ${ids[ids.length - 1]}`;

function fnRow(e: SimEvent): BoardRow {
  const name = functionLabel(e.fn ?? "");
  const to = e.toSats ?? [];
  const from = e.fromSats ?? [];
  if (to.length === 0) return { key: e.fn ?? name, text: `${name}: nobody holds it`, tone: "vacant" };
  if (to.length > 1)
    return { key: e.fn ?? name, text: `${name}: two holders, ${list(to)} (swarm split)`, tone: "split" };
  const was = from.filter((f) => f !== to[0]);
  return {
    key: e.fn ?? name,
    text: `${name}: won by ${to[0]}${was.length > 0 ? ` (was ${list(was)})` : ""}`,
    tone: "ok",
  };
}

export default function AuctionBoard() {
  const events = useSimStore((s) => s.events);
  const handoffs = useSimStore((s) => s.handoffs);
  const rounds = useSimStore((s) => s.consensusRounds);

  // The newest burst, from whichever source the run speaks.
  const burst = useMemo<Burst | null>(() => {
    let lastFn: SimEvent | undefined;
    for (let i = events.length - 1; i >= 0; i--) {
      if (events[i].fn !== undefined) {
        lastFn = events[i];
        break;
      }
    }
    if (lastFn !== undefined) {
      const t = lastFn.simTime;
      const byFn = new Map<string, SimEvent>();
      for (const e of events) if (e.fn !== undefined && e.simTime === t) byFn.set(e.fn, e);
      return { id: `fn-${t}-${byFn.size}`, title: "Consensus auction", rows: [...byFn.values()].map(fnRow), decentral: true };
    }
    const crit = handoffs.filter((h) => h.role === "leader" || h.role === "downlink");
    if (crit.length === 0) return null;
    const t = crit[crit.length - 1].t;
    const rows = crit
      .filter((h) => h.t === t)
      .map((h) => ({ key: `${h.role}-${h.to}`, text: `${roleLabel(h.role)}: ${h.to} took over from ${h.from}`, tone: "ok" as Tone }));
    return { id: `role-${t}-${rows.length}`, title: "Role reassignment", rows, decentral: false };
  }, [events, handoffs]);

  // Show a burst only when it is new since mount; hold, fade, hide.
  const [seen] = useState<string | null>(() => burst?.id ?? null);
  const [shown, setShown] = useState<Burst | null>(null);
  const [phase, setPhase] = useState<"in" | "out">("in");
  // Restart the hold only when a NEW burst lands, not on every later event.
  const latest = useRef(burst);
  latest.current = burst;
  const burstId = burst?.id ?? null;
  useEffect(() => {
    const b = latest.current;
    if (b === null || b.id === seen) return;
    setShown(b);
    setPhase("in");
    const fade = window.setTimeout(() => setPhase("out"), HOLD_MS);
    const hide = window.setTimeout(() => setShown(null), HOLD_MS + FADE_MS);
    return () => {
      window.clearTimeout(fade);
      window.clearTimeout(hide);
    };
  }, [burstId, seen]);

  if (shown === null) return null;

  return (
    <section key={shown.id} className={styles.card} data-phase={phase} aria-live="polite" aria-label={shown.title}>
      <header className={styles.head}>
        <h2 className={styles.title}>{shown.title}</h2>
        {shown.decentral && rounds !== null && <span className={styles.rounds}>{rounds} rounds</span>}
        <button type="button" className={styles.close} onClick={() => setShown(null)} aria-label="Close">
          Close
        </button>
      </header>
      <ul className={styles.rows}>
        {shown.rows.map((r, i) => (
          <li key={r.key} className={styles.row} data-tone={r.tone} style={{ animationDelay: `${i * 150}ms` }}>
            {r.text}
          </li>
        ))}
      </ul>
      {shown.decentral && (
        <p className={styles.foot}>
          Each satellite bids for the functions it can do best; the swarm agrees on winners without a leader. One round is one 2 s tick
          (assumption).
        </p>
      )}
    </section>
  );
}
