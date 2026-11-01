// simStore against real wire bytes (fixtures in src/test/fixtures/).
import { beforeEach, describe, expect, it } from "vitest";
import { useSimStore } from "./simStore";
import v2 from "../test/fixtures/v2_live.json";
import v1 from "../test/fixtures/v1_leader_failure.json";

const feed = (msgs: unknown[]) => msgs.forEach((m) => useSimStore.getState().applyMessage(m));

beforeEach(() => useSimStore.getState().reset());

describe("role handoffs (batons)", () => {
  it("records the leader moving to a new holder on a v2 run", () => {
    feed(v2);
    expect(useSimStore.getState().handoffs).toContainEqual(
      expect.objectContaining({ role: "leader", from: "SAT-1", to: "SAT-3" }),
    );
  });

  it("records both handoffs of the v1 kept-formation replan once each", () => {
    feed(v1);
    const h = useSimStore.getState().handoffs;
    expect(h.filter((x) => x.role === "leader")).toEqual([
      expect.objectContaining({ from: "SAT-1", to: "SAT-3", t: 2408 }),
    ]);
    expect(h.filter((x) => x.role === "downlink")).toEqual([
      expect.objectContaining({ from: "SAT-6", to: "SAT-5", t: 2408 }),
    ]);
  });
});

describe("reassignment and summary", () => {
  it("keeps kept_formation and method on the last reassignment", () => {
    feed(v1);
    const r = useSimStore.getState().lastReassignment!;
    expect(r.keptFormation).toBe(true);
    expect(r.method).toBe("do_no_harm_hold");
  });

  it("stores the run summary and clears it on a new run", () => {
    feed(v2);
    expect(useSimStore.getState().runSummary?.coverageMeanLastOrbit).toBeCloseTo(0.252, 3);
    useSimStore.getState().applyMessage({ type: "sim_state", sim_time: 0, state: "NOMINAL", scenario: "x", seed: 1, sats: [], coverage: null, min_sep: null, metrics: {} });
    expect(useSimStore.getState().runSummary).toBeNull();
  });

  it("keeps every event, several per tick included", () => {
    feed(v2);
    expect(useSimStore.getState().events.filter((e) => e.simTime === 1912)).toHaveLength(2);
  });
});
