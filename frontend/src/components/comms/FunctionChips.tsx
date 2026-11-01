// Leader functions as chips (Track C, decentral laser runs). One chip per
// function in FUNCTIONS order, showing who holds it now: one holder is a plain
// chip, two holders (split-brain, one per disconnected group) a warning chip,
// nobody an empty dashed chip. A chip whose holder just changed pulses in the
// repair colour for about 2 s. Holders come only from `sats[].functions`.
import { useEffect, useRef, useState } from "react";
import { useSimStore } from "../../stores/simStore";
import { FUNCTIONS, functionLabel } from "../live/hudFormat";
import styles from "./FunctionChips.module.css";

const PULSE_MS = 2000;

/** True when any satellite carries a `functions` list (decentral runs only). */
export function hasFunctions(sats: ReadonlyArray<{ functions?: string[] }>): boolean {
  return sats.some((s) => s.functions !== undefined);
}

export default function FunctionChips() {
  const sats = useSimStore((s) => s.satellites);
  const splitBrain = useSimStore((s) => s.splitBrain);

  const holders: Record<string, string[]> = {};
  for (const f of FUNCTIONS) holders[f] = [];
  for (const sat of sats) {
    if (sat.status === "failed") continue;
    for (const f of sat.functions ?? []) {
      (holders[f] ??= []).push(sat.id);
    }
  }
  const keyOf = (f: string) => holders[f].join(",");

  // Pulse a chip when its holder set differs from the previous frame's.
  const prev = useRef<Record<string, string> | null>(null);
  const [pulse, setPulse] = useState<Record<string, number>>({});
  const signature = FUNCTIONS.map(keyOf).join("|");
  useEffect(() => {
    const now: Record<string, string> = {};
    for (const f of FUNCTIONS) now[f] = keyOf(f);
    const before = prev.current;
    prev.current = now;
    if (before === null) return;
    const changed = FUNCTIONS.filter((f) => before[f] !== now[f]);
    if (changed.length === 0) return;
    const stamp = Date.now();
    setPulse((p) => {
      const next = { ...p };
      for (const f of changed) next[f] = stamp;
      return next;
    });
    const timer = window.setTimeout(() => {
      setPulse((p) => {
        const next: Record<string, number> = {};
        for (const [f, t] of Object.entries(p)) if (Date.now() - t < PULSE_MS) next[f] = t;
        return next;
      });
    }, PULSE_MS + 50);
    return () => window.clearTimeout(timer);
  }, [signature]);

  if (!hasFunctions(sats)) return null;

  return (
    <ul className={styles.chips} aria-label="Leader functions and who holds them">
      {FUNCTIONS.map((f) => {
        const who = holders[f];
        const split = who.length > 1 || splitBrain.includes(f);
        const vacant = who.length === 0;
        return (
          <li
            // remount on a holder change so the pulse animation restarts
            key={`${f}-${pulse[f] ?? 0}`}
            className={styles.chip}
            data-state={vacant ? "vacant" : split ? "split" : "held"}
            data-pulse={pulse[f] !== undefined || undefined}
          >
            <span className={styles.name}>{functionLabel(f)}:</span>{" "}
            <span className={styles.holder}>
              {vacant ? "nobody" : who.join(", ")}
              {split && !vacant && <span className={styles.warn}> (two holders)</span>}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
