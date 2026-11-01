// Track C wire (laser links, swarm groups, consensus auction) against real
// frames captured from the two demo scenarios (fixtures README).
import { beforeEach, describe, expect, it } from "vitest";
import { deserializeMessage } from "./deserializer";
import { useSimStore } from "../stores/simStore";
import dec from "../test/fixtures/decentral_laser.json";
import cen from "../test/fixtures/central_laser.json";

const frames = (msgs: unknown[]) =>
  msgs.map((m) => deserializeMessage(m)).flatMap((d) => (d?.kind === "frame" ? [d.frame] : []));
const at = (msgs: unknown[], t: number) => frames(msgs).find((f) => f.simTime === t)!;

describe("deserializer", () => {
  it("parses links with display ids, state, range and rate", () => {
    const f = at(dec, 1370);
    expect(f.links!.length).toBeGreaterThan(0);
    expect(f.links![0]).toMatchObject({ a: expect.stringMatching(/^SAT-/), b: expect.stringMatching(/^SAT-/) });
    expect(["LOCKED", "ACQUIRING", "DOWN"]).toContain(f.links![0].state);
  });

  it("parses groups, split-brain, vacant functions and consensus rounds", () => {
    const f = at(dec, 1370);
    expect(f.components).toHaveLength(2);
    expect(f.splitBrain).toContain("time_sync");
    expect(f.functionsVacant).toEqual([]);
    expect(typeof f.consensusRounds).toBe("number");
    expect(f.satellites.find((s) => s.id === "SAT-2")!.functions).toBeDefined();
  });

  it("marks sats outside the main group as cut off, never the dead one", () => {
    const f = at(cen, 1204); // the hub died: every sat is alone
    const live = f.satellites.filter((s) => s.status !== "failed");
    expect(live.every((s) => s.cutOff === true)).toBe(true);
    expect(f.satellites.find((s) => s.id === "SAT-1")!.cutOff).toBeUndefined();
    const sun = at(cen, 1356); // SAT-3 alone, the rest together
    expect(sun.satellites.find((s) => s.id === "SAT-3")!.cutOff).toBe(true);
    expect(sun.satellites.find((s) => s.id === "SAT-2")!.cutOff).toBeUndefined();
  });

  it("central (star) runs carry no consensus-auction keys", () => {
    const f = frames(cen)[0];
    expect(f.consensusRounds).toBeUndefined();
    expect(f.satellites[0].functions).toBeUndefined();
  });

  it("reads the formation shape off the hello", () => {
    const h = (cen as unknown[]).map((m) => deserializeMessage(m)).find((d) => d?.kind === "hello");
    expect(h).toMatchObject({ formationShape: "cartwheel" });
  });

  it("keeps FUNCTION_HANDOFF holder lists and link extras", () => {
    const evs = (dec as unknown[]).map((m) => deserializeMessage(m)).flatMap((d) => (d?.kind === "event" ? [d.event] : []));
    const h = evs.find((e) => e.fn === "time_sync" && (e.toSats?.length ?? 0) > 1)!;
    expect(h.fromSats).toEqual(["SAT-3"]);
    expect(h.toSats).toEqual(["SAT-4", "SAT-6"]);
    expect(evs.find((e) => e.reason === "sun")!.link).toHaveLength(2);
  });
});

describe("store", () => {
  beforeEach(() => useSimStore.getState().reset());

  it("turns function handoffs into batons, one per new holder, none for a holder that keeps it", () => {
    (dec as unknown[]).forEach((m) => useSimStore.getState().applyMessage(m));
    const h = useSimStore.getState().handoffs;
    expect(h).toContainEqual(expect.objectContaining({ role: "time_sync", from: "SAT-3", to: "SAT-4", t: 1370 }));
    expect(h).toContainEqual(expect.objectContaining({ role: "time_sync", from: "SAT-3", to: "SAT-6", t: 1370 }));
    // heal at 1550 is outside the fixture; a "from A,B to A" move never makes A->A
    expect(h.some((x) => x.from === x.to)).toBe(false);
  });

  it("keeps the latest links and groups, and the hello's formation shape", () => {
    (cen as unknown[]).forEach((m) => useSimStore.getState().applyMessage(m));
    const s = useSimStore.getState();
    expect(s.links.length).toBeGreaterThan(0);
    expect(s.components.length).toBeGreaterThan(0);
    expect(s.formationShape).toBe("cartwheel");
  });
});
